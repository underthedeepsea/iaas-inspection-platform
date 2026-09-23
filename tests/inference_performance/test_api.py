import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.test import Client

from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inference_performance.api import serialize_profile
from .helpers import payload, sample


@pytest.mark.parametrize(
    'raw_status,quality,plugin,expected', [
        ('NORMAL', {'state': 'IDLE', 'pending_confirmation': False}, True, 'UNKNOWN'),
        ('NORMAL', {'state': 'READY', 'pending_confirmation': True}, True, 'UNKNOWN'),
        ('NORMAL', {'state': 'READY', 'pending_confirmation': False}, False, 'UNKNOWN'),
        ('NORMAL', {'state': 'READY', 'pending_confirmation': False}, True, 'NORMAL'),
        ('WARNING', {'state': 'READY', 'pending_confirmation': True}, True, 'WARNING'),
        ('CRITICAL', {'state': 'IDLE', 'pending_confirmation': True}, True, 'CRITICAL'),
    ],
)
def test_current_profile_status_respects_quality_and_version(raw_status, quality, plugin, expected):
    end = datetime.now(timezone.utc)
    snapshot = SimpleNamespace(
        id='snapshot-1', engine_id='engine-1', engine_type='vllm', model_name='Model',
        window_start=end - timedelta(minutes=1), window_end=end, metrics={},
        evaluation={
            'status': raw_status,
            'quality': quality,
            'plugin': {'id': 'inference-performance', 'version': '1.0.0'} if plugin else {},
            'resolved_policy': {'quality': {'max_age_seconds': 300}},
        },
    )
    profile = serialize_profile(snapshot)
    assert profile['freshness']['state'] == 'FRESH'
    assert profile['status'] == expected
    assert profile['evaluation_status'] == raw_status


@pytest.mark.django_db
def test_snapshot_ingest_is_idempotent_and_exposes_profile():
    environment = Environment.objects.create(name="Production", slug="prod-a")
    client = Client()
    request = payload(str(environment.id), sample_id="same-sample")
    first = client.post("/api/v1/inference-performance/snapshots", data=json.dumps(request), content_type="application/json")
    second = client.post("/api/v1/inference-performance/snapshots", data=json.dumps(request), content_type="application/json")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert InferencePerformanceSnapshot.objects.count() == 1
    profile = client.get("/api/v1/inference-performance/engines/qwen-prod-1/profile", {"environment_id": str(environment.id)})
    assert profile.status_code == 200
    assert profile.json()["engine"]["model_name"] == "Qwen/Qwen3-32B"


@pytest.mark.django_db
def test_snapshot_rejects_invalid_input_and_batch_evaluates_only_latest():
    environment = Environment.objects.create(name="Production", slug="prod-a")
    client = Client()
    invalid = payload(str(environment.id))
    invalid["sample"]["ttft"]["p95_ms"] = -1
    response = client.post("/api/v1/inference-performance/snapshots", data=json.dumps(invalid), content_type="application/json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    end = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    batch = {
        "source": "inference-monitor", "environment_id": str(environment.id),
        "engine": {"engine_id": "qwen-prod-1", "engine_type": "vllm", "model_name": "Qwen/Qwen3-32B"},
        "evaluate_latest": True,
        "samples": [sample("history", end - timedelta(minutes=1)), sample("latest", end)],
    }
    response = client.post("/api/v1/inference-performance/snapshots/batch", data=json.dumps(batch), content_type="application/json")
    assert response.status_code == 201
    assert response.json()["count"] == 2
    assert response.json()["evaluated"]["engine"]["engine_id"] == "qwen-prod-1"


@pytest.mark.django_db
def test_profile_returns_not_found_for_unknown_engine():
    environment = Environment.objects.create(name="Production", slug="prod-a")
    response = Client().get("/api/v1/inference-performance/engines/missing/profile", {"environment_id": str(environment.id)})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ENGINE_PERFORMANCE_NOT_FOUND"


def test_snapshot_returns_validation_error_for_integer_too_large_for_float():
    request = payload("unused-environment")
    request["sample"]["ttft"]["avg_ms"] = 10 ** 400

    response = Client().post("/api/v1/inference-performance/snapshots", data=json.dumps(request), content_type="application/json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"] == {"field": "ttft.avg_ms"}


