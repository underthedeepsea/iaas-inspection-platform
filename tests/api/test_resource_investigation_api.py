from datetime import date, datetime, timezone
import json
import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from apps.core.models import Environment
from apps.inspections.models import InspectionRun, ResourceInspectionSummary, ResourceType
from apps.investigations.models import Conversation, Investigation, InvestigationEvent
from apps.risks.models import Evidence
from apps.investigations.services import runtime
from apps.investigations.services.runtime import run_resource_investigation


def make_user():
    user = get_user_model().objects.create_user(
        username=f"resource-investigation-{uuid.uuid4().hex}", password="password"
    )
    group, _ = Group.objects.get_or_create(name="viewer")
    user.groups.add(group)
    return user


def make_environment(name="Investigation"):
    return Environment.objects.create(name=name, slug=f"resource-investigation-{uuid.uuid4().hex}")


def make_resource_type(code="RESOURCE_INVESTIGATION"):
    return ResourceType.objects.create(
        code=code,
        name="Resource investigation",
        asset_selector={"asset_types": ["LLM_INSTANCE"]},
    )


def make_run(environment, resource_type):
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=date(2026, 8, 25),
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=InspectionRun.Status.SUCCEEDED,
        started_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        finished_at=datetime(2026, 8, 25, 0, 1, tzinfo=timezone.utc),
        config_snapshot={"resolved_scope": {"resource_types": [resource_type.code]}},
    )
    ResourceInspectionSummary.objects.create(
        inspection_run=run,
        resource_type=resource_type,
        assets_total=1,
        assets_covered=1,
        health_score=90,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )
    return run


@pytest.mark.django_db
def test_resource_investigation_rejects_cross_environment_and_out_of_scope_runs():
    environment = make_environment()
    other_environment = make_environment("Other")
    resource_type = make_resource_type()
    run = make_run(other_environment, resource_type)
    client = Client()
    client.force_login(make_user())

    cross_environment = client.post(
        f"/api/v1/resource-types/{resource_type.code}/investigations",
        data=json.dumps(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(environment.id),
                "inspection_run_id": str(run.id),
            }
        ),
        content_type="application/json",
    )
    assert cross_environment.status_code in {400, 403}

    out_of_scope_run = make_run(environment, make_resource_type("OTHER_RESOURCE"))
    out_of_scope = client.post(
        f"/api/v1/resource-types/{resource_type.code}/investigations",
        data=json.dumps(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(environment.id),
                "inspection_run_id": str(out_of_scope_run.id),
            }
        ),
        content_type="application/json",
    )
    assert out_of_scope.status_code == 400
    assert out_of_scope.json()["error"]["code"] == "RESOURCE_SCOPE_MISMATCH"


