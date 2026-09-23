"""Route-level contracts for the documented public REST surface.

The matrix deliberately uses empty/missing resources: it checks that the
documented URL reaches the right view and crosses its method and validation boundary,
without coupling the route test to domain fixture shape.
"""

import json
import uuid

import pytest
from django.test import Client, override_settings


RESOURCE_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
ITEM_RUN_ID = uuid.uuid4()
FEEDBACK_ID = uuid.uuid4()
EXPERIENCE_ID = uuid.uuid4()
TASK_ID = uuid.uuid4()




def _request(client, method, path):
    if not path.endswith("/"):
        path += "/"
    return client.generic(
        method,
        path,
        data=json.dumps({}),
        content_type="application/json",
    )


# Sections 38-49.  ``expected`` is the response from an anonymous request
# Collection/detail distinctions make
# an unmounted route fail RED even when the fallback returns a 404.
ROUTES = (
    ("GET", "/api/v1/health", 200),
    ("GET", "/api/v1/product-info", 200),
    ("GET", "/api/v1/dashboard/today", 404),
    ("GET", "/api/v1/daily-snapshots", 200),
    ("GET", f"/api/v1/daily-snapshots/{RESOURCE_ID}", 404),
    ("GET", "/api/v1/inspection-items", 200),
    ("GET", f"/api/v1/inspection-items/{RESOURCE_ID}", 404),
    ("POST", f"/api/v1/inspection-items/{RESOURCE_ID}/ask", 400),
    ("POST", "/api/v1/inspection-runs/trigger", 400),
    ("GET", "/api/v1/inspection-runs", 200),
    ("GET", f"/api/v1/inspection-runs/{RUN_ID}", 404),
    ("GET", f"/api/v1/inspection-item-runs/{ITEM_RUN_ID}", 404),
    ("GET", "/api/v1/findings", 200),
    ("GET", "/api/v1/risks", 200),
    ("GET", f"/api/v1/risks/{RESOURCE_ID}", 404),
    ("GET", f"/api/v1/risks/{RESOURCE_ID}/timeline", 404),
    ("GET", f"/api/v1/risks/{RESOURCE_ID}/evidence", 404),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/mark-handled", 404),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/ignore", 400),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/reverify", 404),
    ("POST", f"/api/v1/risks/{RESOURCE_ID}/investigations", 400),
    ("GET", "/api/v1/capabilities", 200),
    ("GET", f"/api/v1/capabilities/matrix-{RESOURCE_ID}", 404),
    ("POST", "/api/v1/capabilities", 400),
    ("POST", f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions", 404),
    (
        "POST",
        f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions/1.0.0/test",
        404,
    ),
    (
        "POST",
        f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions/1.0.0/shadow",
        404,
    ),
    (
        "POST",
        f"/api/v1/capabilities/matrix-{RESOURCE_ID}/versions/1.0.0/activate",
        404,
    ),
    ("POST", "/api/v1/capabilities/resolve", 400),
    ("POST", "/api/v1/conversations", 400),
    ("GET", f"/api/v1/conversations/{RESOURCE_ID}", 404),
    ("GET", f"/api/v1/conversations/{RESOURCE_ID}/messages", 404),
    ("POST", f"/api/v1/conversations/{RESOURCE_ID}/turns", 400),
    (
        "GET",
        f"/api/v1/conversations/{RESOURCE_ID}/turns/{RUN_ID}/events",
        404,
    ),
    ("POST", f"/api/v1/conversations/{RESOURCE_ID}/close", 404),
    ("GET", f"/api/v1/investigations/{RESOURCE_ID}", 404),
    ("GET", f"/api/v1/investigations/{RESOURCE_ID}/events", 404),
    ("GET", f"/api/v1/investigations/{RESOURCE_ID}/tool-calls", 404),
    ("POST", f"/api/v1/investigations/{RESOURCE_ID}/cancel", 404),
    ("POST", "/api/v1/feedback", 400),
    ("GET", "/api/v1/feedback", 200),
    ("POST", f"/api/v1/feedback/{FEEDBACK_ID}/create-experience", 404),
    ("GET", "/api/v1/experiences", 200),
    ("GET", f"/api/v1/experiences/{EXPERIENCE_ID}", 404),
    ("POST", f"/api/v1/experiences/{EXPERIENCE_ID}/confirm", 404),
    (
        "POST",
        f"/api/v1/experiences/{EXPERIENCE_ID}/codeization-tasks",
        404,
    ),
    ("GET", "/api/v1/codeization-tasks", 200),
    ("PATCH", f"/api/v1/codeization-tasks/{TASK_ID}", 404),
    ("POST", "/api/v1/mock-datasets/generate", 404),
    ("GET", "/api/v1/mock-datasets", 200),
    ("GET", f"/api/v1/mock-datasets/{RESOURCE_ID}", 404),
)


