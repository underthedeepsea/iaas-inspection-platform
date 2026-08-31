"""Pure, deterministic mock data generation for the first inspection cases."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import random
from typing import Optional

from .scenarios import SUPPORTED_SCENARIOS, scenario_config


GENERATOR_VERSION = "1.0.0"
DEFAULT_DATASET_DATE = date(2026, 1, 1)
POINT_COUNT = 6


@dataclass(frozen=True)
class AssetRecord:
    asset_key: str
    asset_type: str
    name: str
    parent_key: Optional[str] = None
    labels: dict = field(default_factory=dict)
    topology: dict = field(default_factory=dict)

    @property
    def external_key(self):
        return self.asset_key


@dataclass(frozen=True)
class MetricPoint:
    asset_key: str
    metric_name: str
    ts: datetime
    value: float
    labels: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LogRecord:
    asset_key: str
    ts: datetime
    source: str
    level: str
    message: str
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EventRecord:
    asset_key: Optional[str]
    ts: datetime
    event_type: str
    reason: str = ""
    message: str = ""
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChangeRecord:
    asset_key: Optional[str]
    start_at: datetime
    end_at: Optional[datetime]
    change_type: str
    summary: str
    attributes: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GeneratedDataset:
    seed: int
    scenario: str
    dataset_date: date
    version: str = GENERATOR_VERSION
    assets: tuple = ()
    metrics: tuple = ()
    logs: tuple = ()
    events: tuple = ()
    changes: tuple = ()
    missing_data: tuple = ()

    @property
    def business_date(self):
        return self.dataset_date

    @property
    def asset_count(self):
        return len(self.assets)

    @property
    def metric_count(self):
        return len(self.metrics)

    @property
    def log_count(self):
        return len(self.logs)

    @property
    def event_count(self):
        return len(self.events)

    @property
    def change_count(self):
        return len(self.changes)


class MockDataGenerator:
    """Generate one deterministic dataset without importing Django."""

    version = GENERATOR_VERSION

    def __init__(self, seed, scenario, dataset_date=None, *, business_date=None):
        if dataset_date is not None and business_date is not None:
            if _coerce_date(dataset_date) != _coerce_date(business_date):
                raise ValueError("dataset_date and business_date must match")
        self.seed = _coerce_seed(seed)
        self.scenario = scenario
        scenario_config(scenario)
        self.dataset_date = _coerce_date(
            dataset_date if dataset_date is not None else business_date
        )

    def generate(self):
        rng = random.Random(self.seed)
        timestamps = _timestamps(self.dataset_date)
        assets = _assets_for(self.scenario)
        metrics = _metrics_for(self.scenario, timestamps, rng)
        logs = _logs_for(self.scenario, timestamps)
        events = _events_for(self.scenario, timestamps)
        changes = _changes_for(self.scenario, timestamps)
        config = scenario_config(self.scenario)
        return GeneratedDataset(
            seed=self.seed,
            scenario=self.scenario,
            dataset_date=self.dataset_date,
            version=GENERATOR_VERSION,
            assets=tuple(assets),
            metrics=tuple(metrics),
            logs=tuple(logs),
            events=tuple(events),
            changes=tuple(changes),
            missing_data=tuple(config["missing_data"]),
        )


def generate_dataset(seed, scenario, dataset_date=None, *, business_date=None):
    return MockDataGenerator(
        seed,
        scenario,
        dataset_date,
        business_date=business_date,
    ).generate()


def _coerce_seed(seed):
    if isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    try:
        value = int(seed)
    except (TypeError, ValueError) as exc:
        raise ValueError("seed must be an integer") from exc
    if str(value) != str(seed).strip() and not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    return value


def _coerce_date(value):
    if value is None:
        return DEFAULT_DATASET_DATE
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("dataset_date must be a date or ISO date string") from exc


def _timestamps(dataset_date):
    start = datetime.combine(dataset_date, time.min, tzinfo=timezone.utc)
    return tuple(start + timedelta(minutes=5 * index) for index in range(POINT_COUNT))


def _assets_for(scenario):
    control_plane_host = "host-control-0"
    second_control_plane_host = (
        control_plane_host
        if scenario == "control_plane_anti_affinity"
        else "host-worker-0"
    )
    cluster_platform = {
        "kvm_cluster_baseline": "kvm",
        "k8s_cluster_baseline": "kubernetes",
    }.get(scenario, "kubernetes")
    assets = [
        AssetRecord(
            "cluster-0",
            "CLUSTER",
            "mock-cluster",
            labels={"environment": "mock", "platform": cluster_platform},
            topology={"zones": ["zone-a", "zone-b"]},
        ),
        AssetRecord(
            "host-control-0",
            "HOST",
            "control-host-0",
            parent_key="cluster-0",
            labels={"role": "control-plane", "zone": "zone-a"},
            topology={"zone": "zone-a"},
        ),
        AssetRecord(
            "host-worker-0",
            "HOST",
            "worker-host-0",
            parent_key="cluster-0",
            labels={"role": "worker", "zone": "zone-b"},
            topology={"zone": "zone-b"},
        ),
        AssetRecord(
            "vm-0",
            "VM",
            "mock-vm-0",
            parent_key="host-worker-0",
            labels={"workload": "llm"},
            topology={"host": "host-worker-0"},
        ),
        AssetRecord(
            "control-plane-0",
            "POD",
            "control-plane-0",
            parent_key=control_plane_host,
            labels={"component": "control-plane", "anti_affinity": "control-plane"},
            topology={"host": control_plane_host},
        ),
        AssetRecord(
            "control-plane-1",
            "POD",
            "control-plane-1",
            parent_key=second_control_plane_host,
            labels={"component": "control-plane", "anti_affinity": "control-plane"},
            topology={"host": second_control_plane_host},
        ),
        AssetRecord(
            "gpu-0",
            "GPU",
            "mock-gpu-0",
            parent_key="vm-0",
            labels={"model": "A100"},
            topology={"host": "host-worker-0"},
        ),
        AssetRecord(
            "llm-0",
            "LLM_INSTANCE",
            "mock-llm-0",
            parent_key="vm-0",
            labels={"model": "mock-llm"},
            topology={"gpu": "gpu-0"},
        ),
    ]
    if scenario == "mixed_resource_inspection":
        assets.insert(
            1,
            AssetRecord(
                "cluster-k8s-0",
                "CLUSTER",
                "mock-kubernetes-cluster",
                labels={"environment": "mock", "platform": "kubernetes"},
                topology={"zones": ["zone-a", "zone-b"]},
            ),
        )
        assets.insert(
            2,
            AssetRecord(
                "cluster-kvm-0",
                "CLUSTER",
                "mock-kvm-cluster",
                labels={"environment": "mock", "platform": "kvm"},
                topology={"zones": ["zone-a", "zone-b"]},
            ),
        )
    return assets


def _metrics_for(scenario, timestamps, rng):
    points = []
    for index, timestamp in enumerate(timestamps):
        points.extend(
            (
                MetricPoint(
                    "host-worker-0",
                    "cpu_percent",
                    timestamp,
                    float(30 + rng.randint(-2, 2)),
                ),
                MetricPoint(
                    "host-worker-0",
                    "memory_percent",
                    timestamp,
                    float(55 + rng.randint(-2, 2)),
                ),
                MetricPoint("host-worker-0", "rx_missed", timestamp, float(rng.randint(0, 1))),
                MetricPoint(
                    "host-worker-0",
                    "softirq_percent",
                    timestamp,
                    float(4 + rng.randint(-1, 1)),
                ),
                MetricPoint(
                    "host-worker-0",
                    "capacity_percent",
                    timestamp,
                    float(62 + rng.randint(-2, 2)),
                ),
            )
        )
        if scenario in {"llm_scheduler_pressure", "mixed_resource_inspection"}:
            ttft = 100 + index * 20 + rng.randint(-2, 2)
            queue = 2 + index * 3 + rng.randint(-1, 1)
            gpu_util = 84 - index * 4 + rng.randint(-1, 1)
        else:
            ttft = 100 + rng.randint(-3, 3)
            queue = 2 + rng.randint(0, 1)
            gpu_util = 70 + rng.randint(-3, 3)
        points.append(MetricPoint("llm-0", "ttft_ms", timestamp, float(ttft)))
        if scenario != "data_incomplete":
            points.append(MetricPoint("llm-0", "queue_depth", timestamp, float(queue)))
        points.append(MetricPoint("llm-0", "gpu_util_percent", timestamp, float(gpu_util)))
    return points


def _logs_for(scenario, timestamps):
    logs = []
    if scenario in {"llm_scheduler_pressure", "mixed_resource_inspection"}:
        logs.append(
            LogRecord(
                "llm-0",
                timestamps[-1],
                "scheduler",
                "WARNING",
                "scheduler queue pressure detected",
                {"signal": "scheduler_pressure"},
            )
        )
    if scenario in {"control_plane_anti_affinity", "mixed_resource_inspection"}:
        logs.append(
            LogRecord(
                "control-plane-1",
                timestamps[-1],
                "scheduler",
                "WARNING",
                "control-plane anti-affinity violation",
                {"signal": "anti_affinity"},
            )
        )
    if logs:
        return logs
    if scenario == "data_incomplete":
        return [
            LogRecord(
                "llm-0",
                timestamps[-1],
                "runtime",
                "ERROR",
                "required metric queue_depth is missing",
                {"missing": ["queue_depth"]},
            )
        ]
    return [
        LogRecord(
            "llm-0",
            timestamps[-1],
            "runtime",
            "INFO",
            "mock workload healthy",
            {"signal": "healthy_baseline"},
        )
    ]


def _events_for(scenario, timestamps):
    events = []
    if scenario in {"control_plane_anti_affinity", "mixed_resource_inspection"}:
        events.append(
            EventRecord(
                "control-plane-1",
                timestamps[-1],
                "TOPOLOGY_RISK",
                "ANTI_AFFINITY_VIOLATION",
                "control-plane pods share host-control-0",
                {
                    "anti_affinity_key": "control-plane",
                    "host": "host-control-0",
                    "members": ["control-plane-0", "control-plane-1"],
                },
            )
        )
    if scenario in {"llm_scheduler_pressure", "mixed_resource_inspection"}:
        events.append(
            EventRecord(
                "llm-0",
                timestamps[-1],
                "PERFORMANCE_DEGRADATION",
                "SCHEDULER_PRESSURE",
                "LLM scheduler pressure is increasing",
                {"signals": ["ttft_ms", "queue_depth", "gpu_util_percent"]},
            )
        )
    if events:
        return events
    if scenario == "data_incomplete":
        return [
            EventRecord(
                "llm-0",
                timestamps[-1],
                "DATA_QUALITY",
                "MISSING_REQUIRED_METRIC",
                "queue_depth data is incomplete",
                {"missing": ["queue_depth"]},
            )
        ]
    return []


def _changes_for(scenario, timestamps):
    changes = [
        ChangeRecord(
            "llm-0",
            timestamps[1],
            timestamps[2],
            "deploy",
            "mock workload deployment",
            {"scenario": scenario},
        )
    ]
    if scenario == "mixed_resource_inspection":
        changes.append(
            ChangeRecord(
                "control-plane-1",
                timestamps[2],
                timestamps[3],
                "topology_change",
                "mock control-plane placement change",
                {"scenario": scenario},
            )
        )
    return changes


__all__ = [
    "AssetRecord",
    "ChangeRecord",
    "EventRecord",
    "GeneratedDataset",
    "GENERATOR_VERSION",
    "LogRecord",
    "MetricPoint",
    "MockDataGenerator",
    "SUPPORTED_SCENARIOS",
    "generate_dataset",
]
