"""Route-level contracts for the documented public REST surface.

The matrix deliberately uses empty/missing resources: it checks that the
documented URL reaches the right view and crosses its auth/method boundary,
without coupling the route test to domain fixture shape.
"""

import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, override_settings


RESOURCE_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
ITEM_RUN_ID = uuid.uuid4()
FEEDBACK_ID = uuid.uuid4()
EXPERIENCE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()


def _user(role):
    user = get_user_model().objects.create_user(
        username=f"contract-matrix-{role}-{uuid.uuid4().hex}", password="password"
    )
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)
    return user


def _request(client, method, path):
    if not path.endswith("/"):
        path += "/"
    return client.generic(
        method,
        path,
        data=json.dumps({}),
        content_type="application/json",
    )


# Sections 38-49.  ``expected`` is the response from an authenticated user
# with the minimum role for the endpoint.  Collection/detail distinctions make
# an unmounted route fail RED even when the fallback returns a 404.
ROUTES = (
    ("GET", "/api/v1/health", None, 200),
    ("GET", "/api/v1/product-info", None, 200),
    ("GET", "/api/v1/dashboard/today", "viewer", 404),
    ("GET", "/api/v1/daily-snapshots", "viewer", 200),
    ("GET", f"/api/v1/daily-snapshots/{RESOURCE_ID}", "viewer", 404),
    ("GET", "/api/v1/inspection-items", "viewer", 200),
    ("GET", f"/api/v1/inspection-items/{RESOURCE_ID}", "viewer", 404),
    ("POST", f"/api/v1/inspection-items/{RESOURCE_ID}/ask", "viewer", 400),
    ("POST", "/api/v1/inspection-runs/trigger", "operator", 400),
    ("GET", "/api/v1/inspection-runs", "viewer", 200),
    ("GET", f"/api/v1/inspection-runs/{RUN_ID}", "viewer", 404),
    ("GET", f"/api/v1/inspection-item-runs/{ITEM_RUN_ID}", "viewer", 404),
    ("GET", "/api/v1/findings", "viewer", 200),
    ("GET", "/api/v1/risks", "viewer", 200),
    ("GET", f"/api/v1/risks/{RESOURCE_ID}", "viewer", 404),
    ("GET", f"/api/v1/risks/{RESOURCE_ID}/timeline", "viewer", 404),
    ("GET", f"/api/v1/risks/{RESOURCE_ID}/evidence", "viewer", 404),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/mark-handled", "operator", 404),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/ignore", "operator", 400),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/reverify", "operator", 404),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/investigations", "viewer", 400),
    ("GET", "/api/v1/capabilities", "viewer", 200),
    ("GET", f"/api/v1/capabilities/matrix-{RESOURCE_ID}", "viewer", 404),
    ("POST", "/api/v1/capabilities", "platform_admin", 400),
    ("POST", f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions", "platform_admin", 404),
    (
        "POST",
        f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions/1.0.0/test",
        "platform_admin",
        404,
    ),
    (
        "POST",
        f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions/1.0.0/shadow",
        "platform_admin",
        404,
    ),
    (
        "POST",
        f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions/1.0.0/activate",
        "platform_admin",
        404,
    ),
    ("POST", "/api/v1/capabilities/resolve", "viewer", 400),
    ("POST", "/api/v1/conversations", "viewer", 400),
    ("GET", f"/api/v1/conversations/{RESOURCE_ID}", "viewer", 404),
    ("GET", f"/api/v1/conversations/{RESOURCE_ID}/messages", "viewer", 404),
    ("POST", f"/api/v1/conversations/{RESOURCE_ID}/turns", "viewer", 400),
    (
        "GET",
        f"/api/v1/conversations/{RESOURCE_ID}/turns/{RUN_ID}/events",
        "viewer",
        404,
    ),
    ("POST", f"/api/v1/conversations/{RESOURCE_ID}/close", "viewer", 404),
    ("GET", f"/api/v1/investigations/{RESOURCE_ID}", "viewer", 404),
    ("GET", f"/api/v1/investigations/{RESOURCE_ID}/events", "viewer", 404),
    ("GET", f"/api/v1/investigations/{RESOURCE_ID}/tool-calls", "viewer", 404),
    ("POST", f"/api/v1/investigations/{RESOURCE_ID}/cancel", "operator", 404),
    ("POST", "/api/v1/feedback", "operator", 400),
    ("GET", "/api/v1/feedback", "viewer", 200),
    ("POST", f"/api/v1/feedback/{FEEDBACK_ID}/create-experience", "operator", 404),
    ("GET", "/api/v1/experiences", "viewer", 200),
    ("GET", f"/api/v1/experiences/{EXPERIENCE_ID}", "viewer", 404),
    ("POST", f"/api/v1/experiences/{EXPERIENCE_ID}/confirm", "operator", 404),
    (
        "POST",
        f"/api/v1/experiences/{EXPERIENCE_ID}/codeization-tasks",
        "operator",
        404,
    ),
    ("GET", "/api/v1/codeization-tasks", "viewer", 200),
    ("PATCH", f"/api/v1/codeization-tasks/{TASK_ID}", "operator", 404),
    ("POST", "/api/v1/mock-datasets/generate", "operator", 400),
    ("GET", "/api/v1/mock-datasets", "viewer", 200),
    ("GET", f"/api/v1/mock-datasets/{RESOURCE_ID}", "viewer", 404),
)


