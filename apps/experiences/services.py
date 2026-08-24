"""Transactional Experience and CodeizationTask services."""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from apps.audits.services import record_event
from apps.core.models import Environment
from apps.inspections.models import InspectionItem
from apps.investigations.models import HumanFeedback
from apps.learning.models import CodeizationTask, Experience, ExperienceEvidence
from apps.risks.models import Evidence


_IDENTIFIER_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}\Z")


class ExperienceError(ValueError):
    """Invalid Experience or codeization request."""


def create_experience_from_feedback(feedback, *, actor=None, evidence=None, evidences=None):
    """Create the one DISCOVERED Experience allowed by a root-cause feedback."""

    feedback = _model(feedback, HumanFeedback, "feedback")
    if type(feedback.create_experience) is not bool:
        raise ExperienceError("create_experience must be a boolean")
    if feedback.feedback_type != HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE:
        raise ExperienceError("only confirmed root-cause feedback can create an experience")
    if not feedback.create_experience:
        raise ExperienceError("feedback did not opt in to experience creation")
    _require_actor(actor)
    if evidence is not None and evidences is not None:
        raise ExperienceError("supply evidence or evidences, not both")
    evidences = _evidence_rows(evidence if evidence is not None else evidences)
    with transaction.atomic():
        feedback = (
            HumanFeedback.objects.select_for_update(of=("self",))
            .select_related(
                "environment",
                "risk__inspection_item",
                "investigation__risk__inspection_item",
            )
            .get(pk=feedback.pk)
        )
        _validate_feedback_context(feedback, evidences)
        key = f"feedback:{feedback.pk}"
        experience, _created = Experience.objects.get_or_create(
            experience_key=key,
            defaults=_experience_defaults(feedback),
        )
        experience = Experience.objects.select_for_update().get(pk=experience.pk)
        if (
            experience.source_risk_id != feedback.risk_id
            or experience.source_investigation_id != feedback.investigation_id
        ):
            raise ExperienceError("feedback identity is already bound to another experience")
        if _created:
            record_event(
                actor=actor,
                environment=feedback.environment,
                event_type="experience.created",
                object_type="Experience",
                object_id=experience.pk,
                payload={
                    "from_status": Experience.Status.DISCOVERED,
                    "to_status": Experience.Status.DISCOVERED,
                    "target_claim": experience.target_claim,
                },
            )
        for evidence_row in evidences:
            ExperienceEvidence.objects.get_or_create(
                experience=experience,
                evidence=evidence_row,
                relation=ExperienceEvidence.Relation.SUPPORT,
            )
    return experience


def confirm_experience(
    first=None,
    second=None,
    *,
    actor=None,
    actor_user=None,
    experience=None,
    human_summary,
    target_claim,
):
    """Confirm a discovered Experience using a legal locked transition."""

    if isinstance(first, Experience):
        experience = experience or first
    elif first is not None:
        actor = actor or first
        experience = experience or second
    actor = actor or actor_user
    _require_actor(actor)
    experience = _model(experience, Experience, "experience")
    human_summary = _nonempty(human_summary, "human_summary")
    target_claim = canonical_claim(target_claim)
    with transaction.atomic():
        locked = Experience.objects.select_for_update().get(pk=experience.pk)
        if locked.status == Experience.Status.CONFIRMED:
            if locked.human_summary == human_summary and locked.target_claim == target_claim:
                return locked
            raise ExperienceError("confirmed experience cannot be changed")
        if locked.status != Experience.Status.DISCOVERED:
            raise ExperienceError("only a discovered experience can be confirmed")
        locked.status = Experience.Status.CONFIRMED
        locked.human_summary = human_summary
        locked.target_claim = target_claim
        locked.confirmed_at = timezone.now()
        locked.save(update_fields=["status", "human_summary", "target_claim", "confirmed_at", "updated_at"])
        record_event(
            actor=actor,
            environment=_experience_environment(locked),
            event_type="experience.confirmed",
            object_type="Experience",
            object_id=locked.pk,
            payload={
                "from_status": Experience.Status.DISCOVERED,
                "to_status": locked.status,
                "target_claim": locked.target_claim,
            },
        )
        return locked


