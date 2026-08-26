import uuid

import pytest
from django.test import Client, override_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import (
    InspectionItem,
    InspectionItemResourceType,
    InspectionRun,
    InspectionRunEvent,
    ResourceInspectionSummary,
    ResourceType,
)
from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
from apps.inspections.services.trigger import create_manual_inspection_run


def make_environment():
    return Environment.objects.create(name="Manual lifecycle", slug=f"manual-{uuid.uuid4().hex}")


def make_item():
    return InspectionItem.objects.create(
        code=f"manual.lifecycle.{uuid.uuid4().hex}",
        name="Manual lifecycle item",
        domain="CONTROL_PLANE",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        required_claims=[],
    )


def make_viewer():
    user = get_user_model().objects.create_user(username=f"manual-viewer-{uuid.uuid4().hex}", password="password")
    group, _ = Group.objects.get_or_create(name="viewer")
    user.groups.add(group)
    return user


@pytest.mark.django_db(transaction=True)
@override_settings(
    MANUAL_INSPECTION_SEED=20260823,
    MANUAL_INSPECTION_SCENARIO="control_plane_anti_affinity",
)
def test_manual_run_uses_production_orchestrator_and_publishes_resource_summary():
    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="CONTROL_PLANE",
        defaults={
            "name": "控制面",
            "asset_selector": {"asset_types": [Asset.AssetType.POD]},
            "sort_order": 10,
        },
    )
    resource_type.enabled = True
    resource_type.save(update_fields=["enabled"])
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=make_item())
    run = create_manual_inspection_run(
        environment=environment,
        resource_type_codes=[resource_type.code],
    )
    assert run.dataset_id is not None
    start_manual_inspection_run(run.pk)

    run.refresh_from_db()
    assert run.status == InspectionRun.Status.SUCCEEDED
    assert {
        event.event_type
        for event in InspectionRunEvent.objects.filter(inspection_run=run)
    } >= {
        "scope.resolved",
        "assets.discovered",
        "inspection.item.started",
        "inspection.item.progress",
        "inspection.item.completed",
        "risk.correlation.started",
        "risk.correlation.completed",
        "summary.completed",
        "run.completed",
    }
    summary = ResourceInspectionSummary.objects.get(inspection_run=run, resource_type=resource_type)
    assert summary.health_score is not None

    viewer = Client()
    viewer.force_login(make_viewer())
    history = viewer.get(
        f"/api/v1/resource-types/{resource_type.code}/inspection-history",
        {"environment_id": str(environment.pk)},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1

    resource_types = viewer.get("/api/v1/resource-types", {"environment_id": str(environment.pk)})
    control_plane = next(item for item in resource_types.json()["items"] if item["code"] == resource_type.code)
    assert control_plane["health_score"] is not None


@pytest.mark.django_db(transaction=True)
@override_settings(
    MANUAL_INSPECTION_SEED=20260823,
    MANUAL_INSPECTION_SCENARIO="control_plane_anti_affinity",
)
def test_manual_orchestrator_resumes_a_claimed_run_after_worker_restart():
    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="CONTROL_PLANE",
        defaults={
            "name": "控制面",
            "asset_selector": {"asset_types": [Asset.AssetType.POD]},
            "sort_order": 10,
        },
    )
    resource_type.enabled = True
    resource_type.save(update_fields=["enabled"])
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=make_item())
    run = create_manual_inspection_run(
        environment=environment,
        resource_type_codes=[resource_type.code],
    )
    snapshot = dict(run.config_snapshot)
    snapshot["batch"] = {"manual_orchestrator_claimed": True}
    run.config_snapshot = snapshot
    run.save(update_fields=["config_snapshot"])

    start_manual_inspection_run(run.pk)

    run.refresh_from_db()
    assert run.status == InspectionRun.Status.SUCCEEDED
    assert run.events.filter(event_type="run.completed").count() == 1
