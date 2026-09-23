import uuid

import pytest
from django.test import Client

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
        code="llm.performance_profile",
        name="Manual lifecycle item",
        domain="LLM_RUNTIME",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        required_claims=[],
    )




@pytest.mark.django_db(transaction=True)
def test_manual_run_uses_production_orchestrator_and_publishes_resource_summary():
    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="LLM_RUNTIME",
        defaults={
            "name": "LLM 运行时",
            "asset_selector": {"asset_types": [Asset.AssetType.LLM_INSTANCE], "labels": {"input_source": "INFERENCE_SNAPSHOT"}},
            "sort_order": 10,
        },
    )
    resource_type.enabled = True
    resource_type.asset_selector = {"asset_types": [Asset.AssetType.LLM_INSTANCE], "labels": {"input_source": "INFERENCE_SNAPSHOT"}}
    resource_type.save(update_fields=["enabled", "asset_selector"])
    Asset.objects.create(environment=environment, external_key='inference:manual', asset_type=Asset.AssetType.LLM_INSTANCE, name='Engine', labels={'input_source': 'INFERENCE_SNAPSHOT'})
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=make_item())
    run = create_manual_inspection_run(
        environment=environment,
        resource_type_codes=[resource_type.code],
    )
    assert run.dataset_id is None
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
    event_types = list(
        InspectionRunEvent.objects.filter(inspection_run=run)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )
    assert event_types.index("inspection.started") < event_types.index("inspection.completed")
    assert event_types.index("inspection.completed") < event_types.index("risk.correlation.started")
    assert "ai.admission.started" not in event_types
    assert event_types.index("risk.correlation.completed") < event_types.index("summary.started")
    summary = ResourceInspectionSummary.objects.get(inspection_run=run, resource_type=resource_type)
    assert summary.health_score is None
    assert summary.summary['data_state'] == 'UNKNOWN'

    viewer = Client()

    history = viewer.get(
        f"/api/v1/resource-types/{resource_type.code}/inspection-history",
        {"environment_id": str(environment.pk)},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1

    resource_types = viewer.get("/api/v1/resource-types", {"environment_id": str(environment.pk)})
    runtime = next(item for item in resource_types.json()["items"] if item["code"] == resource_type.code)
    assert runtime["health_score"] is None


@pytest.mark.django_db(transaction=True)
def test_manual_orchestrator_resumes_a_claimed_run_after_worker_restart():
    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="LLM_RUNTIME",
        defaults={
            "name": "LLM 运行时",
            "asset_selector": {"asset_types": [Asset.AssetType.LLM_INSTANCE], "labels": {"input_source": "INFERENCE_SNAPSHOT"}},
            "sort_order": 10,
        },
    )
    resource_type.enabled = True
    resource_type.asset_selector = {"asset_types": [Asset.AssetType.LLM_INSTANCE], "labels": {"input_source": "INFERENCE_SNAPSHOT"}}
    resource_type.save(update_fields=["enabled", "asset_selector"])
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
