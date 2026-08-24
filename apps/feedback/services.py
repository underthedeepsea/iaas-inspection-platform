"""Transactional domain service for operator feedback."""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from apps.audits.services import record_event
from apps.core.models import Environment
from apps.investigations.models import (
    Conversation,
    ConversationMessage,
    HumanFeedback,
    Investigation,
)
from apps.risks.models import Evidence, Risk


class FeedbackError(ValueError):
    """Invalid feedback or feedback context."""


def create_feedback(
    actor=None,
    *,
    actor_user=None,
    environment=None,
    risk=None,
    investigation=None,
    conversation=None,
    message=None,
    evidence=None,
    evidences=None,
    feedback_type=None,
    rating=None,
    comment="",
    confirmed_conclusion="",
    correction=None,
    create_experience=False,
):
    """Persist feedback and optionally create its idempotent Experience.

    ``actor`` is deliberately explicit even though Task 14 will add the HTTP
    authentication boundary.  All supplied context rows are checked before a
    write, so a feedback row cannot join two environments or two risks.
    """

    actor = actor or actor_user
    _require_actor(actor)
    feedback_type = _choice_value(feedback_type, HumanFeedback.FeedbackType, "feedback_type")
    if rating is not None and (not isinstance(rating, int) or not 1 <= rating <= 5):
        raise FeedbackError("rating must be an integer from 1 to 5")
    if not isinstance(comment, str) or not isinstance(confirmed_conclusion, str):
        raise FeedbackError("comment and confirmed_conclusion must be strings")
    if type(create_experience) is not bool:
        raise FeedbackError("create_experience must be a boolean")
    if correction is None:
        correction = {}
    if not isinstance(correction, dict):
        raise FeedbackError("correction must be an object")

    environment = _model(environment, Environment, "environment")
    risk = _model(risk, Risk, "risk")
    investigation = _model(investigation, Investigation, "investigation")
    conversation = _model(conversation, Conversation, "conversation")
    message = _model(message, ConversationMessage, "message")
    if evidence is not None and evidences is not None:
        raise FeedbackError("supply evidence or evidences, not both")
    evidences = _evidence_rows(evidence if evidence is not None else evidences)
    if message is not None:
        message_conversation = _related(message, "conversation", Conversation)
        if conversation is None:
            conversation = message_conversation
        elif conversation.pk != message_conversation.pk:
            raise FeedbackError("message does not belong to conversation")
    if conversation is not None:
        if conversation.investigation_id and investigation is None:
            investigation = _related(conversation, "investigation", Investigation)
        if conversation.risk_id and risk is None:
            risk = _related(conversation, "risk", Risk)
    if investigation is not None and investigation.risk_id and risk is None:
        risk = _related(investigation, "risk", Risk)

    environment = _validate_context(
        environment,
        risk=risk,
        investigation=investigation,
        conversation=conversation,
        message=message,
        evidences=evidences,
    )
    if investigation is not None and risk is not None and investigation.risk_id != risk.pk:
        raise FeedbackError("investigation and risk do not belong to the same context")
    if conversation is not None:
        if conversation.risk_id and risk is not None and conversation.risk_id != risk.pk:
            raise FeedbackError("conversation and risk do not belong to the same context")
        if (
            conversation.investigation_id
            and investigation is not None
            and conversation.investigation_id != investigation.pk
        ):
            raise FeedbackError("conversation and investigation do not belong to the same context")
    for evidence_row in evidences:
        if evidence_row.risk_id and risk is not None and evidence_row.risk_id != risk.pk:
            raise FeedbackError("evidence and risk do not belong to the same context")
        if (
            evidence_row.investigation_id
            and investigation is not None
            and evidence_row.investigation_id != investigation.pk
        ):
            raise FeedbackError("evidence and investigation do not belong to the same context")
    _validate_investigation_environment(investigation, environment)

    with transaction.atomic():
        feedback = HumanFeedback.objects.create(
            environment=environment,
            user=actor,
            risk=risk,
            investigation=investigation,
            conversation=conversation,
            message=message,
            feedback_type=feedback_type,
            rating=rating,
            comment=comment.strip(),
            confirmed_conclusion=confirmed_conclusion.strip(),
            correction=correction,
            create_experience=create_experience,
        )
        record_event(
            actor=actor,
            environment=environment,
            event_type="feedback.created",
            object_type="HumanFeedback",
            object_id=feedback.pk,
            payload={
                "feedback_type": feedback.feedback_type,
                "create_experience": feedback.create_experience,
            },
        )
        if (
            feedback_type == HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE
            and create_experience
        ):
            from apps.experiences.services import create_experience_from_feedback

            create_experience_from_feedback(
                feedback,
                actor=actor,
                evidence=evidences,
            )
    return feedback


