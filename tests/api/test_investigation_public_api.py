import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory

from apps.audits.models import AuditEvent
from apps.capabilities.models import Capability, CapabilityVersion
from apps.core.models import Environment
from apps.inspections.models import InspectionItem
from apps.investigations.models import (
    Conversation,
    Investigation,
    InvestigationEvent,
    ToolCall,
)
from apps.risks.models import Risk, Severity


def _user(*groups):
    user = get_user_model().objects.create_user(
        username=f"investigation-api-{uuid.uuid4().hex}", password="password"
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _context(*, owner=None):
    owner = owner or _user("viewer")
    environment = Environment.objects.create(
        name="Investigation API", slug=f"investigation-api-{uuid.uuid4().hex}"
    )
    item = InspectionItem.objects.create(
        code=f"investigation.api.{uuid.uuid4().hex}",
        name="Investigation item",
        domain="NETWORK",
        execution_mode=InspectionItem.ExecutionMode.AI_INVESTIGATION,
        code_status=InspectionItem.CodeStatus.NOT_CODED,
        required_claims=["network.packet_loss.cause_category"],
    )
    risk = Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key=f"risk-{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        title="Investigation risk",
        domain="NETWORK",
        severity=Severity.P2,
        first_seen_at="2026-08-23T00:00:00Z",
        last_seen_at="2026-08-23T00:00:00Z",
    )
    investigation = Investigation.objects.create(
        risk=risk,
        trigger_type=Investigation.TriggerType.HUMAN,
        entry_reason=Investigation.EntryReason.USER_QUESTION,
        model_provider="secret-provider",
        model_name="secret-model",
        conclusion="Packet path pressure",
    )
    conversation = Conversation.objects.create(
        environment=environment,
        user=owner,
        context_type=Conversation.ContextType.RISK,
        context_id=risk.pk,
        risk=risk,
        investigation=investigation,
        title="Investigation review",
    )
    InvestigationEvent.objects.create(
        investigation=investigation,
        sequence=1,
        event_type="assistant.final",
        payload={"summary": "bounded", "api_key": "do-not-return"},
    )
    return {
        "owner": owner,
        "environment": environment,
        "risk": risk,
        "item": item,
        "investigation": investigation,
        "conversation": conversation,
    }


def _request(method, path, user, payload=None):
    body = b"" if payload is None else json.dumps(payload).encode()
    request = getattr(RequestFactory(), method.lower())(
        path, data=body, content_type="application/json"
    )
    request.user = user
    return request


@pytest.mark.django_db
def test_investigation_detail_is_owner_scoped_and_hides_provider_fields():
    from apps.investigations import public_views

    context = _context()
    response = public_views.detail(
        _request("GET", "/investigations", context["owner"]),
        context["investigation"].pk,
    )

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["investigation_id"] == str(context["investigation"].pk)
    assert body["status"] == Investigation.Status.CREATED
    assert "model_provider" not in body
    assert "model_name" not in body

    stranger = _user("viewer")
    response = public_views.detail(
        _request("GET", "/investigations", stranger), context["investigation"].pk
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_investigation_events_and_tool_calls_are_bounded_public_projections():
    from apps.investigations import public_views

    context = _context()
    capability = Capability.objects.create(
        capability_id=f"network.readonly.{uuid.uuid4().hex}",
        name="Readonly capability",
        domain="NETWORK",
        read_only=True,
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        resolves=["network.packet_loss.cause_category"],
    )
    ToolCall.objects.create(
        investigation=context["investigation"],
        conversation=context["conversation"],
        capability_version=version,
        call_id="call-1",
        tool_name="network.readonly",
        input_args={"secret": "do-not-return"},
        status=ToolCall.Status.SUCCEEDED,
        result_summary="packet counters",
        result_payload={"secret": "do-not-return"},
        error_message="provider details",
    )

    events = public_views.events(
        _request("GET", "/investigations/events", context["owner"]),
        context["investigation"].pk,
    )
    assert events.status_code == 200
    assert "do-not-return" not in events.content.decode()

    calls = public_views.tool_calls(
        _request("GET", "/investigations/tool-calls", context["owner"]),
        context["investigation"].pk,
    )
    assert calls.status_code == 200
    item = json.loads(calls.content)["items"][0]
    assert item["tool_name"] == "network.readonly"
    assert "input_args" not in item
    assert "result_payload" not in item
    assert "error_message" not in item


@pytest.mark.django_db
def test_cancel_requires_operator_and_records_one_semantic_audit_event():
    from apps.investigations import public_views

    context = _context()
    viewer_response = public_views.cancel(
        _request("POST", "/investigations/cancel", context["owner"]),
        context["investigation"].pk,
    )
    assert viewer_response.status_code == 403

    operator = _user("operator")
    context["conversation"].user = operator
    context["conversation"].save(update_fields=["user"])
    response = public_views.cancel(
        _request("POST", "/investigations/cancel", operator),
        context["investigation"].pk,
    )
    assert response.status_code == 200
    context["investigation"].refresh_from_db()
    assert context["investigation"].status == Investigation.Status.CANCELLED
    audit = AuditEvent.objects.get(
        object_type="Investigation", object_id=str(context["investigation"].pk)
    )
    assert audit.event_type == "investigation.cancelled"
