import json
import os
import re
import uuid
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, RequestFactory, override_settings

from apps.api.auth import owned_or_404, require_role, require_session
from apps.api.http import (
    APIRequestError,
    api_error,
    parse_bool,
    parse_json_object,
    parse_positive_int,
)
from apps.api.pagination import paginate


def _user(*groups, is_superuser=False):
    user = get_user_model().objects.create_user(
        username=f"api-{uuid.uuid4().hex}",
        password="password",
        is_superuser=is_superuser,
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _request(*, user=None, query_string=""):
    request = RequestFactory().get("/" + (f"?{query_string}" if query_string else ""))
    request.user = user or SimpleNamespace(is_authenticated=False)
    return request


def _body(response):
    return json.loads(response.content.decode("utf-8"))


def test_api_error_has_stable_envelope_and_trace_id():
    response = api_error("VALIDATION_ERROR", "bad request", status=400)

    assert response.status_code == 400
    body = _body(response)
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "trace_id"}
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"] == {}
    assert re.fullmatch(r"tr_[0-9a-f]{32}", body["error"]["trace_id"])


@pytest.mark.parametrize("raw", [b"[1]", b"null", b'"text"', b"not-json"])
def test_parse_json_object_rejects_non_object_payloads(raw):
    request = RequestFactory().post("/", data=raw, content_type="application/json")

    with pytest.raises(APIRequestError) as error:
        parse_json_object(request)

    assert error.value.code == "VALIDATION_ERROR"


def test_parse_json_object_accepts_only_utf8_json_objects():
    request = RequestFactory().post(
        "/", data=json.dumps({"enabled": True}), content_type="application/json"
    )

    assert parse_json_object(request) == {"enabled": True}


@pytest.mark.parametrize("raw", [1, 0, "true", "false", "1", "yes", None, []])
def test_parse_bool_requires_a_real_boolean(raw):
    with pytest.raises(APIRequestError):
        parse_bool(raw)


@pytest.mark.parametrize("raw", [True, False, 1.0, "01", " 1", "1 ", "1.0", "-1", 0])
def test_parse_positive_int_rejects_bool_and_non_canonical_values(raw):
    with pytest.raises(APIRequestError):
        parse_positive_int(raw)


def test_parse_positive_int_applies_default_and_upper_bound():
    assert parse_positive_int(None, default=50, maximum=100) == 50
    assert parse_positive_int("50", default=50, maximum=100) == 50
    with pytest.raises(APIRequestError):
        parse_positive_int("101", default=50, maximum=100)


@pytest.mark.django_db
def test_session_and_role_hierarchy_support_groups_and_superusers():
    anonymous = _request()
    session_error = require_session(anonymous)
    assert session_error.status_code == 401
    assert _body(session_error)["error"]["code"] == "AUTH_REQUIRED"

    viewer = _user("viewer")
    operator = _user("operator")
    admin = _user("platform_admin")
    superuser = _user(is_superuser=True)
    for user in (viewer, operator, admin, superuser):
        request = _request(user=user)
        assert require_session(request) is None

    assert require_role(_request(user=viewer), "viewer") is None
    assert require_role(_request(user=viewer), "operator").status_code == 403
    assert require_role(_request(user=operator), "viewer") is None
    assert require_role(_request(user=operator), "platform_admin").status_code == 403
    assert require_role(_request(user=admin), "platform_admin") is None
    assert require_role(_request(user=superuser), "platform_admin") is None


@pytest.mark.django_db
def test_owned_or_404_scopes_queryset_to_user_when_model_has_user_field():
    owner = _user("viewer")
    stranger = _user("viewer")
    owned = SimpleNamespace(pk=1, user_id=owner.pk)
    queryset = [owned]

    assert owned_or_404(queryset, owner, pk=1) is owned
    with pytest.raises(Exception) as error:
        owned_or_404(queryset, stranger, pk=1)
    assert getattr(error.value, "status_code", 404) == 404


def test_paginate_uses_bounded_defaults_and_serializer():
    response = paginate(list(range(120)), _request(), lambda value: {"value": value})

    assert response.status_code == 200
    assert _body(response) == {
        "items": [{"value": value} for value in range(50)],
        "page": 1,
        "page_size": 50,
        "total": 120,
    }


def test_paginate_rejects_invalid_or_unbounded_parameters():
    assert paginate(list(range(2)), _request(query_string="page=0"), lambda value: value).status_code == 400
    assert paginate(list(range(2)), _request(query_string="page_size=1001"), lambda value: value).status_code == 400


@pytest.mark.django_db
def test_health_is_anonymous_and_reports_database_state_without_external_calls():
    client = Client()
    with override_settings(API_HEALTH_CHECKS={"ollama": lambda: False, "airflow": lambda: True}):
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "ok"
    assert body["ollama"] == "error"
    assert body["airflow"] == "ok"
    assert set(body) == {"status", "database", "ollama", "airflow", "version"}


def test_product_info_is_anonymous_and_has_exact_numeric_versions():
    response = Client().get("/api/v1/product-info")

    assert response.status_code == 200
    body = response.json()
    assert body["product_name"] == "IaaS 智能巡检"
    assert body["data_mode"] == "MOCK"
    assert body["llm_provider"] == os.getenv("LLM_PROVIDER", "fake")
    assert body["security_mode"] == "READ_ONLY_TOOLS"
    assert body["versions"] == {
        "django": "4.2.16",
        "airflow": "2.3.2",
        "langgraph": "1.2.10",
        "langchain": "1.3.14",
    }


def test_local_development_defaults_to_deterministic_ai_provider():
    assert settings.LLM_PROVIDER == os.getenv("LLM_PROVIDER", "fake")


@pytest.mark.django_db
def test_health_database_failure_is_reported_without_external_network():
    client = Client()
    with override_settings(API_HEALTH_DATABASE_CHECK=lambda: False):
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "error"