def _validate_context(
    environment,
    *,
    risk,
    investigation,
    conversation,
    message,
    evidences,
):
    candidates = []
    if environment is not None:
        candidates.append(("environment", environment.pk))
    if risk is not None:
        candidates.append(("risk", risk.environment_id))
    if conversation is not None:
        candidates.append(("conversation", conversation.environment_id))
    if investigation is not None:
        if investigation.risk_id:
            candidates.append(("investigation", investigation.risk.environment_id))
        elif investigation.inspection_item_run_id:
            item_run = investigation.inspection_item_run
            candidates.append(("investigation", item_run.inspection_run.environment_id))
    if message is not None:
        candidates.append(("message", message.conversation.environment_id))
    for evidence in evidences:
        evidence_environment = _evidence_environment(evidence)
        if evidence_environment is not None:
            candidates.append(("evidence", evidence_environment.pk))
    if not candidates:
        raise FeedbackError("feedback requires an environment or linked context")
    expected = candidates[0][1]
    if any(value != expected for _, value in candidates[1:]):
        raise FeedbackError("feedback context rows must share one environment")
    if environment is None:
        environment = Environment.objects.get(pk=expected)
    elif environment.pk != expected:
        raise FeedbackError("feedback context rows must share one environment")
    return environment


def _validate_investigation_environment(investigation, environment):
    if investigation is None:
        return
    if investigation.risk_id and investigation.risk.environment_id != environment.pk:
        raise FeedbackError("investigation and environment do not match")
    if investigation.inspection_item_run_id:
        if investigation.inspection_item_run.inspection_run.environment_id != environment.pk:
            raise FeedbackError("investigation and environment do not match")


def _evidence_environment(evidence):
    if evidence.risk_id:
        return evidence.risk.environment
    if evidence.investigation_id:
        investigation = evidence.investigation
        if investigation.risk_id:
            return investigation.risk.environment
        if investigation.inspection_item_run_id:
            return investigation.inspection_item_run.inspection_run.environment
    if evidence.inspection_item_run_id:
        return evidence.inspection_item_run.inspection_run.environment
    return None


def _evidence_rows(value):
    if value is None:
        return []
    if isinstance(value, Evidence):
        return [_model(value, Evidence, "evidence")]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        return [_model(row, Evidence, "evidence") for row in value]
    return [_model(value, Evidence, "evidence")]


def _model(value, model, label):
    if value is None:
        return None
    if isinstance(value, model):
        if value.pk is None or value._state.adding:
            raise FeedbackError(f"{label} must be persisted")
        return value
    try:
        return model.objects.get(pk=value)
    except (model.DoesNotExist, TypeError, ValueError):
        raise FeedbackError(f"{label} does not exist") from None


def _related(instance, relation, model):
    try:
        value = getattr(instance, relation)
    except model.DoesNotExist:
        raise FeedbackError(f"{relation} does not exist") from None
    return _model(value, model, relation)


def _choice_value(value, enum, label):
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str):
        raise FeedbackError(f"{label} is required")
    value = value.strip().upper()
    if value not in enum.values:
        raise FeedbackError(f"invalid {label}")
    return value


def _require_actor(actor):
    if actor is None or not getattr(actor, "pk", None) or getattr(actor, "is_authenticated", True) is False:
        raise FeedbackError("an explicit authenticated actor is required")


submit_feedback = create_feedback
record_feedback = create_feedback
submit_human_feedback = create_feedback
record_human_feedback = create_feedback


__all__ = [
    "FeedbackError",
    "create_feedback",
    "record_feedback",
    "record_human_feedback",
    "submit_feedback",
    "submit_human_feedback",
]
