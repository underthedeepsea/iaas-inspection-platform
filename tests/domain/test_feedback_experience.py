import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.core.models import Environment
from apps.inspections.models import InspectionItem
from apps.investigations.models import (
    Conversation,
    ConversationMessage,
    HumanFeedback,
    Investigation,
)
from apps.learning.models import CodeizationTask, Experience
from apps.risks.models import Evidence, Risk


def context():
    suffix = uuid.uuid4().hex
    environment = Environment.objects.create(name="Development", slug=f"dev-{suffix}")
    item = InspectionItem.objects.create(
        code=f"feedback.item.{suffix}",
        name="Feedback item",
        domain="NETWORK",
        execution_mode=InspectionItem.ExecutionMode.AI_INVESTIGATION,
        code_status=InspectionItem.CodeStatus.NOT_CODED,
        required_claims=["network.packet_loss.cause_category"],
    )
    risk = Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key=f"risk-{suffix}",
        fingerprint=f"fingerprint-{suffix}",
        title="Packet loss",
        domain="NETWORK",
        severity="P2",
        first_seen_at=timezone.now(),
        last_seen_at=timezone.now(),
    )
    investigation = Investigation.objects.create(
        risk=risk,
        trigger_type=Investigation.TriggerType.HUMAN,
        entry_reason=Investigation.EntryReason.USER_QUESTION,
        model_provider="ollama",
        model_name="qwen",
        conclusion="Likely packet path pressure",
    )
    user = get_user_model().objects.create_user(username=f"operator-{suffix}")
    conversation = Conversation.objects.create(
        environment=environment,
        user=user,
        context_type=Conversation.ContextType.RISK,
        context_id=risk.pk,
        risk=risk,
        investigation=investigation,
        title="Risk review",
    )
    message = ConversationMessage.objects.create(
        conversation=conversation,
        role=ConversationMessage.Role.ASSISTANT,
        content="The likely cause is packet path pressure.",
        structured_content={"current_conclusion": "PACKET_PATH_PRESSURE"},
    )
    evidence = Evidence.objects.create(
        risk=risk,
        investigation=investigation,
        evidence_type=Evidence.EvidenceType.TOOL_RESULT,
        evidence_key=f"evidence-{suffix}",
        summary="RX errors increased",
        source="test",
    )
    return {
        "environment": environment,
        "item": item,
        "risk": risk,
        "investigation": investigation,
        "user": user,
        "conversation": conversation,
        "message": message,
        "evidence": evidence,
    }


