from datetime import datetime, timedelta, timezone

import pytest

from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inference_performance.schemas import parse_snapshot_request
from apps.inference_performance.services.baseline import HistoricalBaseline, MetricBaseline, build_baseline, evaluate_dynamic
from apps.inference_performance.services.fixed import evaluate_fixed
from apps.inference_performance.services.policy import resolve_policy
from apps.inference_performance.services.trend import evaluate_trend
from .helpers import payload


def test_fixed_requires_two_consecutive_hits():
    policy = resolve_policy(engine_type="vllm", model_name="Qwen/Qwen3-32B").policy
    current = parse_snapshot_request(payload("prod-a", ttft_p95=600)).sample.metrics
    first = evaluate_fixed(current_metrics=current, policy=policy, previous_metrics=[])
    assert first["status"] == "NORMAL"
    second = evaluate_fixed(current_metrics=current, policy=policy, previous_metrics=[current])
    assert second["status"] == "WARNING"
    assert second["metrics"]["ttft.p95_ms"]["effective_status"] == "WARNING"


def test_fixed_uses_every_consecutive_snapshot_even_when_it_was_not_evaluated():
    policy = resolve_policy(engine_type="vllm", model_name="Qwen/Qwen3-32B").policy
    high = parse_snapshot_request(payload("prod-a", ttft_p95=600)).sample.metrics
    normal = parse_snapshot_request(payload("prod-a", ttft_p95=300)).sample.metrics

    after_high_then_normal = evaluate_fixed(current_metrics=high, policy=policy, previous_metrics=[normal, high])

    assert after_high_then_normal["status"] == "NORMAL"
    assert after_high_then_normal["metrics"]["ttft.p95_ms"]["consecutive_hits"] == 1


def test_dynamic_zero_baseline_is_normal_at_zero_but_flags_positive_degradation():
    policy = resolve_policy(engine_type="vllm", model_name="Qwen/Qwen3-32B").policy
    zero_metrics = parse_snapshot_request(payload("prod-a", waiting=0)).sample.metrics
    baseline = HistoricalBaseline(
        state="READY",
        days_covered=3,
        sample_count=100,
        metrics={"requests.waiting": MetricBaseline(median=0, mad=0, robust_sigma=0, sample_count=100)},
        load_filter="FULL_HISTORY_FALLBACK",
    )

    normal = evaluate_dynamic(current_metrics=zero_metrics, baseline=baseline, policy=policy)
    positive_metrics = parse_snapshot_request(payload("prod-a", waiting=1)).sample.metrics
    degraded = evaluate_dynamic(current_metrics=positive_metrics, baseline=baseline, policy=policy)

    assert normal["metrics"]["requests.waiting"]["status"] == "NORMAL"
    assert normal["status"] == "NORMAL"
    assert degraded["metrics"]["requests.waiting"]["status"] == "CRITICAL"
    assert degraded["status"] == "CRITICAL"


@pytest.mark.django_db
def test_baseline_qps_filter_dynamic_threshold_and_trend_do_not_share_status():
    environment = Environment.objects.create(name="Performance", slug="performance")
    base = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(100):
        request = parse_snapshot_request(payload(str(environment.id), sample_id=f"history-{index}", end=base + timedelta(minutes=index * 30), ttft_p95=300, qps=5))
        rows.append(InferencePerformanceSnapshot(
            environment=environment, source=request.source, sample_id=request.sample.sample_id,
            engine_id=request.engine.engine_id, engine_type=request.engine.engine_type, model_name=request.engine.model_name,
            window_start=request.sample.window_start, window_end=request.sample.window_end, metrics=request.sample.metrics,
        ))
    InferencePerformanceSnapshot.objects.bulk_create(rows)
    current_request = parse_snapshot_request(payload(str(environment.id), sample_id="current", end=base + timedelta(days=3), ttft_p95=400, qps=5))
    current = InferencePerformanceSnapshot.objects.create(
        environment=environment, source=current_request.source, sample_id=current_request.sample.sample_id,
        engine_id=current_request.engine.engine_id, engine_type=current_request.engine.engine_type, model_name=current_request.engine.model_name,
        window_start=current_request.sample.window_start, window_end=current_request.sample.window_end, metrics=current_request.sample.metrics,
    )
    policy = resolve_policy(engine_type="vllm", model_name="Qwen/Qwen3-32B").policy
    baseline = build_baseline(snapshot=current)
    dynamic = evaluate_dynamic(current_metrics=current.metrics, baseline=baseline, policy=policy)
    assert baseline.state == "READY"
    assert baseline.load_filter == "QPS_COMPARABLE"
    assert dynamic["metrics"]["ttft.p95_ms"]["status"] == "WARNING"
    assert dynamic["metrics"]["throughput.generation_tps"]["contributes_to_status"] is False

    recent = list(InferencePerformanceSnapshot.objects.filter(environment=environment).order_by("window_end"))[-6:]
    for index, row in enumerate(recent):
        row.window_end = base + timedelta(days=3, minutes=index * 10)
        row.metrics["ttft"]["p95_ms"] = 300 if index < 3 else 400
        row.save(update_fields=["window_end", "metrics"])
    current.refresh_from_db()
    trend = evaluate_trend(snapshot=current, policy=policy)
    assert trend["status"] == "DEGRADING"
