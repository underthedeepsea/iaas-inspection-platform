import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.test import Client

from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from .helpers import payload, sample


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

    with patch("apps.inference_performance.services.ingest.evaluate_snapshot") as evaluate_snapshot:
        replay = client.post(
            "/api/v1/inference-performance/snapshots/batch", data=json.dumps(batch), content_type="application/json",
        )
        evaluate_snapshot.assert_not_called()
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

    expected_evaluation = {
        "status": "WARNING",
        "fixed": {"status": "WARNING", "metrics": {}},
        "dynamic": {"status": "NOT_READY", "metrics": {}},
        "trend": {"status": "NOT_READY"},
        "policy_source": {"level": "default", "config_hash": "test-hash"},
        "reasons": [{"code": "MOCK_REASON"}],
    }
    with patch(
        "apps.inference_performance.services.ingest.evaluate_snapshot", return_value=expected_evaluation,
    ) as evaluate_snapshot:
        evaluated = client.post(
            "/api/v1/inference-performance/snapshots/batch", data=json.dumps(batch), content_type="application/json",
        )
        evaluate_snapshot.assert_called_once()
        assert evaluate_snapshot.call_args.args[0].pk == unevaluated.pk
    unevaluated.refresh_from_db()
    assert evaluated.status_code == 201
    assert evaluated.json()["created_count"] == 0
    assert unevaluated.evaluation == expected_evaluation
    profile = evaluated.json()["evaluated"]
    assert profile == {
        "snapshot_id": str(unevaluated.id),
        "engine": {"engine_id": "qwen-prod-1", "engine_type": "vllm", "model_name": "Qwen/Qwen3-32B"},
        "window": {
            "start": unevaluated.window_start.isoformat(),
            "end": unevaluated.window_end.isoformat(),
        },
        "status": "WARNING",
        "current_metrics": unevaluated.metrics,
        "fixed": expected_evaluation["fixed"],
        "dynamic": expected_evaluation["dynamic"],
        "trend": expected_evaluation["trend"],
        "policy_source": expected_evaluation["policy_source"],
        "reasons": expected_evaluation["reasons"],
    }


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
