from __future__ import annotations

from typing import Any

PRIMARY_METRICS = (
    "ttft.p95_ms", "ttft.p99_ms", "tpot.p95_ms", "tpot.p99_ms",
    "e2e.p95_ms", "e2e.p99_ms", "requests.waiting",
)
STATUS_RANK = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


def metric_value(metrics: dict[str, Any], metric: str) -> float:
    group, name = metric.split(".", 1)
    return float(metrics[group][name])


def highest_status(statuses: list[str]) -> str:
    return max(statuses or ["NORMAL"], key=lambda status: STATUS_RANK.get(status, 0))


def _raw_status(*, current: float, warning: float, critical: float) -> str:
    return "CRITICAL" if current >= critical else "WARNING" if current >= warning else "NORMAL"


def evaluate_fixed(*, current_metrics: dict[str, Any], policy: dict[str, Any], previous_metrics: list[dict[str, Any]], current_window=None) -> dict[str, Any]:
    persistence = int(policy.get("persistence", {}).get("consecutive_hits", 2))
    max_gap = int(policy.get("quality", {}).get("max_gap_seconds", 300))
    results: dict[str, dict[str, Any]] = {}
    for metric in PRIMARY_METRICS:
        thresholds = policy.get("fixed", {}).get(metric)
        if not isinstance(thresholds, dict):
            continue
        current = metric_value(current_metrics, metric)
        warning = float(thresholds["warning"])
        critical = float(thresholds["critical"])
        raw_status = _raw_status(current=current, warning=warning, critical=critical)
        warning_hits = critical_hits = 0
        previous_window = current_window
        for previous_item in previous_metrics:
            metrics = previous_item.get('metrics', previous_item) if isinstance(previous_item, dict) else previous_item
            if previous_window and isinstance(previous_item, dict) and 'window_end' in previous_item:
                from datetime import timedelta
                start, end = previous_item['window_start'], previous_item['window_end']
                later_start, later_end = previous_window
                if (later_end - later_start) != (end - start) or later_start < end or later_start - end > timedelta(seconds=max_gap):
                    break
                previous_window = (start, end)
            previous = metric_value(metrics, metric)
            prior_status = _raw_status(current=previous, warning=warning, critical=critical)
            if prior_status == 'NORMAL':
                break
            warning_hits += 1
            if prior_status == 'CRITICAL' and critical_hits == warning_hits - 1:
                critical_hits += 1
            if warning_hits >= persistence - 1:
                break
        effective_status = ('CRITICAL' if raw_status == 'CRITICAL' and critical_hits >= persistence - 1
                            else 'WARNING' if raw_status != 'NORMAL' and warning_hits >= persistence - 1
                            else 'NORMAL')
        results[metric] = {
            "metric": metric, "current": current, "warning": warning, "critical": critical,
            "raw_status": raw_status, "effective_status": effective_status,
            "consecutive_hits": warning_hits + (1 if raw_status != "NORMAL" else 0),
            "critical_consecutive_hits": critical_hits + (1 if raw_status == 'CRITICAL' else 0),
        }
    return {"status": highest_status([item["effective_status"] for item in results.values()]), "metrics": results}
