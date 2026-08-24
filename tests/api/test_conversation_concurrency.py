import threading
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.conversations.services import create_turn
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, Severity
from apps.investigations.models import Conversation, Investigation
from apps.risks.models import Risk


def _risk_for_concurrency():
    environment = Environment.objects.create(
        name="Concurrency environment",
        slug=f"concurrency-{uuid.uuid4().hex}",
    )
    item = InspectionItem.objects.create(
        code=f"concurrency.item.{uuid.uuid4().hex}",
        name="Concurrency item",
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
        title="Concurrency risk",
        domain="TEST",
        severity=Severity.P2,
        first_seen_at="2026-08-23T00:00:00Z",
        last_seen_at="2026-08-23T00:00:00Z",
    )


class ConversationClaimConcurrencyTests(TransactionTestCase):
    reset_sequences = False

    def test_same_idempotency_key_has_one_graph_leader_and_fast_follower(self):
        risk = _risk_for_concurrency()
        user = get_user_model().objects.create_user(
            username=f"concurrent-{uuid.uuid4().hex}",
            password="password",
        )
        conversation = Conversation.objects.create(
            environment=risk.environment,
            user=user,
            context_type=Conversation.ContextType.RISK,
            context_id=risk.pk,
            risk=risk,
            title="Concurrency",
        )
        graph_started = threading.Event()
        release_graph = threading.Event()
        calls = []
        responses = []
        errors = []
        result = {
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
        }

        def graph_runner(_graph_input):
            calls.append(threading.current_thread().name)
            graph_started.set()
            if not release_graph.wait(timeout=5):
                raise AssertionError("leader graph was not released")
            return result

        def submit():
            close_old_connections()
            try:
                responses.append(
                    create_turn(
                        user,
                        conversation.pk,
                        {"message": "Investigate", "idempotency_key": "same-key"},
                        graph_runner=graph_runner,
                    )
                )
            except BaseException as exc:  # surface thread failures in the test thread
                errors.append(exc)
            finally:
                close_old_connections()

        leader = threading.Thread(target=submit, name="conversation-leader")
        leader.start()
        assert graph_started.wait(timeout=5)
        investigation = Investigation.objects.get(pk=Conversation.objects.get(pk=conversation.pk).investigation_id)
        assert investigation.status == Investigation.Status.RUNNING
        assert investigation.claim_token
        follower = threading.Thread(target=submit, name="conversation-follower")
        follower.start()
        follower.join(timeout=2)
        assert not follower.is_alive(), "follower must not wait for the graph"
        assert len(calls) == 1
        release_graph.set()
        leader.join(timeout=5)
        assert not leader.is_alive()
        assert not errors
        assert len(responses) == 2
        assert {response["turn_id"] for response in responses} == {str(investigation.pk)}

    def test_old_nonterminal_claim_is_not_auto_stolen_by_a_retry(self):
        risk = _risk_for_concurrency()
        user = get_user_model().objects.create_user(
            username=f"stale-{uuid.uuid4().hex}",
            password="password",
        )
        conversation = Conversation.objects.create(
            environment=risk.environment,
            user=user,
            context_type=Conversation.ContextType.RISK,
            context_id=risk.pk,
            risk=risk,
            title="Stale claim",
        )
        key = "stale-key"
        turn_id = uuid.uuid5(uuid.NAMESPACE_URL, f"ai-inspect:{conversation.pk}:turn:{key}")
        old = timezone.now() - timedelta(hours=2)
        investigation = Investigation.objects.create(
            id=turn_id,
            risk=risk,
            trigger_type=Investigation.TriggerType.HUMAN,
            status=Investigation.Status.RUNNING,
            entry_reason=Investigation.EntryReason.USER_QUESTION,
            model_provider="test",
            model_name="test",
            claim_token=uuid.uuid4(),
            claim_heartbeat_at=old,
            started_at=old,
        )
        conversation.investigation = investigation
        conversation.save(update_fields=["investigation", "updated_at"])
        original_claim = investigation.claim_token
        calls = []

        def graph_runner(_graph_input):
            calls.append(True)
            raise AssertionError("old nonterminal claim must not be stolen")

        response = create_turn(
            user,
            conversation.pk,
            {"message": "Investigate", "idempotency_key": key},
            graph_runner=graph_runner,
        )
        assert calls == []
        assert response["turn_id"] == str(turn_id)
        investigation.refresh_from_db()
        assert investigation.status == Investigation.Status.RUNNING
        assert investigation.claim_token == original_claim