@pytest.mark.django_db
def test_batch_replay_preserves_saved_evaluation_and_evaluates_an_unevaluated_latest():
    environment = Environment.objects.create(name="Production", slug="prod-a")
    client = Client()
    end = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    batch = {
        "source": "inference-monitor", "environment_id": str(environment.id),
        "engine": {"engine_id": "qwen-prod-1", "engine_type": "vllm", "model_name": "Qwen/Qwen3-32B"},
        "evaluate_latest": True,
        "samples": [sample("saved", end)],
    }
    first = client.post("/api/v1/inference-performance/snapshots/batch", data=json.dumps(batch), content_type="application/json")
    assert first.status_code == 201
    saved = InferencePerformanceSnapshot.objects.get(sample_id="saved")
    original_evaluation = saved.evaluation

    with patch("apps.inference_performance.services.ingest.dispatch_code_rule") as dispatch:
        replay = client.post(
            "/api/v1/inference-performance/snapshots/batch", data=json.dumps(batch), content_type="application/json",
        )
        dispatch.assert_not_called()
    saved.refresh_from_db()
    assert replay.status_code == 201
    assert replay.json()["created_count"] == 0
    assert saved.evaluation == original_evaluation

    unevaluated_request = payload(str(environment.id), sample_id="unevaluated", end=end + timedelta(minutes=1))
    unevaluated = InferencePerformanceSnapshot.objects.create(
        environment=environment, source=unevaluated_request["source"], sample_id=unevaluated_request["sample"]["sample_id"],
        engine_id=unevaluated_request["engine"]["engine_id"], engine_type=unevaluated_request["engine"]["engine_type"],
        model_name=unevaluated_request["engine"]["model_name"],
        window_start=datetime.fromisoformat(unevaluated_request["sample"]["window_start"]),
        window_end=datetime.fromisoformat(unevaluated_request["sample"]["window_end"]),
        metrics={key: value for key, value in unevaluated_request["sample"].items() if key not in {"sample_id", "window_start", "window_end"}},
    )
    batch["samples"] = [unevaluated_request["sample"]]

    evaluated = client.post(
        "/api/v1/inference-performance/snapshots/batch", data=json.dumps(batch), content_type="application/json",
    )
    unevaluated.refresh_from_db()
    assert evaluated.status_code == 201
    assert evaluated.json()["created_count"] == 0
    assert unevaluated.evaluation["plugin"]["id"] == "inference-performance"
    profile = evaluated.json()["evaluated"]
    assert profile["snapshot_id"] == str(unevaluated.id)
    assert profile["plugin"]["id"] == "inference-performance"
    assert profile["evaluation_status"] == unevaluated.evaluation["status"]


@pytest.mark.django_db
def test_unevaluated_batch_normal_snapshot_breaks_fixed_threshold_consecutive_hits():
    environment = Environment.objects.create(name="Production", slug="prod-a")
    client = Client()
    end = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)

    first_high = client.post(
        "/api/v1/inference-performance/snapshots",
        data=json.dumps(payload(str(environment.id), sample_id="high-1", end=end, ttft_p95=600)),
        content_type="application/json",
    )
    assert first_high.status_code == 201
    assert first_high.json()["profile"]["fixed"]["metrics"]["ttft.p95_ms"]["raw_status"] == "WARNING"

    history = {
        "source": "inference-monitor", "environment_id": str(environment.id),
        "engine": {"engine_id": "qwen-prod-1", "engine_type": "vllm", "model_name": "Qwen/Qwen3-32B"},
        "evaluate_latest": False,
        "samples": [sample("normal-gap", end + timedelta(minutes=1), ttft_p95=300)],
    }
    historical = client.post(
        "/api/v1/inference-performance/snapshots/batch", data=json.dumps(history), content_type="application/json",
    )
    assert historical.status_code == 201
    assert historical.json()["evaluated"] is None

    second_high = client.post(
        "/api/v1/inference-performance/snapshots",
        data=json.dumps(payload(str(environment.id), sample_id="high-2", end=end + timedelta(minutes=2), ttft_p95=600)),
        content_type="application/json",
    )
    fixed = second_high.json()["profile"]["fixed"]
    assert second_high.status_code == 201
    assert fixed["metrics"]["ttft.p95_ms"]["raw_status"] == "WARNING"
    assert fixed["metrics"]["ttft.p95_ms"]["effective_status"] == "NORMAL"
    assert fixed["metrics"]["ttft.p95_ms"]["consecutive_hits"] == 1