def create_codeization_task(
    first=None,
    second=None,
    *,
    actor=None,
    actor_user=None,
    experience=None,
    inspection_item,
    target_capability_id,
    task_type,
    implementation_type,
    target_claim=None,
    title=None,
    specification=None,
    owner="",
):
    """Persist a CODE_PENDING task after explicit Experience confirmation."""

    if isinstance(first, Experience):
        experience = experience or first
    elif first is not None:
        actor = actor or first
        experience = experience or second
    actor = actor or actor_user
    _require_actor(actor)
    experience = _model(experience, Experience, "experience")
    inspection_item = _model(inspection_item, InspectionItem, "inspection_item")
    target_capability_id = _identifier(target_capability_id, "target_capability_id")
    task_type = _choice_value(task_type, CodeizationTask.TaskType, "task_type")
    implementation_type = _choice_value(
        implementation_type,
        CodeizationTask.ImplementationType,
        "implementation_type",
    )
    with transaction.atomic():
        locked_experience = Experience.objects.select_for_update().get(pk=experience.pk)
        if locked_experience.status != Experience.Status.CONFIRMED:
            raise ExperienceError("experience must be confirmed before codeization")
        claim = canonical_claim(target_claim or locked_experience.target_claim)
        if locked_experience.target_claim != claim:
            raise ExperienceError("task target_claim must match the confirmed experience")
        _validate_item_context(locked_experience, inspection_item)
        specification = {} if specification is None else specification
        if not isinstance(specification, dict):
            raise ExperienceError("specification must be an object")
        existing = CodeizationTask.objects.filter(
            experience=locked_experience,
            inspection_item=inspection_item,
            target_capability_id=target_capability_id,
            target_claim=claim,
        ).first()
        if existing is not None:
            return existing
        locked_experience.status = Experience.Status.CODE_PENDING
        locked_experience.code_status = Experience.CodeStatus.CODE_PENDING
        locked_experience.save(update_fields=["status", "code_status", "updated_at"])
        task = CodeizationTask.objects.create(
            experience=locked_experience,
            inspection_item=inspection_item,
            target_capability_id=target_capability_id,
            task_type=task_type,
            status=CodeizationTask.Status.CODE_PENDING,
            title=_nonempty(title or locked_experience.title, "title"),
            target_claim=claim,
            implementation_type=implementation_type,
            specification=specification,
            owner=owner or getattr(actor, "username", ""),
            historical_support=locked_experience.support_count,
            precision=locked_experience.precision,
        )
        record_event(
            actor=actor,
            environment=_experience_environment(locked_experience),
            event_type="codeization_task.created",
            object_type="CodeizationTask",
            object_id=task.pk,
            payload={
                "from_status": CodeizationTask.Status.CODE_PENDING,
                "to_status": CodeizationTask.Status.CODE_PENDING,
                "target_claim": task.target_claim,
                "target_capability_id": task.target_capability_id,
                "task_type": task.task_type,
                "implementation_type": task.implementation_type,
            },
        )
    return task


def canonical_claim(value):
    if not isinstance(value, str):
        raise ExperienceError("target_claim is required")
    value = value.strip().lower()
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ExperienceError("target_claim must be a canonical identifier")
    return value


def _experience_defaults(feedback):
    risk = feedback.risk
    investigation = feedback.investigation
    if risk is None and investigation is not None:
        risk = investigation.risk
    item = risk.inspection_item if risk is not None else None
    conclusion = feedback.confirmed_conclusion.strip() or feedback.comment.strip() or "Confirmed root cause"
    return {
        "title": (risk.title if risk is not None else conclusion[:255]) or "Confirmed root cause",
        "domain": (risk.domain if risk is not None else (item.domain if item else "UNKNOWN"))[:64],
        "status": Experience.Status.DISCOVERED,
        "source_type": Experience.SourceType.FEEDBACK,
        "source_risk": risk,
        "source_investigation": investigation,
        "hypothesis": investigation.conclusion if investigation is not None else "",
        "conclusion": conclusion,
        "applicable_scope": {
            "environment_id": str(feedback.environment_id),
            **({"inspection_item_id": str(item.pk)} if item is not None else {}),
        },
        "human_summary": feedback.comment.strip(),
        "support_count": 1,
        "code_status": Experience.CodeStatus.NOT_CODED,
    }