def feedback_args(ctx, **overrides):
    values = {
        "actor": ctx["user"],
        "environment": ctx["environment"],
        "risk": ctx["risk"],
        "investigation": ctx["investigation"],
        "conversation": ctx["conversation"],
        "message": ctx["message"],
        "feedback_type": HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE,
        "confirmed_conclusion": "PACKET_PATH_PRESSURE",
        "comment": "Confirmed by the operator.",
        "create_experience": True,
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
def test_helpful_feedback_only_persists_feedback():
    from apps.feedback.services import create_feedback

    ctx = context()
    feedback = create_feedback(
        **feedback_args(
            ctx,
            feedback_type=HumanFeedback.FeedbackType.HELPFUL,
        )
    )

    assert feedback.feedback_type == HumanFeedback.FeedbackType.HELPFUL
    assert HumanFeedback.objects.count() == 1
    assert Experience.objects.count() == 0


@pytest.mark.django_db
def test_confirmed_root_cause_with_opt_in_creates_idempotent_discovered_experience():
    from apps.feedback.services import create_feedback
    from apps.experiences.services import create_experience_from_feedback

    ctx = context()
    feedback = create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()

    assert experience.status == Experience.Status.DISCOVERED
    assert experience.code_status == Experience.CodeStatus.NOT_CODED
    assert experience.source_risk_id == ctx["risk"].pk
    assert experience.source_investigation_id == ctx["investigation"].pk
    assert experience.conclusion == "PACKET_PATH_PRESSURE"
    assert create_experience_from_feedback(feedback) == experience
    assert Experience.objects.count() == 1


@pytest.mark.django_db
def test_experience_confirmation_is_separate_from_codeization_task_creation():
    from apps.feedback.services import create_feedback
    from apps.experiences.services import confirm_experience, create_codeization_task

    ctx = context()
    feedback = create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()

    confirm_experience(
        ctx["user"],
        experience,
        human_summary="Packet path pressure is reproducible.",
        target_claim="network.packet_loss.cause_category",
    )
    task = create_codeization_task(
        ctx["user"],
        experience,
        inspection_item=ctx["item"],
        target_capability_id=f"network.packet.pressure.{uuid.uuid4().hex}",
        task_type=CodeizationTask.TaskType.PLUGIN,
        implementation_type=CodeizationTask.ImplementationType.RULE,
        specification={"rules": ["rx_errors > 0"]},
    )

    assert feedback.pk
    experience.refresh_from_db()
    assert experience.status == Experience.Status.CODE_PENDING
    assert experience.code_status == Experience.CodeStatus.CODE_PENDING
    assert experience.target_claim == "network.packet_loss.cause_category"
    assert task.status == CodeizationTask.Status.CODE_PENDING
    assert task.target_claim == experience.target_claim


@pytest.mark.django_db
def test_codeization_requires_pending_shadow_active_and_registry_prefers_active_resolver():
    from apps.experiences.codeization import activate_codeization_task, move_to_shadow
    from apps.feedback.services import create_feedback
    from apps.experiences.services import confirm_experience, create_codeization_task
    from services.plugin_runtime.registry import CapabilityRegistry

    ctx = context()
    create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()
    confirm_experience(
        ctx["user"],
        experience,
        human_summary="Packet path pressure is reproducible.",
        target_claim="network.packet_loss.cause_category",
    )
    experience.refresh_from_db()
    capability = Capability.objects.create(
        capability_id=f"network.packet.pressure.{uuid.uuid4().hex}",
        name="Packet pressure resolver",
        domain="NETWORK",
        read_only=True,
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="0.9.0",
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        resolves=[experience.target_claim],
        manifest={"security": {"read_only": True}},
    )
    task = create_codeization_task(
        ctx["user"],
        experience,
        inspection_item=ctx["item"],
        target_capability_id=capability.capability_id,
        task_type=CodeizationTask.TaskType.PLUGIN,
        implementation_type=CodeizationTask.ImplementationType.RULE,
    )

    with pytest.raises(ValueError):
        activate_codeization_task(ctx["user"], task, version)

    move_to_shadow(ctx["user"], task, version)
    task.refresh_from_db()
    version.refresh_from_db()
    assert task.status == CodeizationTask.Status.SHADOW
    assert version.status == CapabilityVersion.Status.SHADOW
    assert Experience.objects.get(pk=experience.pk).status == Experience.Status.SHADOW
    assert InspectionCapabilityBinding.objects.filter(
        inspection_item=ctx["item"],
        capability_version=version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=experience.target_claim,
        enabled=True,
    ).exists()

    activate_codeization_task(ctx["user"], task, version)
    task.refresh_from_db()
    version.refresh_from_db()
    capability.refresh_from_db()
    item = InspectionItem.objects.get(pk=ctx["item"].pk)
    assert task.status == CodeizationTask.Status.CODE_ACTIVE
    assert version.status == CapabilityVersion.Status.ACTIVE
    assert capability.current_version_id == version.pk
    assert item.code_status == InspectionItem.CodeStatus.CODE_ACTIVE
    assert experience.target_claim in item.resolved_claims
    assert CapabilityRegistry().resolve(experience.target_claim) == version


@pytest.mark.django_db
def test_feedback_rejects_cross_environment_context():
    from apps.feedback.services import create_feedback

    ctx = context()
    other_environment = Environment.objects.create(
        name="Other", slug=f"other-{uuid.uuid4().hex}"
    )
    with pytest.raises(ValueError):
        create_feedback(**feedback_args(ctx, environment=other_environment))
    assert HumanFeedback.objects.count() == 0


@pytest.mark.django_db
def test_codeization_rejects_backtracking_and_direct_capability_activation():
    from apps.experiences.codeization import transition_codeization_task
    from apps.feedback.services import create_feedback
    from apps.experiences.services import confirm_experience, create_codeization_task

    ctx = context()
    create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()
    confirm_experience(
        ctx["user"],
        experience,
        human_summary="Packet path pressure is reproducible.",
        target_claim="network.packet_loss.cause_category",
    )
    task = create_codeization_task(
        ctx["user"],
        experience,
        inspection_item=ctx["item"],
        target_capability_id=f"network.packet.pressure.{uuid.uuid4().hex}",
        task_type=CodeizationTask.TaskType.RULE,
        implementation_type=CodeizationTask.ImplementationType.RULE,
    )

    with pytest.raises(ValueError):
        transition_codeization_task(ctx["user"], task, CodeizationTask.Status.CODE_ACTIVE)
