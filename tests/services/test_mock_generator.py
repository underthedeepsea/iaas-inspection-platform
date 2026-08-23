from datetime import date

import pytest

from apps.mockdata.services import persist_dataset
from services.mock_generator.generator import generate_dataset


BUSINESS_DATE = date(2026, 8, 23)


def test_same_seed_scenario_and_date_reproduce_the_same_key_points():
    first = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)
    second = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)

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

    assert metric_series["ttft_ms"][0] < metric_series["ttft_ms"][-1]
    assert metric_series["queue_depth"][0] < metric_series["queue_depth"][-1]
    assert metric_series["gpu_util_percent"][0] > metric_series["gpu_util_percent"][-1]


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
    assert risks[0] == generate_dataset(
        1729, "control_plane_anti_affinity", BUSINESS_DATE
    ).events[0]


def test_data_incomplete_omits_required_data_instead_of_fabricating_null_metrics():
    dataset = generate_dataset(1729, "data_incomplete", BUSINESS_DATE)
    metric_names = {point.metric_name for point in dataset.metrics}

    assert "queue_depth" not in metric_names
    assert dataset.missing_data == ("queue_depth",)
    assert all(point.value is not None for point in dataset.metrics)


@pytest.mark.django_db
def test_persist_dataset_writes_ready_dataset_and_all_mock_rows():
    from apps.core.models import Environment

    environment = Environment.objects.create(
        name="Mock test",
        slug="mock-test-1729",
    )
    generated = generate_dataset(1729, "llm_scheduler_pressure", BUSINESS_DATE)

    persisted = persist_dataset(environment, generated)

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

    from apps.inspections.models import MockChange, MockEvent, MockLog, MockMetric

    assert MockMetric.objects.filter(dataset=persisted).count() == len(generated.metrics)
    assert MockLog.objects.filter(dataset=persisted).count() == len(generated.logs)
    assert MockEvent.objects.filter(dataset=persisted).count() == len(generated.events)
    assert MockChange.objects.filter(dataset=persisted).count() == len(generated.changes)