@pytest.mark.django_db(transaction=True)
def test_resource_investigation_creates_owner_scoped_investigation_and_replayable_sse(monkeypatch):
    environment = make_environment()
    resource_type = make_resource_type()
    run = make_run(environment, resource_type)
    user = make_user()
    queued = []
    monkeypatch.setattr(
        "apps.investigations.api.enqueue_resource_investigation",
        lambda investigation_id, context: queued.append((investigation_id, context)),
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/resource-types/{resource_type.code}/investigations",
        data=json.dumps(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(environment.id),
                "inspection_run_id": str(run.id),
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    investigation_id = response.json()["investigation_id"]
    investigation = Investigation.objects.get(pk=investigation_id)
    assert investigation.status == Investigation.Status.CREATED
    runtime.run_resource_investigation(
        investigation,
        queued[0][1],
        failed_tools=["change_history"],
    )
    investigation.refresh_from_db()
    assert investigation.status == Investigation.Status.RESOLVED
    events = client.get(
        f"/api/v1/investigations/{investigation_id}/events",
        HTTP_LAST_EVENT_ID="1",
    )
    assert events.status_code == 200
    assert events["Content-Type"] == "text/event-stream"
    raw = b"".join(events.streaming_content).decode()
    payloads = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
    assert payloads
    assert all(payload["sequence"] > 1 for payload in payloads)
    assert payloads[-1]["event_type"] == "analysis.completed"


@pytest.mark.django_db(transaction=True)
def test_resource_investigation_returns_created_and_enqueues_background_runtime(monkeypatch):
    environment = make_environment()
    resource_type = make_resource_type("ASYNC_RESOURCE")
    run = make_run(environment, resource_type)
    user = make_user()
    enqueued = []
    monkeypatch.setattr(
        "apps.investigations.api.enqueue_resource_investigation",
        lambda investigation_id, context: enqueued.append((str(investigation_id), context)),
        raising=False,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/api/v1/resource-types/{resource_type.code}/investigations",
        data=json.dumps(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(environment.id),
                "inspection_run_id": str(run.id),
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    investigation = Investigation.objects.get(pk=body["investigation_id"])
    conversation = Conversation.objects.get(investigation=investigation)
    assert body["status"] == Investigation.Status.CREATED
    assert body["conversation_id"] == str(conversation.id)
    assert investigation.status == Investigation.Status.CREATED
    assert enqueued and enqueued[0][0] == str(investigation.id)


@pytest.mark.django_db
def test_resource_runtime_calls_injected_investigation_graph_and_persists_evidence(monkeypatch):
    environment = make_environment("Graph runtime")
    resource_type = make_resource_type("GRAPH_RESOURCE")
    run = make_run(environment, resource_type)
    investigation = Investigation.objects.create(
        trigger_type=Investigation.TriggerType.HUMAN,
        status=Investigation.Status.CREATED,
        entry_reason=Investigation.EntryReason.TREND_GAP,
        model_provider="test",
        model_name="fake",
    )
    evidence = {
        "evidence_key": "summary:1",
        "summary": "summary evidence",
        "payload": {"health_score": 90},
        "source": "summary",
        "capability_id": "summary",
        "confidence": 0.9,
        "materiality": 0.8,
    }
    calls = []

    def fake_run_graph(values, **kwargs):
        calls.append(values)
        return {
            "status": "RESOLVED",
            "summary": "graph answer",
            "conclusion": "graph answer",
            "facts": ["summary evidence"],
            "next_steps": [],
            "confidence": 0.9,
            "evidence": [evidence],
            "tool_history": [],
            "rounds_used": 1,
            "tool_calls_used": 0,
        }

    monkeypatch.setattr(runtime, "run_graph", fake_run_graph, raising=False)
    result = runtime.run_resource_investigation(
        investigation,
        {
            "context_type": "RESOURCE_RUN",
            "inspection_run_id": str(run.id),
            "current_summary": {"health_score": 90},
            "evidence": [{
                "evidence_key": "summary:1",
                "evidence_type": "METRIC",
                "source": "prometheus",
                "window_end": "2026-08-25T00:01:00+00:00",
                "observed_at": "2026-08-25T00:01:00+00:00",
                "value": {"health_score": 90},
                "summary": "summary evidence",
                "confidence": 0.9,
                "materiality": 0.8,
                "related_finding_ids": ["finding-1"],
                "related_risk_ids": ["risk-1"],
            }],
        },
    )

    assert calls and calls[0]["context"]["inspection_run_id"] == str(run.id)
    assert result.status == Investigation.Status.RESOLVED
    persisted = Evidence.objects.get(investigation=result, evidence_key="summary:1")
    assert persisted.evidence_type == Evidence.EvidenceType.METRIC
    assert persisted.window_end.isoformat() == "2026-08-25T00:01:00+00:00"
    evidence_event = InvestigationEvent.objects.get(investigation=result, event_type="evidence.created")
    assert evidence_event.payload["value"] == {"health_score": 90}
    assert evidence_event.payload["related_finding_ids"] == ["finding-1"]
    assert evidence_event.payload["related_risk_ids"] == ["risk-1"]


@pytest.mark.django_db(transaction=True)
def test_resource_conversation_question_reuses_resource_context(monkeypatch):
    environment = make_environment("Question context")
    resource_type = make_resource_type("QUESTION_RESOURCE")
    run = make_run(environment, resource_type)
    user = make_user()
    queued = []
    monkeypatch.setattr(
        "apps.investigations.api.enqueue_resource_investigation",
        lambda investigation_id, context: queued.append((investigation_id, context)),
    )
    client = Client()
    client.force_login(user)
    created = client.post(
        f"/api/v1/resource-types/{resource_type.code}/investigations",
        data=json.dumps(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(environment.id),
                "inspection_run_id": str(run.id),
            }
        ),
        content_type="application/json",
    ).json()

    graph_calls = []

    def fake_graph(values, **kwargs):
        graph_calls.append(values)
        return {
            "status": "RESOLVED",
            "summary": "follow-up answer",
            "conclusion": "follow-up answer",
            "facts": [],
            "next_steps": [],
            "confidence": 0.8,
            "evidence": [],
            "tool_history": [],
            "rounds_used": 1,
            "tool_calls_used": 0,
        }

    response = None
    with patch("apps.conversations.services.run_graph", side_effect=fake_graph):
        response = client.post(
            f"/api/v1/conversations/{created['conversation_id']}/turns",
            data=json.dumps({"message": "为什么健康度下降？"}),
            content_type="application/json",
        )

    assert response.status_code == 202
    assert graph_calls
    assert graph_calls[0]["context"]["resource_type_code"] == resource_type.code
    assert graph_calls[0]["context"]["inspection_run_id"] == str(run.id)


@pytest.mark.django_db
def test_partial_tool_failure_still_resolves_investigation():
    environment = make_environment()
    resource_type = make_resource_type("PARTIAL_RESOURCE")
    run = make_run(environment, resource_type)
    investigation = Investigation.objects.create(
        trigger_type=Investigation.TriggerType.HUMAN,
        status=Investigation.Status.RUNNING,
        entry_reason=Investigation.EntryReason.TREND_GAP,
        model_provider="resource",
        model_name="bounded",
    )

    run_resource_investigation(
        investigation,
        {"context_type": "RESOURCE_RUN", "inspection_run_id": str(run.id)},
        failed_tools=["change_history"],
    )

    investigation.refresh_from_db()
    assert investigation.status == Investigation.Status.RESOLVED
    assert InvestigationEvent.objects.filter(
        investigation=investigation,
        event_type="tool.failed",
    ).exists()
