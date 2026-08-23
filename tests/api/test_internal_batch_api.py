from datetime import date
import json
import uuid

import pytest
from django.test import Client

from apps.core.models import Environment
from apps.inspections.models import (
    DailySnapshot,
    Finding,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
    MockDataset,
)
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory


TOKEN = "test-airflow-token"
DAY = date(2026, 8, 23)
BASE = "/api/internal/v1/batch"


def _environment():
    return Environment.objects.create(
        name="Internal batch test",
        slug=f"internal-batch-{uuid.uuid4().hex}",
    )


def _item():
    return InspectionItem.objects.create(
        code=f"internal.batch.item.{uuid.uuid4().hex}",
        name="Internal batch item",
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        required_claims=[],
    )


def _post(client, path, payload=None):
    return client.post(
        f"{BASE}{path}",
        data=json.dumps(payload or {}),
        content_type="application/json",
        HTTP_X_AIRFLOW_TOKEN=TOKEN,
    )


@pytest.fixture(autouse=True)
def airflow_token(monkeypatch):
    monkeypatch.setenv("AIRFLOW_INTERNAL_TOKEN", TOKEN)


@pytest.mark.django_db
def test_missing_token_rejected_before_json_parsing_and_without_side_effects():
    environment = _environment()
    client = Client()

    response = client.post(
        f"{BASE}/datasets/",
        data=b"{not-json",
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_airflow_token"
    assert MockDataset.objects.count() == 0
    assert Environment.objects.filter(pk=environment.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_every_batch_stage_is_retry_safe_and_returns_same_resources():
    environment = _environment()
    _item()
    client = Client()
    dataset_payload = {
        "environment_id": str(environment.pk),
        "dataset_date": DAY.isoformat(),
        "seed": 20260823,
        "scenario": "control_plane_anti_affinity",
    }

    dataset_first = _post(client, "/datasets/", dataset_payload)
    dataset_retry = _post(client, "/datasets/", dataset_payload)
    assert dataset_first.status_code == dataset_retry.status_code == 200
    assert dataset_first.json()["dataset_id"] == dataset_retry.json()["dataset_id"]
    assert MockDataset.objects.count() == 1

    run_payload = {
        "dataset_id": dataset_first.json()["dataset_id"],
        "environment_id": str(environment.pk),
        "run_date": DAY.isoformat(),
        "dag_run_id": "scheduled__2026-08-23T00:00:00+00:00",
    }
    run_first = _post(client, "/inspection-runs/", run_payload)
    run_retry = _post(client, "/inspection-runs/", run_payload)
    assert run_first.status_code == run_retry.status_code == 200
    assert run_first.json()["inspection_run_id"] == run_retry.json()["inspection_run_id"]
    assert InspectionRun.objects.count() == 1
    run_id = run_first.json()["inspection_run_id"]

    execute_path = f"/inspection-runs/{run_id}/execute/"
    execute_first = _post(client, execute_path)
    execute_retry = _post(client, execute_path)
    assert execute_first.status_code == execute_retry.status_code == 200
    assert InspectionItemRun.objects.count() == 1
    assert Finding.objects.count() == 1

    correlate_path = f"/inspection-runs/{run_id}/correlate-risks/"
    correlate_first = _post(client, correlate_path)
    correlate_retry = _post(client, correlate_path)
    assert correlate_first.status_code == correlate_retry.status_code == 200
    assert Risk.objects.count() == 1
    assert RiskObservation.objects.count() == 1
    assert RiskStatusHistory.objects.count() == 1

    reverify_path = f"/inspection-runs/{run_id}/reverify/"
    reverify_first = _post(client, reverify_path)
    reverify_retry = _post(client, reverify_path)
    assert reverify_first.status_code == reverify_retry.status_code == 200
    assert RiskObservation.objects.count() == 1
    assert RiskStatusHistory.objects.count() == 1

    snapshot_path = f"/inspection-runs/{run_id}/snapshot/"
    snapshot_first = _post(client, snapshot_path)
    snapshot_retry = _post(client, snapshot_path)
    assert snapshot_first.status_code == snapshot_retry.status_code == 200
    assert snapshot_first.json()["snapshot_id"] == snapshot_retry.json()["snapshot_id"]
    assert DailySnapshot.objects.count() == 1

    complete_path = f"/inspection-runs/{run_id}/complete/"
    complete_first = _post(client, complete_path)
    complete_retry = _post(client, complete_path)
    assert complete_first.status_code == complete_retry.status_code == 200
    assert complete_first.json()["inspection_run_id"] == complete_retry.json()["inspection_run_id"]
    assert InspectionRun.objects.get(pk=run_id).status == InspectionRun.Status.SUCCEEDED
    assert RiskStatusHistory.objects.count() == 1


@pytest.mark.django_db
def test_dataset_and_run_retries_reject_conflicting_immutable_inputs():
    environment = _environment()
    client = Client()
    payload = {
        "environment_id": str(environment.pk),
        "dataset_date": DAY.isoformat(),
        "seed": 7,
        "scenario": "llm_scheduler_pressure",
    }
    first = _post(client, "/datasets/", payload)
    assert first.status_code == 200

    conflict = dict(payload, scenario="control_plane_anti_affinity")
    assert _post(client, "/datasets/", conflict).status_code == 200
    assert MockDataset.objects.count() == 2

    run_payload = {
        "dataset_id": first.json()["dataset_id"],
        "environment_id": str(environment.pk),
        "run_date": DAY.isoformat(),
        "dag_run_id": "same-dag-run",
    }
    assert _post(client, "/inspection-runs/", run_payload).status_code == 200
    run_conflict = dict(run_payload, run_date="2026-08-24")
    response = _post(client, "/inspection-runs/", run_conflict)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "immutable_input_conflict"
    assert InspectionRun.objects.count() == 1
