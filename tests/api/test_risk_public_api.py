import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory

from apps.audits.models import AuditEvent
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, Severity
from apps.risks.models import Evidence, Risk, RiskStatusHistory


def _user(*roles):
    user = get_user_model().objects.create_user(
        username=f"risk-api-{uuid.uuid4().hex}", password="password"
    )
    for role in roles:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


def _request(method, path, user, payload=None):
    body = b"" if payload is None else json.dumps(payload).encode()
    request = getattr(RequestFactory(), method.lower())(
        path, data=body, content_type="application/json"
    )
    request.user = user
    return request


def _risk(status=Risk.Status.PENDING_ACTION):
    environment = Environment.objects.create(
        name="Risk API",
        slug=f"risk-api-{uuid.uuid4().hex}",
    )
    item = InspectionItem.objects.create(
        code=f"risk.api.item.{uuid.uuid4().hex}",
        name="Risk API item",
        domain="LLM",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
    )
    return Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key=f"risk-{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex,
        title="Risk API risk",
        domain="LLM",
        severity=Severity.P2,
        status=status,
        first_seen_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )


@pytest.mark.django_db
def test_risk_list_filters_change_and_serializes_bounded_payloads():
    from apps.operations_api import views

    risk = _risk()
    Evidence.objects.create(
        risk=risk,
        evidence_type=Evidence.EvidenceType.TOOL_RESULT,
        evidence_key="secret-ish",
        summary="safe summary",
        payload={"password": "must not be returned"},
        source="test",
    )
    viewer = _user("viewer")
    response = views.risks(
        _request("GET", "/api/v1/risks?status=PENDING_ACTION&change=NEW&ai_involved=false", viewer)
    )

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["total"] == 1
    item = body["items"][0]
    assert item["risk_id"] == str(risk.pk)
    assert "evidence" not in item
    assert "password" not in json.dumps(item)


@pytest.mark.django_db(transaction=True)
def test_mark_handled_is_operator_only_audited_and_never_recovers_directly():
    from apps.operations_api import views

    risk = _risk()
    viewer = _user("viewer")
    denied = views.mark_handled(
        _request("POST", f"/api/v1/risks/{risk.pk}/mark-handled", viewer, {"comment": "x"}),
        str(risk.pk),
    )
    assert denied.status_code == 403

    operator = _user("operator")
    response = views.mark_handled(
        _request(
            "POST",
            f"/api/v1/risks/{risk.pk}/mark-handled",
            operator,
            {"comment": "已调整 worker", "external_ticket": "CHG-1"},
        ),
        str(risk.pk),
    )
    risk.refresh_from_db()

    assert response.status_code == 200
    assert risk.status == Risk.Status.PENDING_REVERIFY
    assert risk.status != Risk.Status.RECOVERED
    assert RiskStatusHistory.objects.filter(
        risk=risk, to_status=Risk.Status.PENDING_REVERIFY, actor_user=operator
    ).exists()
    assert AuditEvent.objects.filter(
        object_type="Risk", object_id=str(risk.pk), user=operator
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_ignore_requires_reason_and_rejects_terminal_or_illegal_transition():
    from apps.operations_api import views

    operator = _user("operator")
    risk = _risk()
    missing_reason = views.ignore(
        _request("POST", f"/api/v1/risks/{risk.pk}/ignore", operator, {}),
        str(risk.pk),
    )
    assert missing_reason.status_code == 400

    response = views.ignore(
        _request("POST", f"/api/v1/risks/{risk.pk}/ignore", operator, {"reason": "accepted"}),
        str(risk.pk),
    )
    risk.refresh_from_db()
    assert response.status_code == 200
    assert risk.status == Risk.Status.IGNORED
    assert AuditEvent.objects.filter(object_type="Risk", object_id=str(risk.pk)).exists()

    recovered = _risk(status=Risk.Status.RECOVERED)
    illegal = views.ignore(
        _request("POST", f"/api/v1/risks/{recovered.pk}/ignore", operator, {"reason": "late"}),
        str(recovered.pk),
    )
    assert illegal.status_code == 409
    assert json.loads(illegal.content)["error"]["code"] == "INVALID_RISK_TRANSITION"


@pytest.mark.django_db
def test_timeline_and_evidence_are_bounded_and_do_not_expose_raw_payload():
    from apps.operations_api import views

    risk = _risk()
    RiskStatusHistory.objects.create(
        risk=risk,
        from_status=Risk.Status.NEW,
        to_status=Risk.Status.PENDING_ACTION,
        source=RiskStatusHistory.Source.SYSTEM,
        reason="transition",
    )
    Evidence.objects.create(
        risk=risk,
        evidence_type=Evidence.EvidenceType.LOG,
        evidence_key="bounded-log",
        summary="safe",
        payload={"password": "do-not-return"},
        source="test",
    )
    viewer = _user("viewer")
    timeline = views.risk_timeline(
        _request("GET", f"/api/v1/risks/{risk.pk}/timeline", viewer), str(risk.pk)
    )
    evidence = views.risk_evidence(
        _request("GET", f"/api/v1/risks/{risk.pk}/evidence?limit=1", viewer), str(risk.pk)
    )

    assert json.loads(timeline.content)["risk_id"] == str(risk.pk)
    assert json.loads(timeline.content)["events"][0]["type"] == "STATUS_CHANGE"
    assert len(json.loads(evidence.content)["items"]) == 1
    assert "payload" not in json.loads(evidence.content)["items"][0]


@pytest.mark.django_db
def test_item_and_risk_detail_serializers_include_bounded_codeization_fields():
    from apps.operations_api import views

    risk = _risk()
    viewer = _user("viewer")
    item_response = views.inspection_item_detail(
        _request("GET", f"/api/v1/inspection-items/{risk.inspection_item_id}", viewer),
        str(risk.inspection_item_id),
    )
    assert item_response.status_code == 200
    item_body = json.loads(item_response.content)
    assert item_body["description"] == ""

    risk_response = views.risk_detail(
        _request("GET", f"/api/v1/risks/{risk.pk}", viewer), str(risk.pk)
    )
    assert risk_response.status_code == 200
    risk_body = json.loads(risk_response.content)
    assert risk_body["codeization"]["code_status"] == risk.inspection_item.code_status


@pytest.mark.django_db(transaction=True)
def test_mark_handled_rolls_back_lifecycle_when_audit_write_fails(monkeypatch):
    from apps.operations_api import views

    risk = _risk()
    operator = _user("operator")

    def fail_audit(**_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(views, "record_event", fail_audit)
    response = views.mark_handled(
        _request(
            "POST",
            f"/api/v1/risks/{risk.pk}/mark-handled",
            operator,
            {"comment": "remediated"},
        ),
        str(risk.pk),
    )

    risk.refresh_from_db()
    assert response.status_code == 500
    assert risk.status == Risk.Status.PENDING_ACTION
    assert not RiskStatusHistory.objects.filter(risk=risk).exists()
    assert not AuditEvent.objects.filter(object_id=str(risk.pk)).exists()