def _validate_feedback_context(feedback, evidences):
    if feedback.risk_id and feedback.risk.environment_id != feedback.environment_id:
        raise ExperienceError("feedback risk does not belong to its environment")
    if feedback.investigation_id:
        investigation = feedback.investigation
        if investigation.risk_id and investigation.risk.environment_id != feedback.environment_id:
            raise ExperienceError("feedback investigation does not belong to its environment")
        if feedback.risk_id and investigation.risk_id != feedback.risk_id:
            raise ExperienceError("feedback investigation and risk do not match")
    if feedback.conversation_id:
        conversation = feedback.conversation
        if conversation.environment_id != feedback.environment_id:
            raise ExperienceError("feedback conversation does not belong to its environment")
        if feedback.risk_id and conversation.risk_id and conversation.risk_id != feedback.risk_id:
            raise ExperienceError("feedback conversation and risk do not match")
        if feedback.investigation_id and conversation.investigation_id and conversation.investigation_id != feedback.investigation_id:
            raise ExperienceError("feedback conversation and investigation do not match")
    if feedback.message_id and feedback.message.conversation_id != feedback.conversation_id:
        raise ExperienceError("feedback message does not belong to its conversation")
    for evidence in evidences:
        if evidence.risk_id and feedback.risk_id and evidence.risk_id != feedback.risk_id:
            raise ExperienceError("evidence does not belong to feedback risk")
        if (
            evidence.investigation_id
            and feedback.investigation_id
            and evidence.investigation_id != feedback.investigation_id
        ):
            raise ExperienceError("evidence does not belong to feedback investigation")
        evidence_environment = _evidence_environment(evidence)
        if evidence_environment is not None and evidence_environment.pk != feedback.environment_id:
            raise ExperienceError("evidence does not belong to feedback environment")


def _validate_item_context(experience, inspection_item):
    if experience.source_risk_id and experience.source_risk.inspection_item_id != inspection_item.pk:
        raise ExperienceError("inspection item does not belong to the experience context")
    scope_item = (experience.applicable_scope or {}).get("inspection_item_id")
    if scope_item and str(inspection_item.pk) != str(scope_item):
        raise ExperienceError("inspection item does not belong to the experience context")


def _experience_environment(experience):
    if experience.source_risk_id:
        return experience.source_risk.environment
    environment_id = (experience.applicable_scope or {}).get("environment_id")
    if environment_id:
        return Environment.objects.filter(pk=environment_id).first()
    return None


def _evidence_environment(evidence):
    if evidence.risk_id:
        return evidence.risk.environment
    if evidence.investigation_id:
        if evidence.investigation.risk_id:
            return evidence.investigation.risk.environment
        if evidence.investigation.inspection_item_run_id:
            return evidence.investigation.inspection_item_run.inspection_run.environment
    if evidence.inspection_item_run_id:
        return evidence.inspection_item_run.inspection_run.environment
    return None


def _evidence_rows(value):
    if value is None:
        return []
    if isinstance(value, Evidence):
        return [_model(value, Evidence, "evidence")]
    if isinstance(value, (list, tuple, set)):
        return [_model(row, Evidence, "evidence") for row in value]
    return [_model(value, Evidence, "evidence")]


def _choice_value(value, enum, label):
    value = value.value if hasattr(value, "value") else value
    if not isinstance(value, str) or value.strip().upper() not in enum.values:
        raise ExperienceError(f"invalid {label}")
    return value.strip().upper()


def _identifier(value, label):
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value.strip()):
        raise ExperienceError(f"{label} must be a canonical identifier")
    return value.strip()


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ExperienceError(f"{label} must be non-empty")
    return value.strip()


def _model(value, model, label):
    if isinstance(value, model):
        if value.pk is None or value._state.adding:
            raise ExperienceError(f"{label} must be persisted")
        return value
    if value is None:
        raise ExperienceError(f"{label} is required")
    try:
        return model.objects.get(pk=value)
    except (model.DoesNotExist, TypeError, ValueError):
        raise ExperienceError(f"{label} does not exist") from None


def _require_actor(actor):
    if actor is None or not getattr(actor, "pk", None) or getattr(actor, "is_authenticated", True) is False:
        raise ExperienceError("an explicit authenticated actor is required")


create_experience = create_experience_from_feedback
confirm = confirm_experience
create_task = create_codeization_task


__all__ = [
    "ExperienceError",
    "canonical_claim",
    "confirm",
    "confirm_experience",
    "create_experience",
    "create_codeization_task",
    "create_experience_from_feedback",
    "create_task",
]
