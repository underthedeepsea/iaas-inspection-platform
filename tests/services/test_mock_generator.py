from datetime import date, datetime, timezone

import pytest

from apps.mockdata.services import persist_dataset
from services.mock_generator.generator import generate_dataset


BUSINESS_DATE = date(2026, 8, 23)


def test_same_seed_scenario_and_date_reproduce_the_same_key_points():
    first = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)
    second = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)

    assert [
        (point.metric_name, point.ts.isoformat(), point.value)
        for point in first.metrics
        if point.asset_key == "llm-0"
    ] == [
        ("ttft_ms", "2026-08-23T00:00:00+00:00", 99.0),
        ("queue_depth", "2026-08-23T00:00:00+00:00", 2.0),
        ("gpu_util_percent", "2026-08-23T00:00:00+00:00", 85.0),
        ("ttft_ms", "2026-08-23T00:05:00+00:00", 121.0),
        ("queue_depth", "2026-08-23T00:05:00+00:00", 4.0),
        ("gpu_util_percent", "2026-08-23T00:05:00+00:00", 81.0),
        ("ttft_ms", "2026-08-23T00:10:00+00:00", 142.0),
        ("queue_depth", "2026-08-23T00:10:00+00:00", 8.0),
        ("gpu_util_percent", "2026-08-23T00:10:00+00:00", 77.0),
        ("ttft_ms", "2026-08-23T00:15:00+00:00", 162.0),
        ("queue_depth", "2026-08-23T00:15:00+00:00", 10.0),
        ("gpu_util_percent", "2026-08-23T00:15:00+00:00", 73.0),
        ("ttft_ms", "2026-08-23T00:20:00+00:00", 182.0),
        ("queue_depth", "2026-08-23T00:20:00+00:00", 14.0),
        ("gpu_util_percent", "2026-08-23T00:20:00+00:00", 69.0),
        ("ttft_ms", "2026-08-23T00:25:00+00:00", 201.0),
        ("queue_depth", "2026-08-23T00:25:00+00:00", 16.0),
        ("gpu_util_percent", "2026-08-23T00:25:00+00:00", 63.0),
    ]
    assert first.assets == second.assets
    assert first.metrics == second.metrics
    assert first.logs == second.logs
    assert first.events == second.events
    assert first.changes == second.changes


def test_llm_scheduler_pressure_has_rising_ttft_and_queue_and_falling_gpu_util():
    dataset = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)
    metric_series = {
        metric_name: [
            point.value
            for point in dataset.metrics
            if point.asset_key == "llm-0" and point.metric_name == metric_name
        ]
        for metric_name in ("ttft_ms", "queue_depth", "gpu_util_percent")
    }

    assert metric_series == {
        "ttft_ms": [99.0, 121.0, 142.0, 162.0, 182.0, 201.0],
        "queue_depth": [2.0, 4.0, 8.0, 10.0, 14.0, 16.0],
        "gpu_util_percent": [85.0, 81.0, 77.0, 73.0, 69.0, 63.0],
    }
    assert all(
        before < after
        for before, after in zip(metric_series["ttft_ms"], metric_series["ttft_ms"][1:])
    )
    assert all(
        before < after
        for before, after in zip(metric_series["queue_depth"], metric_series["queue_depth"][1:])
    )
    assert all(
        before > after
        for before, after in zip(
            metric_series["gpu_util_percent"], metric_series["gpu_util_percent"][1:]
        )
    )


def test_control_plane_anti_affinity_emits_a_deterministic_topology_risk():
    dataset = generate_dataset(1729, "control_plane_anti_affinity", BUSINESS_DATE)
    risks = [event for event in dataset.events if event.event_type == "TOPOLOGY_RISK"]

    assert len(risks) == 1
    assert risks[0].reason == "ANTI_AFFINITY_VIOLATION"
    assert risks[0].attributes == {
        "anti_affinity_key": "control-plane",
        "host": "host-control-0",
        "members": ["control-plane-0", "control-plane-1"],
    }
    control_plane_assets = {
        asset.asset_key: asset
        for asset in dataset.assets
        if asset.asset_key in ("control-plane-0", "control-plane-1")
    }
    assert control_plane_assets["control-plane-0"].parent_key == "host-control-0"
    assert control_plane_assets["control-plane-1"].parent_key == "host-control-0"
    assert control_plane_assets["control-plane-0"].topology["host"] == "host-control-0"
    assert control_plane_assets["control-plane-1"].topology["host"] == "host-control-0"
    assert risks[0] == generate_dataset(
        1729, "control_plane_anti_affinity", BUSINESS_DATE
    ).events[0]