@pytest.mark.django_db
def test_every_section_38_to_49_route_requires_expected_method_auth_and_role():
    anonymous = Client()
    users = {role: _user(role) for role in {row[2] for row in ROUTES if row[2]}}

    for method, path, role, expected in ROUTES:
        if role is None:
            response = _request(anonymous, method, path)
            assert response.status_code == expected, (method, path, response.content)
            continue

        response = _request(anonymous, method, path)
        assert response.status_code == 401, (method, path, response.content)
        body = response.json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"code", "message", "details", "trace_id"}
        assert body["error"]["code"] == "AUTH_REQUIRED"

        response = _request(Client(), method, path)
        # A fresh client is anonymous too; keep this assertion close to the
        # route loop so accidental session leakage cannot hide a route error.
        assert response.status_code == 401

        client = Client()
        client.force_login(users[role])
        response = _request(client, method, path)
        assert response.status_code == expected, (method, path, response.content)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path,role",
    [
        ("POST", "/api/v1/health", "viewer"),
        ("POST", "/api/v1/product-info", "viewer"),
        ("POST", "/api/v1/daily-snapshots", "viewer"),
        ("POST", "/api/v1/inspection-items", "viewer"),
        ("GET", f"/api/v1/inspection-items/{RESOURCE_ID}/ask", "viewer"),
        ("GET", "/api/v1/inspection-runs/trigger", "operator"),
        ("POST", "/api/v1/inspection-runs", "viewer"),
        ("POST", "/api/v1/findings", "viewer"),
        ("POST", "/api/v1/risks", "viewer"),
        ("GET", f"/api/v1/risks/{RESOURCE_ID}/ignore", "operator"),
        ("GET", "/api/v1/capabilities/resolve", "viewer"),
        ("GET", "/api/v1/conversations", "viewer"),
        ("POST", f"/api/v1/conversations/{RESOURCE_ID}/messages", "viewer"),
        ("GET", f"/api/v1/conversations/{RESOURCE_ID}/close", "viewer"),
        ("POST", f"/api/v1/conversations/{RESOURCE_ID}", "viewer"),
        ("POST", f"/api/v1/investigations/{RESOURCE_ID}/events", "viewer"),
        ("GET", f"/api/v1/feedback/{FEEDBACK_ID}/create-experience", "operator"),
        ("POST", "/api/v1/experiences", "viewer"),
        ("GET", f"/api/v1/experiences/{EXPERIENCE_ID}/confirm", "operator"),
        ("POST", "/api/v1/codeization-tasks", "viewer"),
        ("GET", f"/api/v1/codeization-tasks/{TASK_ID}", "operator"),
    ],
)
def test_documented_route_rejects_unsupported_method(method, path, role):
    user = _user(role)
    client = Client()
    client.force_login(user)
    response = _request(client, method, path)
    assert response.status_code == 405, (method, path, response.content)
    assert set(response.json()["error"]) == {"code", "message", "details", "trace_id"}
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path,required_role",
    [
        ("POST", "/api/v1/capabilities", "platform_admin"),
        ("POST", "/api/v1/capabilities/matrix/versions", "platform_admin"),
        ("POST", "/api/v1/inspection-runs/trigger", "operator"),
        ("POST", f"/api/v1/risks/{RESOURCE_ID}/mark-handled", "operator"),
        ("POST", f"/api/v1/investigations/{RESOURCE_ID}/cancel", "operator"),
        ("POST", "/api/v1/feedback", "operator"),
        ("POST", f"/api/v1/experiences/{RESOURCE_ID}/confirm", "operator"),
    ],
)
def test_role_bound_routes_reject_viewer_before_resource_lookup(path, method, required_role):
    viewer = _user("viewer")
    client = Client()
    client.force_login(viewer)
    response = _request(client, method, path)
    assert response.status_code == 403, (method, path, response.content)
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


@pytest.mark.django_db
@override_settings(MOCK_INTERNAL_TOKEN="matrix-token")
def test_internal_mock_routes_use_token_auth_without_session_auth():
    client = Client()
    for path in (
        "/api/internal/v1/mock/metrics/query",
        "/api/internal/v1/mock/logs/search",
        "/api/internal/v1/mock/events/query",
        "/api/internal/v1/mock/topology/query",
    ):
        denied = _request(client, "POST", path)
        assert denied.status_code == 403, (path, denied.content)
        allowed = client.post(
            path,
            data=json.dumps({"dataset_id": str(RESOURCE_ID)}),
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN="matrix-token",
        )
        assert allowed.status_code == 404, (path, allowed.content)


@pytest.mark.django_db
def test_mounted_public_slices_accept_no_slash_prefixes():
    viewer = _user("viewer")
    client = Client()
    client.force_login(viewer)
    assert client.get("/api/v1/capabilities").status_code == 200
    assert client.get("/api/v1/feedback").status_code == 200
    assert client.get("/api/v1/mock-datasets").status_code == 200
    assert client.get(f"/api/v1/investigations/{RESOURCE_ID}").status_code == 404
    assert client.post(
        "/api/v1/conversations",
        data=json.dumps({}),
        content_type="application/json",
    ).status_code == 400
