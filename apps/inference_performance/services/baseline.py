from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Any

from .fixed import PRIMARY_METRICS, STATUS_RANK, highest_status, metric_value

SUPPORT_METRICS = ("throughput.generation_tps", "throughput.prompt_tps", "cache.kv_cache_hit_rate", "requests.running", "ttft.e2e_ratio")


@dataclass(frozen=True)
class MetricBaseline:
    median: float
    mad: float
    robust_sigma: float
    sample_count: int


@dataclass(frozen=True)
class HistoricalBaseline:
    state: str
    days_covered: int
    sample_count: int
    metrics: dict[str, MetricBaseline]
    load_filter: str


def _downsample(items: list, maximum: int) -> list:
    if len(items) <= maximum:
        return items
    step = len(items) / maximum
    return [items[int(index * step)] for index in range(maximum)]


def build_baseline(*, snapshot, max_samples: int = 4096) -> HistoricalBaseline:
    queryset = snapshot.__class__.objects.filter(
        environment=snapshot.environment, engine_id=snapshot.engine_id, engine_type=snapshot.engine_type,
        model_name=snapshot.model_name, window_end__gte=snapshot.window_end - timedelta(days=14),
        window_end__lt=snapshot.window_end,
    ).order_by("window_end", "pk").values('window_start', 'window_end', 'metrics')
    count = queryset.count()
    stride = max(1, (count + max_samples - 1) // max_samples)
    history = []
    for index, item in enumerate(queryset.iterator(chunk_size=512)):
        if index % stride:
            continue
        if (item['window_end'] - item['window_start']) != (snapshot.window_end - snapshot.window_start):
            continue
        metrics = item['metrics']
        if (metrics['traffic']['qps'] == 0 and metrics['requests']['running'] == 0 and
                metrics['requests']['waiting'] == 0 and metrics['throughput']['generation_tps'] == 0 and
                metrics['throughput']['prompt_tps'] == 0):
            continue
        history.append(item)
    current_qps = metric_value(snapshot.metrics, "traffic.qps")
    load_filter = "FULL_HISTORY_FALLBACK"
    if current_qps > 0:
        comparable = [
            item for item in history
            if current_qps * 0.5 <= metric_value(item['metrics'], "traffic.qps") <= current_qps * 1.5
        ]
        if len(comparable) >= 100 and len({item['window_end'].date() for item in comparable}) >= 3:
            history = comparable
            load_filter = "QPS_COMPARABLE"
    days_covered = len({item['window_end'].date() for item in history})
    values: dict[str, MetricBaseline] = {}
    for metric in (*PRIMARY_METRICS, *SUPPORT_METRICS):
        series = [metric_value(item['metrics'], metric) for item in history]
        if not series:
            continue
        center = float(median(series))
        mad = float(median([abs(value - center) for value in series]))
        values[metric] = MetricBaseline(center, mad, 1.4826 * mad, len(series))
    state = "READY" if len(history) >= 100 and days_covered >= 3 else "NOT_READY"
    return HistoricalBaseline(state, days_covered, len(history), values, load_filter)


def evaluate_dynamic(*, current_metrics: dict[str, Any], baseline: HistoricalBaseline, policy: dict[str, Any]) -> dict[str, Any]:
    result = {
        "status": "NOT_READY" if baseline.state != "READY" else "NORMAL",
        "baseline_state": baseline.state, "baseline_days": baseline.days_covered,
        "sample_count": baseline.sample_count, "load_filter": baseline.load_filter, "metrics": {},
    }
    if baseline.state != "READY":
        return result
    dynamic = policy["dynamic"]
    statuses: list[str] = []
    for metric, item in baseline.metrics.items():
        current = metric_value(current_metrics, metric)
        warning = max(item.median * (1 + float(dynamic["warning_change_ratio"])), item.median + float(dynamic["warning_z"]) * item.robust_sigma)
        critical = max(item.median * (1 + float(dynamic["critical_change_ratio"])), item.median + float(dynamic["critical_z"]) * item.robust_sigma)
        zero_baseline = item.median == 0
        if zero_baseline:
            status = 'NOT_EVALUABLE'
        else:
            status = "CRITICAL" if current >= critical else "WARNING" if current >= warning else "NORMAL"
        primary = metric in PRIMARY_METRICS
        contributes = primary and result['load_filter'] == 'QPS_COMPARABLE' and not zero_baseline
        result["metrics"][metric] = {
            "metric": metric, "current": current, "baseline_median": item.median, "mad": item.mad,
            "robust_sigma": item.robust_sigma, "warning": warning, "critical": critical,
            "change_ratio": None if zero_baseline else (current - item.median) / item.median,
            "absolute_change": current - item.median,
            "status": status if primary else 'OBSERVED',
            "quality_reason": 'ZERO_BASELINE' if zero_baseline else None,
            "contributes_to_status": contributes,
        }
        if contributes:
            statuses.append(status)
    result["status"] = highest_status(statuses)
    return result
