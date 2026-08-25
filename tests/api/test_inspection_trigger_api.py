import json
import uuid
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory

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
    resource_type = ResourceType.objects.get(code="LLM_RUNTIME")
    item = make_item()
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    Asset.objects.create(
        environment=environment,
        external_key=f"llm-{uuid.uuid4().hex}",
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
