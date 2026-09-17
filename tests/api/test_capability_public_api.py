import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from apps.audits.models import AuditEvent
from apps.capabilities.models import Capability, CapabilityVersion
from apps.capability_api import views




def _request(method, path, *, user=None, payload=None, query=None):
    factory = RequestFactory()
    body = json.dumps(payload).encode() if payload is not None else b""
    request = getattr(factory, method.lower())(
        path + (f"?{query}" if query else ""),
        data=body,
        content_type="application/json",
    )

    return request


def _body(response):
    return json.loads(response.content.decode())


def _capability(**values):
    values.setdefault("capability_id", f"network.api.{uuid.uuid4().hex}")
    values.setdefault("name", "RX path resolver")
    values.setdefault("domain", "network")
    return Capability.objects.create(**values)


@pytest.mark.django_db
def test_capability_list_is_anonymous_and_supports_bounded_filters():
    capability = _capability(domain="network", status=Capability.Status.ACTIVE)

    anonymous = views.collection(_request("GET", "/capabilities/"))
    assert anonymous.status_code == 200

    response = views.collection(
        _request("GET", "/capabilities/", user=None, query="domain=network&page_size=1")
    )
    assert response.status_code == 200
    assert _body(response)["items"][0]["capability_id"] == capability.capability_id
    assert _body(response)["page_size"] == 1


@pytest.mark.django_db
def test_admin_can_create_capability_and_numeric_version_with_audit():
    admin = None
    payload = {
        "capability_id": "network.api.pressure",
        "name": "Pressure resolver",
        "domain": "network",
        "description": "bounded resolver",
        "read_only": True,
    }
    created = views.collection(_request("POST", "/capabilities/", user=admin, payload=payload))
    assert created.status_code == 201
    capability = Capability.objects.get(capability_id=payload["capability_id"])
    assert AuditEvent.objects.filter(object_type="Capability", object_id=str(capability.pk)).exists()

    invalid = views.versions(
        _request("POST", "/capabilities/network.api.pressure/versions/", user=admin,
                 payload={"version": "1.0", "implementation_type": "RULE"}),
        capability.capability_id,
    )
    assert invalid.status_code == 400

    valid = views.versions(
        _request(
            "POST", "/capabilities/network.api.pressure/versions/", user=admin,
            payload={
                "version": "1.0.0",
                "implementation_type": "RULE",
                "resolves": ["network.pressure"],
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "manifest": {"rule": {"all": [], "result": "PRESSURE"}},
            },
        ),
        capability.capability_id,
    )
    assert valid.status_code == 201
    assert CapabilityVersion.objects.filter(capability=capability, version="1.0.0").exists()
    assert AuditEvent.objects.filter(object_type="CapabilityVersion").exists()


@pytest.mark.django_db
def test_shadow_then_activate_requires_read_only_schema_and_demo_thresholds():
    admin = None
    capability = _capability(read_only=True)
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="0.9.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.CANDIDATE,
        resolves=["network.pressure"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        manifest={"rule": {"all": [], "result": "PRESSURE"}},
    )
    shadow = views.shadow(
        _request("POST", "/capabilities/x/versions/x/shadow/", user=admin),
        capability.capability_id,
        version.version,
    )
    assert shadow.status_code == 200
    version.refresh_from_db()
    assert version.status == CapabilityVersion.Status.SHADOW

    not_ready = views.activate(
        _request("POST", "/capabilities/x/versions/x/activate/", user=admin,
                 payload={"shadow_cases": 2, "precision": 0.8, "critical_false_positive": 0}),
        capability.capability_id,
        version.version,
    )
    assert not_ready.status_code == 400
    assert CapabilityVersion.objects.get(pk=version.pk).status == CapabilityVersion.Status.SHADOW

    active = views.activate(
        _request("POST", "/capabilities/x/versions/x/activate/", user=admin,
                 payload={"shadow_cases": 3, "precision": 0.8, "critical_false_positive": 0}),
        capability.capability_id,
        version.version,
    )
    assert active.status_code == 200
    version.refresh_from_db()
    capability.refresh_from_db()
    assert version.status == CapabilityVersion.Status.ACTIVE
    assert capability.current_version_id == version.pk


@pytest.mark.django_db
def test_resolve_returns_active_read_only_candidates_without_executing_input():
    admin = None
    capability = _capability(read_only=True)
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        resolves=["network.pressure"],
        semantic_tags=["network"],
        subjects=["host"],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    capability.current_version = version
    capability.save(update_fields=["current_version"])

    response = views.resolve(
        _request(
            "POST", "/capabilities/resolve/", user=admin,
            payload={"claim": "network.pressure", "subject_type": "host", "tags": ["network"]},
        )
    )
    assert response.status_code == 200
    body = _body(response)
    assert body["candidates"][0]["capability_id"] == capability.capability_id
    assert body["candidates"][0]["capability_version_id"] == str(version.pk)


@pytest.mark.django_db
def test_capability_create_rolls_back_when_audit_write_fails(monkeypatch):
    admin = None
    monkeypatch.setattr(views, "record_event", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit")))
    response = views.collection(
        _request("POST", "/capabilities/", user=admin,
                 payload={"capability_id": "network.rollback", "name": "Rollback", "domain": "network"}),
    )
    assert response.status_code == 500
    assert not Capability.objects.filter(capability_id="network.rollback").exists()
