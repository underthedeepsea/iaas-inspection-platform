import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, override_settings

from apps.core.models import Environment
from apps.assets.models import Asset
from apps.inspections.models import MockDataset, MockEvent, MockLog
from apps.mockdata import internal_views, public_views


def _user(*roles):
    user = get_user_model().objects.create_user(
        username=f"mock-api-{uuid.uuid4().hex}", password="password"
    )
    for role in roles:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


def _request(method, path, *, user=None, payload=None, token=None, query=None):
    factory = RequestFactory()
    body = json.dumps(payload).encode() if payload is not None else b""
    request = getattr(factory, method.lower())(
        path + (f"?{query}" if query else ""),
        data=body,
        content_type="application/json",
        **({"HTTP_X_INTERNAL_TOKEN": token} if token else {}),
    )
    request.user = user or SimpleNamespace(is_authenticated=False)
    return request


def _body(response):
    return json.loads(response.content.decode())


@pytest.mark.django_db
def test_authenticated_operator_can_generate_and_bounded_dataset_detail_has_no_raw_rows():
    from apps.audits.models import AuditEvent

    operator = _user("operator")
    environment = Environment.objects.create(name="Mock", slug=f"mock-{uuid.uuid4().hex}")
    payload = {
        "environment_id": str(environment.pk),
        "scenario": "llm_scheduler_pressure",
        "dataset_date": "2026-08-23",
        "seed": 1729,
    }
    response = public_views.generate(_request("POST", "/mock-datasets/generate/", user=operator, payload=payload))
    assert response.status_code == 201
    dataset_id = _body(response)["dataset_id"]
    assert AuditEvent.objects.filter(object_type="MockDataset", object_id=dataset_id).exists()

    detail = public_views.detail(_request("GET", "/mock-datasets/x/", user=operator), dataset_id)
    assert detail.status_code == 200
    body = _body(detail)
    assert body["metric_count"] > 0
    assert "metrics" not in body and "logs" not in body and "events" not in body


@pytest.mark.django_db
def test_mock_dataset_generation_rejects_unauthorized_and_invalid_scenario():
    environment = Environment.objects.create(name="Mock", slug=f"mock-{uuid.uuid4().hex}")
    payload = {
        "environment_id": str(environment.pk),
        "scenario": "llm_scheduler_pressure",
        "dataset_date": "2026-08-23",
        "seed": 1729,
    }
    assert public_views.generate(_request("POST", "/mock-datasets/generate/", payload=payload)).status_code == 401
    assert public_views.generate(
        _request("POST", "/mock-datasets/generate/", user=_user("viewer"), payload=payload)
    ).status_code == 403
    payload["scenario"] = "run-arbitrary-script"
    assert public_views.generate(
        _request("POST", "/mock-datasets/generate/", user=_user("operator"), payload=payload)
    ).status_code == 400


@pytest.mark.django_db
@override_settings(MOCK_INTERNAL_TOKEN="test-token")
def test_internal_mock_queries_require_token_and_return_bounded_rows():
    operator = _user("operator")
    environment = Environment.objects.create(name="Mock", slug=f"mock-{uuid.uuid4().hex}")
    generated = public_views.generate(
        _request(
            "POST", "/mock-datasets/generate/", user=operator,
            payload={
                "environment_id": str(environment.pk),
                "scenario": "llm_scheduler_pressure",
                "dataset_date": "2026-08-23",
                "seed": 1729,
            },
        )
    )
    dataset_id = _body(generated)["dataset_id"]
    payload = {"dataset_id": dataset_id, "metric_names": ["ttft_ms"], "limit": 1}
    denied = internal_views.metrics(_request("POST", "/mock/metrics/query/", payload=payload))
    assert denied.status_code == 403

    response = internal_views.metrics(
        _request("POST", "/mock/metrics/query/", payload=payload, token="test-token")
    )
    assert response.status_code == 200
    assert len(_body(response)["items"]) <= 1

    unbounded = internal_views.logs(
        _request("POST", "/mock/logs/search/", payload={"dataset_id": dataset_id, "limit": 1000}, token="test-token")
    )
    assert unbounded.status_code == 400


@pytest.mark.django_db
@override_settings(MOCK_INTERNAL_TOKEN="test-token")
def test_internal_mock_rows_redact_secret_like_text_and_nested_metadata():
    operator = _user("operator")
    environment = Environment.objects.create(name="Mock", slug=f"mock-{uuid.uuid4().hex}")
    generated = public_views.generate(
        _request(
            "POST", "/mock-datasets/generate/", user=operator,
            payload={
                "environment_id": str(environment.pk),
                "scenario": "llm_scheduler_pressure",
                "dataset_date": "2026-08-23",
                "seed": 1729,
            },
        )
    )
    dataset_id = _body(generated)["dataset_id"]
    dataset = MockDataset.objects.get(pk=dataset_id)
    log = MockLog.objects.filter(dataset=dataset).order_by("-ts", "-pk").first()
    event = MockEvent.objects.filter(dataset=dataset).order_by("-ts", "-pk").first()
    asset = Asset.objects.filter(environment=environment).order_by("external_key").first()
    assert log is not None and event is not None and asset is not None
    log.message = "password=top-secret provider=https://private.example"
    log.save(update_fields=["message"])
    event.reason = "authorization: Bearer top-secret"
    event.message = "token=top-secret"
    event.save(update_fields=["reason", "message"])
    asset_key = asset.external_key
    asset.labels = {"safe": "yes", "api_key": "top-secret"}
    asset.topology = {"zone": "prod", "nested": {"token": "top-secret"}}
    asset.save(update_fields=["labels", "topology"])

    logs = internal_views.logs(
        _request("POST", "/mock/logs/search/", payload={"dataset_id": dataset_id, "limit": 100}, token="test-token")
    )
    events = internal_views.events(
        _request("POST", "/mock/events/query/", payload={"dataset_id": dataset_id, "limit": 100}, token="test-token")
    )
    topology = internal_views.topology(
        _request(
            "POST", "/mock/topology/query/",
            payload={"dataset_id": dataset_id, "asset_ids": [asset_key], "limit": 100},
            token="test-token",
        )
    )
    assert logs.status_code == events.status_code == topology.status_code == 200
    assert "top-secret" not in logs.content.decode()
    assert "top-secret" not in events.content.decode()
    topology_body = _body(topology)
    assert any(row["labels"] == {"safe": "yes"} for row in topology_body["items"])
    assert all("api_key" not in row["labels"] for row in topology_body["items"])
    assert all("token" not in row["topology"].get("nested", {}) for row in topology_body["items"])
