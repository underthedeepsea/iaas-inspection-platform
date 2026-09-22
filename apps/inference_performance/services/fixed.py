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


def evaluate_fixed(*, current_metrics: dict[str, Any], policy: dict[str, Any], previous_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    persistence = int(policy.get("persistence", {}).get("consecutive_hits", 2))
    results: dict[str, dict[str, Any]] = {}
    for metric in PRIMARY_METRICS:
        thresholds = policy.get("fixed", {}).get(metric)
        if not isinstance(thresholds, dict):
            continue
        current = metric_value(current_metrics, metric)
        warning = float(thresholds["warning"])
        critical = float(thresholds["critical"])
        raw_status = _raw_status(current=current, warning=warning, critical=critical)
        prior_hits = 0
        for metrics in previous_metrics:
            previous = metric_value(metrics, metric)
            if _raw_status(current=previous, warning=warning, critical=critical) in {"WARNING", "CRITICAL"}:
                prior_hits += 1
            else:
                break
            if prior_hits >= persistence - 1:
                break
        effective_status = raw_status if raw_status != "NORMAL" and prior_hits >= persistence - 1 else "NORMAL"
        results[metric] = {
            "metric": metric, "current": current, "warning": warning, "critical": critical,
            "raw_status": raw_status, "effective_status": effective_status,
            "consecutive_hits": prior_hits + (1 if raw_status != "NORMAL" else 0),
        }
    return {"status": highest_status([item["effective_status"] for item in results.values()]), "metrics": results}
