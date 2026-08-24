import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.models import Environment
from apps.inspections.models import InspectionItem, Severity
from apps.investigations.models import Conversation, Investigation, InvestigationEvent
from apps.risks.models import Risk


def _conversation():
    user = get_user_model().objects.create_user(
        username=f"sse-{uuid.uuid4().hex}", password="password"
    )
    environment = Environment.objects.create(
        name="SSE environment", slug=f"sse-{uuid.uuid4().hex}"
    )
    item = InspectionItem.objects.create(
        code=f"sse.item.{uuid.uuid4().hex}",
        name="SSE item",
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.AI_INVESTIGATION,
        code_status=InspectionItem.CodeStatus.NOT_CODED,
        required_claims=[],
    )
    risk = Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key=f"risk-{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        title="SSE risk",
        domain="TEST",
        severity=Severity.P2,
        first_seen_at="2026-08-23T00:00:00Z",
        last_seen_at="2026-08-23T00:00:00Z",
    )
    conversation = Conversation.objects.create(
        environment=environment,
        user=user,
        context_type=Conversation.ContextType.RISK,
        context_id=risk.pk,
        risk=risk,
        title="SSE",
    )
    investigation = Investigation.objects.create(
        risk=risk,
        trigger_type=Investigation.TriggerType.HUMAN,
        entry_reason=Investigation.EntryReason.USER_QUESTION,
        model_provider="test",
        model_name="test",
    )
    conversation.investigation = investigation
    conversation.save(update_fields=["investigation", "updated_at"])
    for sequence, event_type in enumerate(("turn.started", "assistant.final", "turn.completed"), 1):
        InvestigationEvent.objects.create(
            investigation=investigation,
            sequence=sequence,
            event_type=event_type,
            payload={"conversation_id": str(conversation.pk), "sequence": sequence},
        )
    return user, conversation, investigation


@pytest.mark.django_db(transaction=True)
def test_sse_replays_only_events_after_strict_last_event_id_in_sequence_order():
    user, conversation, investigation = _conversation()
    client = Client()
    client.force_login(user)
    response = client.get(
        f"/api/v1/conversations/{conversation.pk}/turns/{investigation.pk}/events/",
        HTTP_LAST_EVENT_ID="1",
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    body = b"".join(response.streaming_content).decode()
    assert "id: 1" not in body
    assert body.index("id: 2") < body.index("id: 3")
    assert "event: assistant.final" in body
    assert '"conversation_id"' in body


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("last_event_id", ["-1", "+1", " 1", "1 ", "1.0", "abc", "01"])
def test_sse_rejects_noncanonical_last_event_id(last_event_id):
    user, conversation, investigation = _conversation()
    client = Client()
    client.force_login(user)
    response = client.get(
        f"/api/v1/conversations/{conversation.pk}/turns/{investigation.pk}/events/",
        HTTP_LAST_EVENT_ID=last_event_id,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_last_event_id"


@pytest.mark.django_db(transaction=True)
def test_sse_does_not_expose_other_owner_events():
    user, conversation, investigation = _conversation()
    other = get_user_model().objects.create_user(
        username=f"other-{uuid.uuid4().hex}", password="password"
    )
    client = Client()
    client.force_login(other)
    response = client.get(
        f"/api/v1/conversations/{conversation.pk}/turns/{investigation.pk}/events/"
    )
    assert response.status_code == 404
