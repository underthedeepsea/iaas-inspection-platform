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
from apps.investigations.models import Conversation, HumanFeedback, Investigation
from apps.learning.models import CodeizationTask, Experience
from apps.risks.models import Risk, Severity


def _user(*groups):
    user = get_user_model().objects.create_user(
        username=f"learning-api-{uuid.uuid4().hex}", password="password"
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _context(*, user=None):
    user = user or _user("operator")
    environment = Environment.objects.create(
        name="Learning API", slug=f"learning-api-{uuid.uuid4().hex}"
    )
    item = InspectionItem.objects.create(
        code=f"learning.api.{uuid.uuid4().hex}",
        name="Learning item",
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
        title="Learning risk",
        domain="NETWORK",
        severity=Severity.P2,
        first_seen_at="2026-08-23T00:00:00Z",
        last_seen_at="2026-08-23T00:00:00Z",
    )
    investigation = Investigation.objects.create(
        risk=risk,
        trigger_type=Investigation.TriggerType.HUMAN,
        entry_reason=Investigation.EntryReason.USER_QUESTION,
        model_provider="ollama",
        model_name="qwen",
        conclusion="PACKET_PATH_PRESSURE",
    )
    conversation = Conversation.objects.create(
        environment=environment,
        user=user,
        context_type=Conversation.ContextType.RISK,
        context_id=risk.pk,
        risk=risk,
        investigation=investigation,
        title="Learning review",
    )
    return {
        "user": user,
        "environment": environment,
        "item": item,
        "risk": risk,
        "investigation": investigation,
        "conversation": conversation,
    }


def _request(method, path, user, payload=None, query=""):
    body = b"" if payload is None else json.dumps(payload).encode()
    request = getattr(RequestFactory(), method.lower())(
        f"{path}{query}", data=body, content_type="application/json"
    )
    request.user = user
    return request


@pytest.mark.django_db
def test_conversation_close_is_atomic_and_audited():
    from apps.audits.models import AuditEvent
    from apps.conversations import views

    context = _context()
    response = views.close(
        _request("POST", "/conversations/close", context["user"]),
        context["conversation"].pk,
    )

    assert response.status_code == 200
    context["conversation"].refresh_from_db()
    assert context["conversation"].status == Conversation.Status.CLOSED
    event = AuditEvent.objects.get(
        object_type="Conversation", object_id=str(context["conversation"].pk)
    )
    assert event.event_type == "conversation.closed"


@pytest.mark.django_db
def test_feedback_create_and_convert_to_experience_use_domain_services():
    from apps.feedback import views as feedback_views

    context = _context()
    payload = {
        "risk_id": str(context["risk"].pk),
        "investigation_id": str(context["investigation"].pk),
        "conversation_id": str(context["conversation"].pk),
        "feedback_type": HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE,
        "rating": 5,
        "comment": "Confirmed by operator",
        "confirmed_conclusion": "PACKET_PATH_PRESSURE",
        "correction": {},
        "create_experience": False,
    }
    response = feedback_views.collection(
        _request("POST", "/feedback", context["user"], payload)
    )
    assert response.status_code == 201
    feedback_id = json.loads(response.content)["feedback_id"]
    assert json.loads(response.content)["experience_created"] is False
    assert AuditEvent.objects.filter(event_type="feedback.created").count() == 1

    response = feedback_views.convert(
        _request("POST", "/feedback/convert", context["user"]), feedback_id
    )
    assert response.status_code == 201
    assert json.loads(response.content)["experience_created"] is True
    assert Experience.objects.count() == 1


@pytest.mark.django_db
def test_experience_confirm_and_task_creation_validate_roles_and_enums():
    from apps.experiences import views as experience_views
    from apps.feedback.services import create_feedback

    context = _context()
    feedback = create_feedback(
        actor=context["user"],
        environment=context["environment"],
        risk=context["risk"],
        investigation=context["investigation"],
        conversation=context["conversation"],
        feedback_type=HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE,
        confirmed_conclusion="PACKET_PATH_PRESSURE",
        comment="Confirmed",
        create_experience=True,
    )
    experience = Experience.objects.get(experience_key=f"feedback:{feedback.pk}")

    response = experience_views.confirm(
        _request("POST", "/experiences/confirm", context["user"], {
            "human_summary": "Reproducible",
            "target_claim": "network.packet_loss.cause_category",
        }),
        experience.pk,
    )
    assert response.status_code == 200

    response = experience_views.create_task(
        _request("POST", "/experiences/tasks", context["user"], {
            "inspection_item_id": str(context["item"].pk),
            "target_capability_id": f"network.packet.pressure.{uuid.uuid4().hex}",
            "task_type": CodeizationTask.TaskType.PLUGIN,
            "implementation_type": CodeizationTask.ImplementationType.RULE,
            "target_claim": "network.packet_loss.cause_category",
        }),
        experience.pk,
    )
    assert response.status_code == 201
    assert json.loads(response.content)["status"] == CodeizationTask.Status.CODE_PENDING

    viewer = _user("viewer")
    response = experience_views.confirm(
        _request("POST", "/experiences/confirm", viewer, {
            "human_summary": "No",
            "target_claim": "network.packet_loss.cause_category",
        }),
        experience.pk,
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_codeization_status_progression_is_platform_admin_only_and_uses_exact_version():
    from apps.experiences import views as experience_views
    from apps.feedback.services import create_feedback

    context = _context()
    feedback = create_feedback(
        actor=context["user"],
        environment=context["environment"],
        risk=context["risk"],
        investigation=context["investigation"],
        conversation=context["conversation"],
        feedback_type=HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE,
        confirmed_conclusion="PACKET_PATH_PRESSURE",
        comment="Confirmed",
        create_experience=True,
    )
    experience = Experience.objects.get(experience_key=f"feedback:{feedback.pk}")
    experience_views.confirm(
        _request("POST", "/experiences/confirm", context["user"], {
            "human_summary": "Reproducible",
            "target_claim": "network.packet_loss.cause_category",
        }),
        experience.pk,
    )
    capability = Capability.objects.create(
        capability_id=f"network.packet.pressure.{uuid.uuid4().hex}",
        name="Packet pressure",
        domain="NETWORK",
        status=Capability.Status.ACTIVE,
        read_only=True,
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        resolves=["network.packet_loss.cause_category"],
        manifest={"security": {"read_only": True}},
    )
    task = experience_views.create_task(
        _request("POST", "/experiences/tasks", context["user"], {
            "inspection_item_id": str(context["item"].pk),
            "target_capability_id": capability.capability_id,
            "task_type": CodeizationTask.TaskType.PLUGIN,
            "implementation_type": CodeizationTask.ImplementationType.RULE,
            "target_claim": "network.packet_loss.cause_category",
        }),
        experience.pk,
    )
    task_id = json.loads(task.content)["task_id"]
    denied = experience_views.task_detail(
        _request("PATCH", "/codeization-tasks", context["user"], {
            "status": CodeizationTask.Status.SHADOW,
            "capability_version_id": str(version.pk),
        }),
        task_id,
    )
    assert denied.status_code == 403

    admin = _user("platform_admin")
    shadow = experience_views.task_detail(
        _request("PATCH", "/codeization-tasks", admin, {
            "status": CodeizationTask.Status.SHADOW,
            "capability_version_id": str(version.pk),
        }),
        task_id,
    )
    assert shadow.status_code == 200
    active = experience_views.task_detail(
        _request("PATCH", "/codeization-tasks", admin, {
            "status": CodeizationTask.Status.CODE_ACTIVE,
            "capability_version_id": str(version.pk),
            "shadow_cases": 3,
            "precision": 0.8,
            "critical_false_positive": 0,
        }),
        task_id,
    )
    assert active.status_code == 200
    assert json.loads(active.content)["status"] == CodeizationTask.Status.CODE_ACTIVE
