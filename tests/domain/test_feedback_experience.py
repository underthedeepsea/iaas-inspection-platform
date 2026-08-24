import threading
import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone

from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.audits.models import AuditEvent
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
    assert create_experience_from_feedback(feedback, actor=ctx["user"]) == experience
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
    assert task.capability_version_id is None


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

    task.shadow_cases = 3
    task.precision = Decimal("0.8")
    task.critical_false_positive = 0
    task.save(update_fields=["shadow_cases", "precision", "critical_false_positive"])
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


def _confirmed_task(ctx, *, capability=None, capability_id=None, claim=None):
    from apps.feedback.services import create_feedback
    from apps.experiences.services import confirm_experience, create_codeization_task

    create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()
    claim = claim or "network.packet_loss.cause_category"
    confirm_experience(
        ctx["user"],
        experience,
        human_summary="Packet path pressure is reproducible.",
        target_claim=claim,
    )
    experience.refresh_from_db()
    capability = capability or Capability.objects.create(
        capability_id=capability_id or f"network.packet.pressure.{uuid.uuid4().hex}",
        name="Packet pressure resolver",
        domain="NETWORK",
        read_only=True,
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="0.9.0",
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        resolves=[claim],
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
    return experience, capability, version, task, claim


def _confirmed_experience(ctx, *, claim="network.packet_loss.cause_category"):
    from apps.feedback.services import create_feedback
    from apps.experiences.services import confirm_experience

    create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()
    confirm_experience(
        ctx["user"],
        experience,
        human_summary="Packet path pressure is reproducible.",
        target_claim=claim,
    )
    return Experience.objects.get(pk=experience.pk), claim


def _candidate_version(capability, claim, *, version):
    return CapabilityVersion.objects.create(
        capability=capability,
        version=version,
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        resolves=[claim],
        manifest={"security": {"read_only": True}},
    )


@pytest.mark.django_db
def test_shadow_persists_exact_task_version_and_rejects_v2_without_side_effects():
    from apps.experiences.codeization import activate_codeization_task, move_to_shadow

    ctx = context()
    _experience, capability, version_v1, task, claim = _confirmed_task(ctx)
    version_v2 = _candidate_version(capability, claim, version="0.9.1")
    assert task.capability_version_id is None

    move_to_shadow(ctx["user"], task, version_v1)
    task.refresh_from_db()
    assert task.capability_version_id == version_v1.pk
    shadow_audits = AuditEvent.objects.filter(
        object_type="CodeizationTask",
        object_id=task.pk,
        event_type="codeization_task.shadow",
    )
    assert shadow_audits.get().payload["capability_version_id"] == str(version_v1.pk)
    binding_count = InspectionCapabilityBinding.objects.filter(
        inspection_item=ctx["item"],
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    ).count()
    audit_count = AuditEvent.objects.count()

    with pytest.raises(ValueError):
        move_to_shadow(ctx["user"], task, version_v2)
    with pytest.raises(ValueError):
        activate_codeization_task(ctx["user"], task, version_v2)

    task.refresh_from_db()
    version_v1.refresh_from_db()
    version_v2.refresh_from_db()
    assert task.capability_version_id == version_v1.pk
    assert version_v1.status == CapabilityVersion.Status.SHADOW
    assert version_v2.status == CapabilityVersion.Status.CANDIDATE
    assert not InspectionCapabilityBinding.objects.filter(
        inspection_item=ctx["item"],
        capability_version=version_v2,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    ).exists()
    assert InspectionCapabilityBinding.objects.filter(
        inspection_item=ctx["item"],
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    ).count() == binding_count
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db(transaction=True)
def test_concurrent_shadow_versions_bind_one_persisted_version():
    from apps.experiences.codeization import move_to_shadow

    ctx = context()
    _experience, capability, version_v1, task, claim = _confirmed_task(ctx)
    version_v2 = _candidate_version(capability, claim, version="0.9.1")
    successes = []
    errors = []

    def run(version_id):
        close_old_connections()
        try:
            move_to_shadow(ctx["user"], task.pk, version_id)
            successes.append(version_id)
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [
        threading.Thread(target=run, args=(version_v1.pk,)),
        threading.Thread(target=run, args=(version_v2.pk,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(successes) == 1
    assert len(errors) == 1
    task.refresh_from_db()
    version_v1.refresh_from_db()
    version_v2.refresh_from_db()
    winner = successes[0]
    assert task.capability_version_id == winner
    assert [version_v1.status, version_v2.status].count(CapabilityVersion.Status.SHADOW) == 1
    assert InspectionCapabilityBinding.objects.filter(
        inspection_item=ctx["item"],
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
        enabled=True,
    ).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "required_claims",
    [
        [],
        "network.packet_loss.cause_category",
        {},
        [None],
        ["not-the-confirmed-claim"],
    ],
)
def test_create_task_rejects_empty_or_invalid_required_claims(required_claims):
    from apps.experiences.services import create_codeization_task

    ctx = context()
    ctx["item"].required_claims = required_claims
    ctx["item"].save(update_fields=["required_claims"])
    experience, claim = _confirmed_experience(ctx)

    with pytest.raises(ValueError):
        create_codeization_task(
            ctx["user"],
            experience,
            inspection_item=ctx["item"],
            target_capability_id=f"network.packet.invalid-required.{uuid.uuid4().hex}",
            task_type=CodeizationTask.TaskType.RULE,
            implementation_type=CodeizationTask.ImplementationType.RULE,
            target_claim=claim,
        )
    assert CodeizationTask.objects.count() == 0
    assert Experience.objects.get(pk=experience.pk).status == Experience.Status.CONFIRMED


@pytest.mark.django_db
def test_activate_rechecks_required_claim_after_shadow_and_rolls_back():
    from apps.experiences.codeization import activate_codeization_task, move_to_shadow

    ctx = context()
    _experience, capability, version, task, claim = _confirmed_task(ctx)
    move_to_shadow(ctx["user"], task, version)
    ctx["item"].required_claims = ["network.packet_loss.asset_scope"]
    ctx["item"].save(update_fields=["required_claims"])
    task.shadow_cases = 3
    task.precision = Decimal("0.8")
    task.critical_false_positive = 0
    task.save(update_fields=["shadow_cases", "precision", "critical_false_positive"])

    with pytest.raises(ValueError):
        activate_codeization_task(ctx["user"], task, version)

    task.refresh_from_db()
    version.refresh_from_db()
    capability.refresh_from_db()
    assert task.status == CodeizationTask.Status.SHADOW
    assert task.capability_version_id == version.pk
    assert version.status == CapabilityVersion.Status.SHADOW
    assert capability.current_version_id is None
    assert InspectionCapabilityBinding.objects.filter(
        inspection_item=ctx["item"],
        capability_version=version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
        enabled=True,
    ).exists()


@pytest.mark.django_db
def test_activation_uses_canonical_required_claims_for_aggregate_status():
    from apps.experiences.codeization import activate_codeization_task, move_to_shadow

    ctx = context()
    ctx["item"].required_claims = [" Network.Packet_Loss.Cause_Category "]
    ctx["item"].save(update_fields=["required_claims"])
    _experience, _capability, version, task, _claim = _confirmed_task(ctx)
    move_to_shadow(ctx["user"], task, version)
    task.shadow_cases = 3
    task.precision = Decimal("0.8")
    task.critical_false_positive = 0
    task.save(update_fields=["shadow_cases", "precision", "critical_false_positive"])

    activate_codeization_task(ctx["user"], task, version)

    item = InspectionItem.objects.get(pk=ctx["item"].pk)
    assert item.code_status == InspectionItem.CodeStatus.CODE_ACTIVE
    assert item.code_coverage_percent == 100


@pytest.mark.django_db
@pytest.mark.parametrize(
    "initial_status",
    [InspectionItem.CodeStatus.CODE_ACTIVE, InspectionItem.CodeStatus.PARTIAL_CODE],
)
def test_move_to_shadow_preserves_existing_code_and_active_resolver(initial_status):
    from apps.experiences.codeization import move_to_shadow
    from services.plugin_runtime.registry import CapabilityRegistry

    ctx = context()
    claim = "network.packet_loss.cause_category"
    other_claim = "network.packet_loss.asset_scope"
    ctx["item"].required_claims = [claim, other_claim]
    ctx["item"].resolved_claims = [claim]
    ctx["item"].code_status = initial_status
    ctx["item"].save(update_fields=["required_claims", "resolved_claims", "code_status"])
    old_capability = Capability.objects.create(
        capability_id=f"network.packet.pressure.shared.{uuid.uuid4().hex}",
        name="Existing resolver",
        domain="NETWORK",
        read_only=True,
    )
    old_version = CapabilityVersion.objects.create(
        capability=old_capability,
        version="1.0.0",
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        status=CapabilityVersion.Status.ACTIVE,
        resolves=[claim],
    )
    old_capability.current_version = old_version
    old_capability.save(update_fields=["current_version"])
    old_binding = InspectionCapabilityBinding.objects.create(
        inspection_item=ctx["item"],
        capability_version=old_version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
        enabled=True,
    )
    _experience, _capability, version, task, _claim = _confirmed_task(ctx)

    move_to_shadow(ctx["user"], task, version)

    ctx["item"].refresh_from_db()
    old_version.refresh_from_db()
    old_capability.refresh_from_db()
    old_binding.refresh_from_db()
    version.refresh_from_db()
    assert old_binding.enabled is True
    assert old_version.status == CapabilityVersion.Status.ACTIVE
    assert old_capability.current_version_id == old_version.pk
    assert ctx["item"].code_status == initial_status
    assert claim in ctx["item"].resolved_claims
    assert CapabilityRegistry().resolve_shadow(claim) == version


@pytest.mark.django_db
def test_registry_formal_resolver_accepts_partial_claim_but_requires_current_version():
    from services.plugin_runtime.registry import CapabilityRegistry

    ctx = context()
    claim = "network.packet_loss.cause_category"
    ctx["item"].required_claims = [claim, "network.packet_loss.asset_scope"]
    ctx["item"].resolved_claims = [claim]
    ctx["item"].code_status = InspectionItem.CodeStatus.PARTIAL_CODE
    ctx["item"].save(update_fields=["required_claims", "resolved_claims", "code_status"])
    capability = Capability.objects.create(
        capability_id=f"network.packet.current.{uuid.uuid4().hex}",
        name="Current resolver",
        domain="NETWORK",
        read_only=True,
    )
    old = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        resolves=[claim],
    )
    current = CapabilityVersion.objects.create(
        capability=capability,
        version="2.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        resolves=[claim],
    )
    capability.current_version = current
    capability.save(update_fields=["current_version"])
    old_binding = InspectionCapabilityBinding.objects.create(
        inspection_item=ctx["item"],
        capability_version=old,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    )
    registry = CapabilityRegistry()
    assert registry.resolve(claim) is None
    old_binding.enabled = False
    old_binding.save(update_fields=["enabled"])
    InspectionCapabilityBinding.objects.create(
        inspection_item=ctx["item"],
        capability_version=current,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    )
    assert registry.resolve(claim) == current


@pytest.mark.django_db
def test_shared_capability_replacement_rejects_other_active_dependencies_then_switches():
    from apps.experiences.codeization import activate_codeization_task, move_to_shadow

    ctx = context()
    claim = "network.packet_loss.cause_category"
    old_capability = Capability.objects.create(
        capability_id=f"network.packet.shared.{uuid.uuid4().hex}",
        name="Shared resolver",
        domain="NETWORK",
        read_only=True,
    )
    old_version = CapabilityVersion.objects.create(
        capability=old_capability,
        version="1.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        resolves=[claim],
    )
    old_capability.current_version = old_version
    old_capability.save(update_fields=["current_version"])
    old_binding = InspectionCapabilityBinding.objects.create(
        inspection_item=ctx["item"],
        capability_version=old_version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    )
    other_item = InspectionItem.objects.create(
        code=f"feedback.other.{uuid.uuid4().hex}",
        name="Other item",
        domain="NETWORK",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        required_claims=[claim],
        resolved_claims=[claim],
    )
    other_binding = InspectionCapabilityBinding.objects.create(
        inspection_item=other_item,
        capability_version=old_version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    )
    _experience, capability, version, task, _claim = _confirmed_task(
        ctx,
        capability=old_capability,
    )
    move_to_shadow(ctx["user"], task, version)
    task.shadow_cases = 3
    task.precision = Decimal("0.8")
    task.critical_false_positive = 0
    task.save(update_fields=["shadow_cases", "precision", "critical_false_positive"])

    with pytest.raises(ValueError):
        activate_codeization_task(ctx["user"], task, version)
    old_version.refresh_from_db()
    capability.refresh_from_db()
    old_binding.refresh_from_db()
    other_binding.refresh_from_db()
    version.refresh_from_db()
    assert old_version.status == CapabilityVersion.Status.ACTIVE
    assert capability.current_version_id == old_version.pk
    assert old_binding.enabled is True
    assert other_binding.enabled is True
    assert version.status == CapabilityVersion.Status.SHADOW

    other_binding.enabled = False
    other_binding.save(update_fields=["enabled"])
    activate_codeization_task(ctx["user"], task, version)
    old_version.refresh_from_db()
    capability.refresh_from_db()
    old_binding.refresh_from_db()
    assert old_version.status == CapabilityVersion.Status.RETIRED
    assert capability.current_version_id == version.pk
    assert old_binding.enabled is False


@pytest.mark.django_db
def test_shadow_activation_requires_boundary_metrics():
    from apps.experiences.codeization import (
        MAX_SHADOW_FALSE_POSITIVES,
        MIN_SHADOW_CASES,
        MIN_SHADOW_PRECISION,
        activate_codeization_task,
        move_to_shadow,
    )

    ctx = context()
    _experience, _capability, version, task, _claim = _confirmed_task(ctx)
    move_to_shadow(ctx["user"], task, version)
    assert MIN_SHADOW_CASES == 3
    assert MIN_SHADOW_PRECISION == Decimal("0.8")
    assert MAX_SHADOW_FALSE_POSITIVES == 0

    for cases, precision, false_positives in (
        (2, Decimal("0.8"), 0),
        (3, Decimal("0.7999"), 0),
        (3, Decimal("0.8"), 1),
    ):
        task.shadow_cases = cases
        task.precision = precision
        task.critical_false_positive = false_positives
        task.save(update_fields=["shadow_cases", "precision", "critical_false_positive"])
        with pytest.raises(ValueError):
            activate_codeization_task(ctx["user"], task, version)
        task.refresh_from_db()
        version.refresh_from_db()
        assert task.status == CodeizationTask.Status.SHADOW
        assert version.status == CapabilityVersion.Status.SHADOW

    task.shadow_cases = 3
    task.precision = Decimal("0.8")
    task.critical_false_positive = 0
    task.save(update_fields=["shadow_cases", "precision", "critical_false_positive"])
    activate_codeization_task(ctx["user"], task, version)
    assert CodeizationTask.objects.get(pk=task.pk).status == CodeizationTask.Status.CODE_ACTIVE


@pytest.mark.django_db
def test_shadow_retry_is_idempotent_after_version_already_entered_shadow():
    from apps.experiences.codeization import move_to_shadow

    ctx = context()
    _experience, _capability, version, task, _claim = _confirmed_task(ctx)
    first = move_to_shadow(ctx["user"], task, version)
    second = move_to_shadow(ctx["user"], task, version)
    assert first.pk == second.pk == task.pk
    assert CodeizationTask.objects.get(pk=task.pk).status == CodeizationTask.Status.SHADOW


@pytest.mark.django_db
def test_standalone_experience_operations_require_explicit_actor_and_strict_bool_flag():
    from apps.experiences.services import create_experience_from_feedback
    from apps.feedback.services import create_feedback

    ctx = context()
    with pytest.raises(ValueError):
        create_feedback(**feedback_args(ctx, create_experience="true"))
    feedback = create_feedback(**feedback_args(ctx))
    experience = Experience.objects.get()
    with pytest.raises(ValueError):
        create_experience_from_feedback(feedback)
    assert experience.status == Experience.Status.DISCOVERED
    feedback.create_experience = "true"
    with pytest.raises(ValueError):
        create_experience_from_feedback(feedback, actor=ctx["user"])


@pytest.mark.django_db
def test_codeization_task_enforces_scope_without_source_risk():
    from apps.experiences.services import create_codeization_task

    ctx = context()
    other_item = InspectionItem.objects.create(
        code=f"feedback.other.scope.{uuid.uuid4().hex}",
        name="Other scope item",
        domain="NETWORK",
        required_claims=["network.packet_loss.cause_category"],
    )
    experience = Experience.objects.create(
        experience_key=f"scope-only:{uuid.uuid4().hex}",
        title="Scope-only experience",
        domain="NETWORK",
        status=Experience.Status.CONFIRMED,
        source_type=Experience.SourceType.FEEDBACK,
        conclusion="Scope-only conclusion",
        applicable_scope={"inspection_item_id": str(ctx["item"].pk)},
        target_claim="network.packet_loss.cause_category",
    )

    with pytest.raises(ValueError):
        create_codeization_task(
            ctx["user"],
            experience,
            inspection_item=other_item,
            target_capability_id="network.packet.scope-only",
            task_type=CodeizationTask.TaskType.RULE,
            implementation_type=CodeizationTask.ImplementationType.RULE,
        )


@pytest.mark.django_db
def test_standalone_confirmation_audit_uses_scoped_environment():
    from apps.experiences.services import confirm_experience

    ctx = context()
    experience = Experience.objects.create(
        experience_key=f"audit-scope:{uuid.uuid4().hex}",
        title="Scoped audit experience",
        domain="NETWORK",
        status=Experience.Status.DISCOVERED,
        source_type=Experience.SourceType.FEEDBACK,
        conclusion="Scoped conclusion",
        applicable_scope={"environment_id": str(ctx["environment"].pk)},
    )

    confirm_experience(
        ctx["user"],
        experience,
        human_summary="Confirmed in scoped environment.",
        target_claim="network.packet_loss.cause_category",
    )

    event = AuditEvent.objects.get(object_type="Experience", object_id=experience.pk)
    assert event.environment_id == ctx["environment"].pk


@pytest.mark.django_db
def test_feedback_and_codeization_transitions_write_non_sensitive_audit_events():
    from apps.experiences.codeization import activate_codeization_task, move_to_shadow

    ctx = context()
    from apps.investigations.models import HumanFeedback

    _experience, _capability, version, task, _claim = _confirmed_task(ctx)
    move_to_shadow(ctx["user"], task, version)
    task.shadow_cases = 3
    task.precision = Decimal("0.8")
    task.save(update_fields=["shadow_cases", "precision"])
    activate_codeization_task(ctx["user"], task, version)

    events = AuditEvent.objects.filter(user=ctx["user"]).order_by("created_at", "pk")
    assert {event.object_type for event in events} >= {
        "HumanFeedback",
        "Experience",
        "CodeizationTask",
        "CapabilityVersion",
    }
    for event in events:
        assert event.environment_id == ctx["environment"].pk
        assert "comment" not in event.payload
        assert "confirmed_conclusion" not in event.payload
        assert "specification" not in event.payload
    event_map = {(event.object_type, event.event_type): event for event in events}
    assert (
        event_map[("Experience", "experience.created")].payload["to_status"]
        == Experience.Status.DISCOVERED
    )
    assert (
        event_map[("CapabilityVersion", "capability_version.shadow")].payload["from_status"]
        == CapabilityVersion.Status.CANDIDATE
    )
    feedback = HumanFeedback.objects.get()
    assert feedback.user_id == ctx["user"].pk


@pytest.mark.django_db(transaction=True)
def test_concurrent_shadow_retry_converges_on_one_task_state():
    from apps.experiences.codeization import move_to_shadow

    ctx = context()
    _experience, _capability, version, task, _claim = _confirmed_task(ctx)
    results = []
    errors = []

    def run():
        close_old_connections()
        try:
            results.append(move_to_shadow(ctx["user"], task.pk, version.pk).pk)
        except BaseException as exc:
            errors.append(exc)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert results == [task.pk, task.pk]
    assert CodeizationTask.objects.get(pk=task.pk).status == CodeizationTask.Status.SHADOW