def test_data_incomplete_omits_required_data_instead_of_fabricating_null_metrics():
    dataset = generate_dataset(1729, "data_incomplete", BUSINESS_DATE)
    metric_names = {point.metric_name for point in dataset.metrics}

    assert "queue_depth" not in metric_names
    assert dataset.missing_data == ("queue_depth",)
    assert all(point.value is not None for point in dataset.metrics)


def test_mixed_fixture_contains_control_plane_and_llm_signals():
    dataset = generate_dataset(1729, "mixed_resource_inspection", BUSINESS_DATE)

    assert {asset.asset_key for asset in dataset.assets} >= {
        "cluster-kvm-0",
        "cluster-k8s-0",
    }
    assert {asset.asset_type for asset in dataset.assets} >= {
        "CLUSTER",
        "HOST",
        "POD",
        "GPU",
        "LLM_INSTANCE",
    }
    assert {event.reason for event in dataset.events} >= {
        "ANTI_AFFINITY_VIOLATION",
        "SCHEDULER_PRESSURE",
    }
    assert {log.source for log in dataset.logs} >= {"scheduler"}
    assert {change.asset_key for change in dataset.changes} >= {"llm-0"}


@pytest.mark.django_db
def test_persist_dataset_writes_ready_dataset_and_all_mock_rows():
    from apps.core.models import Environment

    environment = Environment.objects.create(
        name="Mock test",
        slug="mock-test-1729",
    )
    generated = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)

    persisted = persist_dataset(environment, generated)
    from apps.inspections.models import (
        MockChange,
        MockDataset,
        MockEvent,
        MockLog,
        MockMetric,
    )

    persisted = MockDataset.objects.get(pk=persisted.pk)

    assert persisted.status == "READY"
    assert persisted.version == "1.0.0"
    assert persisted.seed == 1729
    assert persisted.scenario == "llm_scheduler_pressure"
    assert persisted.dataset_date == BUSINESS_DATE
    assert persisted.asset_count == len(generated.assets)
    assert persisted.metric_count == len(generated.metrics)
    assert persisted.log_count == len(generated.logs)
    assert persisted.event_count == len(generated.events)
    assert persisted.change_count == len(generated.changes)
    assert persisted.generator_config == {
        "seed": 1729,
        "scenario": "llm_scheduler_pressure",
        "dataset_date": "2026-08-23",
        "version": "1.0.0",
        "missing_data": [],
    }

    from apps.assets.models import Asset

    assert MockMetric.objects.filter(dataset=persisted).count() == len(generated.metrics)
    assert MockLog.objects.filter(dataset=persisted).count() == len(generated.logs)
    assert MockEvent.objects.filter(dataset=persisted).count() == len(generated.events)
    assert MockChange.objects.filter(dataset=persisted).count() == len(generated.changes)

    llm_asset = Asset.objects.get(environment=environment, external_key="llm-0")
    metric = MockMetric.objects.get(
        dataset=persisted,
        metric_name="ttft_ms",
        ts=datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc),
    )
    assert metric.asset_id == llm_asset.pk
    assert metric.value == 99.0
    assert metric.labels == {}

    log = MockLog.objects.get(dataset=persisted)
    assert log.asset_id == llm_asset.pk
    assert log.source == "scheduler"
    assert log.level == "WARNING"
    assert log.message == "scheduler queue pressure detected"
    assert log.attributes == {"signal": "scheduler_pressure"}

    event = MockEvent.objects.get(dataset=persisted)
    assert event.asset_id == llm_asset.pk
    assert event.event_type == "PERFORMANCE_DEGRADATION"
    assert event.reason == "SCHEDULER_PRESSURE"
    assert event.message == "LLM scheduler pressure is increasing"
    assert event.attributes == {
        "signals": ["ttft_ms", "queue_depth", "gpu_util_percent"]
    }

    change = MockChange.objects.get(dataset=persisted)
    assert change.asset_id == llm_asset.pk
    assert change.start_at == datetime(2026, 8, 23, 0, 5, tzinfo=timezone.utc)
    assert change.end_at == datetime(2026, 8, 23, 0, 10, tzinfo=timezone.utc)
    assert change.change_type == "deploy"
    assert change.summary == "mock workload deployment"
    assert change.attributes == {"scenario": "llm_scheduler_pressure"}
