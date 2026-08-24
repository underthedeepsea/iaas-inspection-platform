import json
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from apps.audits.models import AuditEvent
from apps.core.models import Environment
from apps.inspections.models import (
    DailySnapshot,
    Finding,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
    Severity,
)


def _user(*roles):
    user = get_user_model().objects.create_user(
        username=f"operations-{uuid.uuid4().hex}", password="password"
    )
    for role in roles:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


def _request(method, path, user, payload=None):
    factory = RequestFactory()
    body = b"" if payload is None else json.dumps(payload).encode()
    request = getattr(factory, method.lower())(
        path,
        data=body,
        content_type="application/json",
    )
    request.user = user
    return request


def _environment():
    return Environment.objects.create(
        name="Operations API",
        slug=f"operations-{uuid.uuid4().hex}",
    )


def _item(code=None):
    return InspectionItem.objects.create(
        code=code or f"operations.item.{uuid.uuid4().hex}",
        name="Operations item",
        domain="LLM",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
        code_coverage_percent="78.000",
        required_claims=["performance.status"],
        resolved_claims=["performance.status"],
        llm_responsibilities=["未知性能退化原因分类"],
    )


def _run(environment, run_date, *, status=InspectionRun.Status.SUCCEEDED):
    return InspectionRun.objects.create(
        environment=environment,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=status,
        started_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        finished_at=datetime(2026, 8, 23, 1, tzinfo=timezone.utc),
    )


@pytest.mark.django_db
def test_inspection_item_list_requires_session_and_applies_filters_and_page_size():
    from apps.operations_api import views

    _item()
    disabled = _item()
    disabled.enabled = False
    disabled.save(update_fields=["enabled"])

    anonymous = _request("GET", "/api/v1/inspection-items", SimpleNamespace(is_authenticated=False))
    assert views.inspection_items(anonymous).status_code == 401

    viewer = _user("viewer")
    request = _request(
        "GET",
        "/api/v1/inspection-items?domain=LLM&enabled=true&page_size=1",
        viewer,
    )
    response = views.inspection_items(request)

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["page_size"] == 1
    assert body["total"] == 1
    assert set(body["items"][0]) >= {
        "id",
        "code",
        "execution_mode",
        "code_status",
        "code_coverage_percent",
        "resolved_claims",
        "llm_responsibilities",
    }


@pytest.mark.django_db
def test_dashboard_today_returns_latest_snapshot_yesterday_diff_and_bounded_seven_day_trend():
    from apps.operations_api import views

    environment = _environment()
    snapshots = []
    for offset in range(8):
        day = date(2026, 8, 23) - timedelta(days=offset)
        run = _run(environment, day)
        snapshots.append(
            DailySnapshot.objects.create(
                environment=environment,
                snapshot_date=day,
                inspection_run=run,
                risk_total=10 + offset,
                p1_count=offset,
                p2_count=2,
                new_count=3,
                worsened_count=4,
                pending_action_count=5,
                pending_reverify_count=6,
                code_coverage_rate="90.500",
                ai_displacement_rate="42.100",
                data_completeness_rate="99.400",
            )
        )

    viewer = _user("viewer")
    response = views.dashboard_today(
        _request("GET", f"/api/v1/dashboard/today?environment={environment.slug}", viewer)
    )

    assert response.status_code == 200
    body = json.loads(response.content)
    assert body["snapshot"]["date"] == "2026-08-23"
    assert body["snapshot"]["risk_total"] == 10
    assert body["yesterday_diff"]["risk_total"] == -1
    assert len(body["trend_7d"]) == 7
    assert set(body["trend_7d"][0]) >= {"date", "risk_total"}


@pytest.mark.django_db
def test_inspection_run_and_finding_lists_apply_context_filters():
    from apps.operations_api import views

    environment = _environment()
    item = _item()
    run = _run(environment, date(2026, 8, 23))
    item_run = InspectionItemRun.objects.create(
        inspection_run=run,
        inspection_item=item,
        status=InspectionItemRun.Status.SUCCEEDED,
        ai_admission_status=InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE,
        summary={"data_valid": True},
    )
    Finding.objects.create(
        inspection_item_run=item_run,
        finding_code="OPS_FINDING",
        title="Bounded finding",
        category="performance",
        severity=Severity.P2,
        source_type=Finding.SourceType.RULE,
        observed_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        value={"token": "must not be returned as raw payload"},
    )

    viewer = _user("viewer")
    runs = views.inspection_runs(
        _request("GET", f"/api/v1/inspection-runs?environment_id={environment.pk}&status=SUCCEEDED", viewer)
    )
    findings = views.findings(
        _request("GET", f"/api/v1/findings?run_id={run.pk}&finding_code=OPS_FINDING", viewer)
    )

    assert json.loads(runs.content)["total"] == 1
    finding = json.loads(findings.content)["items"][0]
    assert finding["finding_code"] == "OPS_FINDING"
    assert "value" not in finding


@pytest.mark.django_db
def test_inspection_run_detail_bounds_nested_item_runs():
    from apps.operations_api import views

    environment = _environment()
    run = _run(environment, date(2026, 8, 23))
    for index in range(129):
        item = _item(code=f"operations.bound.{index}.{uuid.uuid4().hex}")
        InspectionItemRun.objects.create(inspection_run=run, inspection_item=item)

    with CaptureQueriesContext(connection) as queries:
        response = views.inspection_run_detail(
            _request("GET", f"/api/v1/inspection-runs/{run.pk}", _user("viewer")),
            run.pk,
        )

    assert response.status_code == 200
    assert len(json.loads(response.content)["item_runs"]) == 128
    assert any(
        'FROM "inspection_item_runs"' in query["sql"] and "LIMIT 128" in query["sql"]
        for query in queries.captured_queries
    )


@pytest.mark.django_db(transaction=True)
def test_item_ask_delegates_to_risk_conversation_contract():
    from apps.operations_api import views

    environment = _environment()
    item = _item()
    operator = _user("operator")
    fake_conversation = SimpleNamespace(pk=uuid.uuid4())
    with patch("apps.operations_api.views.create_conversation", return_value=fake_conversation) as create, patch(
        "apps.operations_api.views.create_turn",
        return_value={"turn_id": str(uuid.uuid4()), "investigation_id": str(uuid.uuid4())},
    ):
        response = views.inspection_item_ask(
            _request(
                "POST",
                f"/api/v1/inspection-items/{item.pk}/ask",
                operator,
                {"message": "仍有哪些部分依赖 LLM？"},
            ),
            str(item.pk),
        )

    assert response.status_code == 201
    assert json.loads(response.content)["conversation_id"] == str(fake_conversation.pk)
    assert create.call_args.args[0] == operator
    payload = create.call_args.args[1]
    assert payload["context_type"] == "INSPECTION_ITEM"
    assert payload["context_id"] == str(item.pk)
    assert payload["title"] == item.name


@pytest.mark.django_db(transaction=True)
def test_manual_airflow_trigger_uses_injected_transport_and_stable_failure():
    from apps.operations_api import views

    operator = _user("operator")
    environment = _environment()
    payload = {
        "environment_id": str(environment.pk),
        "run_date": "2026-08-23",
        "scenario": "llm_scheduler_pressure",
        "seed": 20260823,
    }
    with patch("apps.operations_api.views.airflow_transport", side_effect=RuntimeError("offline")):
        response = views.trigger_inspection_run(_request("POST", "/api/v1/inspection-runs/trigger", operator, payload))

    assert response.status_code == 502
    assert json.loads(response.content)["error"]["code"] == "AIRFLOW_TRIGGER_FAILED"
