import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory

from apps.core.models import Environment
from apps.inspections.models import InspectionRun
from apps.inspections.services.events import append_run_event


def make_user():
    user = get_user_model().objects.create_user(
        username=f"run-events-{uuid.uuid4().hex}", password="password"
    )
    group, _ = Group.objects.get_or_create(name="viewer")
    user.groups.add(group)
    return user


def make_run():
    environment = Environment.objects.create(name="Events", slug=f"events-{uuid.uuid4().hex}")
    return InspectionRun.objects.create(
        environment=environment,
        run_date="2026-08-25",
        trigger_type=InspectionRun.TriggerType.MANUAL,
    )


def make_request(run, user, last_event_id=None):
    request = RequestFactory().get(f"/api/v1/inspection-runs/{run.id}/events")
    request.user = user
    if last_event_id is not None:
        request.META["HTTP_LAST_EVENT_ID"] = str(last_event_id)
    return request


@pytest.mark.django_db
def test_run_event_stream_replays_only_events_after_last_event_id():
    from apps.inspections.api import inspection_run_events

    run = make_run()
    append_run_event(run, "scope.resolved", "RUNNING", {"resource_types": ["LLM_RUNTIME"]})
    append_run_event(run, "inspection.item.progress", "RUNNING", {"completed_assets": 23})
    append_run_event(run, "run.completed", "SUCCEEDED", {})

    response = inspection_run_events(make_request(run, make_user(), last_event_id=1), run.id)
    raw = b"".join(response.streaming_content).decode()
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]

    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"
    assert [event["sequence"] for event in events] == [2, 3]
    assert events[0]["event_type"] == "inspection.item.progress"


@pytest.mark.django_db
def test_run_event_stream_rejects_noncanonical_last_event_id():
    from apps.inspections.api import inspection_run_events

    run = make_run()
    request = make_request(run, make_user())
    request.META["HTTP_LAST_EVENT_ID"] = "01"

    response = inspection_run_events(request, run.id)

    assert response.status_code == 400
    assert json.loads(response.content)["error"]["code"] == "VALIDATION_ERROR"
