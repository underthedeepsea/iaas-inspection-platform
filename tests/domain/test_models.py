import uuid

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone


def create_environment():
    from apps.core.models import Environment

    return Environment.objects.create(
        name="Development",
        slug=f"development-{uuid.uuid4().hex}",
    )


@pytest.mark.django_db
def test_environment_defaults_are_preserved():
    environment = create_environment()

    assert environment.environment_type == "DEV"
    assert environment.timezone == "Asia/Shanghai"
    assert environment.is_active is True
    assert environment.metadata == {}


@pytest.mark.parametrize(
    ("model_label", "field_name"),
    [
        ("inspections.InspectionItem", "version"),
        ("inspections.MockDataset", "version"),
        ("capabilities.CapabilityVersion", "version"),
        ("investigations.ConversationMessage", "prompt_version"),
    ],
)
def test_project_version_fields_require_exact_numeric_semantic_versions(
    model_label,
    field_name,
):
    """Relaxing full-match validation must allow a bare or newline version."""
    field = apps.get_model(model_label)._meta.get_field(field_name)

    assert field.clean("1.0.0", None) == "1.0.0"
    for invalid_version in ("1", "1.0.0\n"):
        with pytest.raises(ValidationError):
            field.clean(invalid_version, None)


@pytest.mark.django_db
def test_inspection_item_records_execution_mode_and_code_status():
    """Removing either state field from an inspection item must fail this test."""
    inspection_item = apps.get_model("inspections", "InspectionItem")

    item = inspection_item.objects.create(
        code=f"llm.performance.{uuid.uuid4().hex}",
        name="LLM performance",
        domain="LLM",
        execution_mode="CODE_FIRST_AI_FALLBACK",
        code_status="PARTIAL_CODE",
    )

    assert item.execution_mode == "CODE_FIRST_AI_FALLBACK"
    assert item.code_status == "PARTIAL_CODE"


@pytest.mark.django_db
def test_risk_fingerprint_is_unique_within_an_environment():
    """Dropping the environment/fingerprint constraint must allow this duplicate."""
    inspection_item = apps.get_model("inspections", "InspectionItem")
    risk_model = apps.get_model("risks", "Risk")
    environment = create_environment()
    item = inspection_item.objects.create(
        code=f"risk.source.{uuid.uuid4().hex}",
        name="Risk source",
        domain="LLM",
        execution_mode="CODE_ONLY",
        code_status="CODE_ACTIVE",
    )
    risk_values = {
        "environment": environment,
        "inspection_item": item,
        "risk_key": "ttft-degraded",
        "fingerprint": "same-fingerprint",
        "title": "TTFT degraded",
        "domain": "LLM",
        "severity": "P2",
        "first_seen_at": timezone.now(),
        "last_seen_at": timezone.now(),
    }
    risk_model.objects.create(**risk_values)

    with pytest.raises(IntegrityError), transaction.atomic():
        risk_model.objects.create(**risk_values)


@pytest.mark.django_db
def test_risk_observation_is_unique_for_a_risk_and_run():
    """Removing the risk/run constraint must allow two observations for one run."""
    inspection_item = apps.get_model("inspections", "InspectionItem")
    inspection_run = apps.get_model("inspections", "InspectionRun")
    inspection_item_run = apps.get_model("inspections", "InspectionItemRun")
    risk_model = apps.get_model("risks", "Risk")
    observation_model = apps.get_model("risks", "RiskObservation")
    environment = create_environment()
    item = inspection_item.objects.create(
        code=f"observation.source.{uuid.uuid4().hex}",
        name="Observation source",
        domain="LLM",
        execution_mode="CODE_ONLY",
        code_status="CODE_ACTIVE",
    )
    run = inspection_run.objects.create(
        environment=environment,
        run_date=timezone.localdate(),
        trigger_type="MANUAL",
    )
    item_run = inspection_item_run.objects.create(
        inspection_run=run,
        inspection_item=item,
    )
    risk = risk_model.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key="observation-risk",
        fingerprint=f"observation-{uuid.uuid4().hex}",
        title="Observation risk",
        domain="LLM",
        severity="P2",
        first_seen_at=timezone.now(),
        last_seen_at=timezone.now(),
    )
    observation_values = {
        "risk": risk,
        "inspection_run": run,
        "inspection_item_run": item_run,
        "observed_at": timezone.now(),
        "severity": "P2",
        "status_after": "NEW",
    }
    observation_model.objects.create(**observation_values)

    with pytest.raises(IntegrityError), transaction.atomic():
        observation_model.objects.create(**observation_values)


@pytest.mark.django_db
def test_capability_version_is_unique_per_capability():
    """Removing the capability/version constraint must allow a duplicate version."""
    capability_model = apps.get_model("capabilities", "Capability")
    version_model = apps.get_model("capabilities", "CapabilityVersion")
    capability = capability_model.objects.create(
        capability_id=f"capability.{uuid.uuid4().hex}",
        name="Metric analyzer",
        domain="LLM",
    )
    version_values = {
        "capability": capability,
        "version": "1.0.0",
        "implementation_type": "RULE",
    }
    version_model.objects.create(**version_values)

    with pytest.raises(IntegrityError), transaction.atomic():
        version_model.objects.create(**version_values)


@pytest.mark.django_db
def test_human_feedback_can_link_a_message_investigation_and_risk():
    """Breaking any feedback relation must prevent this linked feedback record."""
    inspection_item = apps.get_model("inspections", "InspectionItem")
    risk_model = apps.get_model("risks", "Risk")
    investigation_model = apps.get_model("investigations", "Investigation")
    conversation_model = apps.get_model("investigations", "Conversation")
    message_model = apps.get_model("investigations", "ConversationMessage")
    feedback_model = apps.get_model("investigations", "HumanFeedback")
    environment = create_environment()
    item = inspection_item.objects.create(
        code=f"feedback.source.{uuid.uuid4().hex}",
        name="Feedback source",
        domain="LLM",
        execution_mode="AI_INVESTIGATION",
        code_status="NOT_CODED",
    )
    risk = risk_model.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key="feedback-risk",
        fingerprint=f"feedback-{uuid.uuid4().hex}",
        title="Feedback risk",
        domain="LLM",
        severity="P2",
        first_seen_at=timezone.now(),
        last_seen_at=timezone.now(),
    )
    investigation = investigation_model.objects.create(
        risk=risk,
        trigger_type="HUMAN",
        entry_reason="USER_QUESTION",
        model_provider="ollama",
        model_name="qwen",
    )
    user = get_user_model().objects.create_user(
        username=f"reviewer-{uuid.uuid4().hex}",
    )
    conversation = conversation_model.objects.create(
        environment=environment,
        user=user,
        context_type="RISK",
        context_id=risk.id,
        risk=risk,
        investigation=investigation,
        title="Risk review",
    )
    message = message_model.objects.create(
        conversation=conversation,
        role="ASSISTANT",
        content="The likely cause is resource contention.",
    )

    feedback = feedback_model.objects.create(
        environment=environment,
        user=user,
        risk=risk,
        investigation=investigation,
        conversation=conversation,
        message=message,
        feedback_type="CONFIRMED_ROOT_CAUSE",
        comment="Confirmed by the operator.",
    )

    assert feedback.risk_id == risk.id
    assert feedback.investigation_id == investigation.id
    assert feedback.message_id == message.id
