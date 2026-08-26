import json
import uuid
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, override_settings

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemResourceType, InspectionRun, ResourceType


def make_user():
    user = get_user_model().objects.create_user(
        username=f"trigger-{uuid.uuid4().hex}",
        password="password",
    )
    group, _ = Group.objects.get_or_create(name="operator")
    user.groups.add(group)
    return user


def make_request(user, payload):
    request = RequestFactory().post(
        "/api/v1/inspection-runs/trigger",
        data=json.dumps(payload),
        content_type="application/json",
    )
    request.user = user
    return request


def make_environment():
    return Environment.objects.create(
        name="Trigger API",
        slug=f"trigger-{uuid.uuid4().hex}",
    )


def make_item():
    return InspectionItem.objects.create(
        code=f"trigger.item.{uuid.uuid4().hex}",
        name="Trigger item",
        domain="LLM",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


@pytest.mark.django_db
def test_empty_resource_types_returns_400():
    from apps.operations_api import views

    response = views.trigger_inspection_run(
        make_request(
            make_user(),
            {"environment_id": str(make_environment().id), "scope": {"resource_types": []}},
        )
    )

    assert response.status_code == 400
    assert json.loads(response.content)["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_unknown_resource_type_returns_structured_400():
    from apps.operations_api import views

    response = views.trigger_inspection_run(
        make_request(
            make_user(),
            {
                "environment_id": str(make_environment().id),
                "scope": {"resource_types": ["NO_SUCH_TYPE"]},
            },
        )
    )

    assert response.status_code == 400
    assert json.loads(response.content)["error"]["code"] == "RESOURCE_TYPE_NOT_FOUND"


@pytest.mark.django_db
def test_valid_request_freezes_requested_and_resolved_scope():
    from apps.operations_api import views

    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="LLM_RUNTIME",
        defaults={
            "name": "LLM 推理引擎",
            "asset_selector": {"asset_types": [Asset.AssetType.LLM_INSTANCE]},
        },
    )
    resource_type.enabled = True
    resource_type.save(update_fields=["enabled"])
    item = make_item()
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    Asset.objects.create(
        environment=environment,
        external_key="llm-0",
        asset_type=Asset.AssetType.LLM_INSTANCE,
        name="LLM instance",
    )

    response = views.trigger_inspection_run(
        make_request(
            make_user(),
            {
                "environment_id": str(environment.id),
                "scope": {"resource_types": ["LLM_RUNTIME"]},
                "trigger_options": {"ai_mode": "DEFERRED"},
            },
        )
    )

    assert response.status_code == 201
    body = json.loads(response.content)
    run = InspectionRun.objects.get(pk=body["id"])
    assert run.trigger_type == InspectionRun.TriggerType.MANUAL
    assert run.status == InspectionRun.Status.PENDING
    assert run.config_snapshot["requested_scope"] == {"resource_types": ["LLM_RUNTIME"]}
    assert run.config_snapshot["resolved_scope"]["resource_types"] == ["LLM_RUNTIME"]
    assert run.config_snapshot["resolved_scope"]["asset_count"] == 1
    assert body["scope"] == {
        "resource_types": ["LLM_RUNTIME"],
        "asset_count": 1,
        "inspection_item_count": 1,
    }


@pytest.mark.django_db(transaction=True)
def test_valid_manual_trigger_binds_ready_dataset_and_enqueues_full_run(monkeypatch):
    from apps.operations_api import views

    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="LLM_RUNTIME",
        defaults={
            "name": "LLM 推理引擎",
            "asset_selector": {"asset_types": [Asset.AssetType.LLM_INSTANCE]},
        },
    )
    resource_type.enabled = True
    resource_type.save(update_fields=["enabled"])
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=make_item())
    enqueued = []
    monkeypatch.setattr(
        views,
        "enqueue_manual_inspection",
        lambda run_id: enqueued.append(str(run_id)),
        raising=False,
    )

    response = views.trigger_inspection_run(
        make_request(
            make_user(),
            {
                "environment_id": str(environment.id),
                "scope": {"resource_types": ["LLM_RUNTIME"]},
            },
        )
    )

    assert response.status_code == 201
    body = json.loads(response.content)
    run = InspectionRun.objects.select_related("dataset").get(pk=body["id"])
    assert run.dataset_id is not None
    assert run.dataset.environment_id == environment.id
    assert run.dataset.dataset_date == run.run_date
    assert run.dataset.status == run.dataset.Status.READY
    assert body["dataset_id"] == str(run.dataset_id)
    assert enqueued == [str(run.id)]


@pytest.mark.django_db(transaction=True)
@override_settings(
    MANUAL_INSPECTION_SEED=20260823,
    MANUAL_INSPECTION_SCENARIO="llm_scheduler_pressure",
)
def test_http_trigger_enters_the_full_manual_orchestrator(monkeypatch):
    from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
    from apps.operations_api import views

    environment = make_environment()
    resource_type, _ = ResourceType.objects.get_or_create(
        code="LLM_RUNTIME",
        defaults={
            "name": "LLM 推理引擎",
            "asset_selector": {"asset_types": [Asset.AssetType.LLM_INSTANCE]},
        },
    )
    resource_type.enabled = True
    resource_type.save(update_fields=["enabled"])
    item = make_item()
    item.required_claims = ["llm.performance.status"]
    item.save(update_fields=["required_claims", "updated_at"])
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    monkeypatch.setattr(
        views,
        "enqueue_manual_inspection",
        lambda run_id: start_manual_inspection_run(run_id),
    )

    response = views.trigger_inspection_run(
        make_request(
            make_user(),
            {
                "environment_id": str(environment.id),
                "scope": {"resource_types": ["LLM_RUNTIME"]},
            },
        )
    )

    assert response.status_code == 201
    run = InspectionRun.objects.get(pk=json.loads(response.content)["id"])
    assert run.status == InspectionRun.Status.SUCCEEDED
    assert run.dataset_id is not None
    assert run.resource_summaries.exists()
    assert run.events.filter(event_type="run.completed").exists()
