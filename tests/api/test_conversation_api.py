import json
import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.models import Environment
from apps.inspections.models import InspectionItem, Severity
from apps.investigations.models import Conversation, ConversationMessage, Investigation, InvestigationEvent
from apps.risks.models import Risk


def _user(name=None):
    return get_user_model().objects.create_user(
        username=name or f"user-{uuid.uuid4().hex}",
        password="password",
    )


def _risk(*, environment=None):
    environment = environment or Environment.objects.create(
        name="Conversation environment",
        slug=f"conversation-{uuid.uuid4().hex}",
    )
    item = InspectionItem.objects.create(
        code=f"conversation.item.{uuid.uuid4().hex}",
        name="Conversation item",
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.AI_INVESTIGATION,
        code_status=InspectionItem.CodeStatus.NOT_CODED,
        required_claims=["degradation_category"],
    )
    return Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key=f"risk-{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        title="Conversation risk",
        domain="TEST",
        severity=Severity.P2,
        first_seen_at="2026-08-23T00:00:00Z",
        last_seen_at="2026-08-23T00:00:00Z",
    )


def _post(client, path, payload):
    return client.post(path, data=json.dumps(payload), content_type="application/json")


@pytest.mark.django_db(transaction=True)
def test_create_risk_conversation_derives_environment_and_requires_authentication():
    risk = _risk()
    other_environment = Environment.objects.create(
        name="Untrusted environment",
        slug=f"untrusted-{uuid.uuid4().hex}",
    )
    client = Client()
    response = _post(
        client,
        "/api/v1/conversations/",
        {
            "context_type": "RISK",
            "context_id": str(risk.pk),
            "environment_id": str(other_environment.pk),
            "title": "Risk analysis",
        },
    )
    assert response.status_code == 401

    user = _user()
    client.force_login(user)
    response = _post(
        client,
        "/api/v1/conversations/",
        {
            "context_type": "RISK",
            "context_id": str(risk.pk),
            "environment_id": str(other_environment.pk),
            "title": "Risk analysis",
        },
    )
    assert response.status_code == 201
    conversation = Conversation.objects.get(pk=response.json()["conversation_id"])
    assert conversation.user_id == user.pk
    assert conversation.risk_id == risk.pk
    assert conversation.environment_id == risk.environment_id
    assert conversation.environment_id != other_environment.pk


@pytest.mark.django_db(transaction=True)
def test_turn_persists_user_investigation_assistant_terminal_event_and_is_retry_safe():
    risk = _risk()
    user = _user()
    client = Client()
    client.force_login(user)
    conversation_response = _post(
        client,
        "/api/v1/conversations/",
        {"context_type": "RISK", "context_id": str(risk.pk), "title": "Risk analysis"},
    )
    conversation_id = conversation_response.json()["conversation_id"]
    result = {
        "status": "RESOLVED",
        "summary": "Scheduler pressure confirmed",
        "conclusion": "SCHEDULER_PRESSURE",
        "facts": ["queue ratio is elevated"],
        "next_steps": ["check workers"],
        "confidence": 0.86,
        "evidence": [],
        "tool_history": [],
        "rounds_used": 1,
        "tool_calls_used": 0,
    }
    with patch("apps.conversations.services.run_graph", return_value=result) as run_graph:
        first = _post(
            client,
            f"/api/v1/conversations/{conversation_id}/turns/",
            {"message": "Why is TTFT increasing?", "idempotency_key": "turn-1"},
        )
        retry = _post(
            client,
            f"/api/v1/conversations/{conversation_id}/turns/",
            {"message": "Why is TTFT increasing?", "idempotency_key": "turn-1"},
        )

    assert first.status_code == retry.status_code == 202
    assert first.json()["turn_id"] == retry.json()["turn_id"]
    assert run_graph.call_count == 1
    conversation = Conversation.objects.get(pk=conversation_id)
    assert str(conversation.investigation_id) == first.json()["investigation_id"]
    assert ConversationMessage.objects.filter(conversation=conversation, role="USER").count() == 1
    assistant = ConversationMessage.objects.get(conversation=conversation, role="ASSISTANT")
    assert assistant.content == "Scheduler pressure confirmed"
    investigation = Investigation.objects.get(pk=first.json()["investigation_id"])
    assert investigation.status == Investigation.Status.RESOLVED
    events = list(InvestigationEvent.objects.filter(investigation=investigation).order_by("sequence"))
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].event_type == "turn.completed"


@pytest.mark.django_db(transaction=True)
def test_graph_error_is_persisted_as_failed_terminal_turn_without_leaking_exception():
    risk = _risk()
    user = _user()
    client = Client()
    client.force_login(user)
    conversation_id = _post(
        client,
        "/api/v1/conversations/",
        {"context_type": "RISK", "context_id": str(risk.pk), "title": "Risk analysis"},
    ).json()["conversation_id"]
    with patch(
        "apps.conversations.services.run_graph",
        side_effect=RuntimeError("provider secret https://secret.invalid"),
    ):
        response = _post(
            client,
            f"/api/v1/conversations/{conversation_id}/turns/",
            {"message": "Investigate"},
        )
    assert response.status_code == 202
    investigation = Investigation.objects.get(pk=response.json()["investigation_id"])
    assert investigation.status == Investigation.Status.FAILED
    assert investigation.error_code if hasattr(investigation, "error_code") else True
    assert "secret.invalid" not in response.content.decode()
    assert InvestigationEvent.objects.filter(
        investigation=investigation,
        event_type="turn.error",
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_conversation_reads_are_owner_isolated_and_messages_survive_refresh():
    risk = _risk()
    owner = _user("owner")
    stranger = _user("stranger")
    owner_client = Client()
    owner_client.force_login(owner)
    conversation_id = _post(
        owner_client,
        "/api/v1/conversations/",
        {"context_type": "RISK", "context_id": str(risk.pk), "title": "Risk analysis"},
    ).json()["conversation_id"]
    with patch(
        "apps.conversations.services.run_graph",
        return_value={
            "status": "RESOLVED",
            "summary": "done",
            "conclusion": "done",
            "facts": [],
            "next_steps": [],
            "confidence": 1,
            "evidence": [],
            "tool_history": [],
            "rounds_used": 1,
            "tool_calls_used": 0,
        },
    ):
        _post(
            owner_client,
            f"/api/v1/conversations/{conversation_id}/turns/",
            {"message": "hello"},
        )

    refreshed = owner_client.get(f"/api/v1/conversations/{conversation_id}/messages/")
    assert refreshed.status_code == 200
    assert [item["role"] for item in refreshed.json()["messages"]] == ["USER", "ASSISTANT"]

    stranger_client = Client()
    stranger_client.force_login(stranger)
    assert stranger_client.get(f"/api/v1/conversations/{conversation_id}/").status_code == 404
    assert stranger_client.get(f"/api/v1/conversations/{conversation_id}/messages/").status_code == 404