@pytest.mark.django_db
def test_every_section_38_to_49_route_enforces_anonymous_method_and_validation_contract():
    for method, path, expected in ROUTES:
        response = _request(Client(), method, path)
        assert response.status_code == expected, (method, path, response.content)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/health"),
        ("POST", "/api/v1/product-info"),
        ("POST", "/api/v1/daily-snapshots"),
        ("POST", "/api/v1/inspection-items"),
        ("GET", f"/api/v1/inspection-items/{RESOURCE_ID}/ask"),
        ("GET", "/api/v1/inspection-runs/trigger"),
        ("POST", "/api/v1/inspection-runs"),
        ("POST", "/api/v1/findings"),
        ("POST", "/api/v1/risks"),
        ("GET", f"/api/v1/risks/{RESOURCE_ID}/ignore"),
        ("GET", "/api/v1/capabilities/resolve"),
        ("GET", "/api/v1/conversations"),
        ("POST", f"/api/v1/conversations/{RESOURCE_ID}/messages"),
        ("GET", f"/api/v1/conversations/{RESOURCE_ID}/close"),
        ("POST", f"/api/v1/conversations/{RESOURCE_ID}"),
        ("POST", f"/api/v1/investigations/{RESOURCE_ID}/events"),
        ("GET", f"/api/v1/feedback/{FEEDBACK_ID}/create-experience"),
        ("POST", "/api/v1/experiences"),
        ("GET", f"/api/v1/experiences/{EXPERIENCE_ID}/confirm"),
        ("POST", "/api/v1/codeization-tasks"),
        ("GET", f"/api/v1/codeization-tasks/{TASK_ID}"),
    ],
)
def test_documented_route_rejects_unsupported_method(method, path):
    client = Client()

    response = _request(client, method, path)
    assert response.status_code == 405, (method, path, response.content)
    assert set(response.json()["error"]) == {"code", "message", "details", "trace_id"}
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/capabilities"),
        ("POST", "/api/v1/capabilities/matrix/versions"),
        ("POST", "/api/v1/inspection-runs/trigger"),
        ("POST", f"/api/v1/risks/{RESOURCE_ID}/mark-handled"),
        ("POST", f"/api/v1/investigations/{RESOURCE_ID}/cancel"),
        ("POST", "/api/v1/feedback"),
        ("POST", f"/api/v1/experiences/{RESOURCE_ID}/confirm"),
    ],
)
def test_anonymous_mutations_validate_input_and_resource_lookup(path, method):
    client = Client()

    response = _request(client, method, path)
    assert response.status_code == (400 if path in {"/api/v1/capabilities", "/api/v1/inspection-runs/trigger", "/api/v1/feedback"} else 404), (method, path, response.content)
    assert response.json()["error"]["code"] in {"VALIDATION_ERROR", "NOT_FOUND"}


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
    client = Client()

    assert client.get("/api/v1/capabilities").status_code == 200
    assert client.get("/api/v1/feedback").status_code == 200
    assert client.get("/api/v1/mock-datasets").status_code == 200
    assert client.get(f"/api/v1/investigations/{RESOURCE_ID}").status_code == 404
    assert client.post(
        "/api/v1/conversations",
        data=json.dumps({}),
        content_type="application/json",
    ).status_code == 400
