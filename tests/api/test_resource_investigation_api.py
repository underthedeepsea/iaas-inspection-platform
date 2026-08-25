from datetime import date, datetime, timezone
import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from apps.core.models import Environment
from apps.inspections.models import InspectionRun, ResourceInspectionSummary, ResourceType
from apps.investigations.models import Investigation, InvestigationEvent
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


@pytest.mark.django_db
def test_resource_investigation_creates_owner_scoped_investigation_and_replayable_sse():
    environment = make_environment()
    resource_type = make_resource_type()
    run = make_run(environment, resource_type)
    user = make_user()
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
