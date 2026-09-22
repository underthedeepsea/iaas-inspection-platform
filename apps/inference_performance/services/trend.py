from __future__ import annotations

from datetime import timedelta
from statistics import median
from typing import Any

from .fixed import PRIMARY_METRICS, metric_value


def evaluate_trend(*, snapshot, policy: dict[str, Any]) -> dict[str, Any]:
    window_minutes = int(policy.get("trend", {}).get("window_minutes", 60))
    history = list(snapshot.__class__.objects.filter(
        environment=snapshot.environment, engine_id=snapshot.engine_id, engine_type=snapshot.engine_type,
        model_name=snapshot.model_name, window_end__gte=snapshot.window_end - timedelta(minutes=window_minutes),
        window_end__lte=snapshot.window_end,
    ).order_by("window_end", "pk"))
    result: dict[str, Any] = {"status": "NOT_READY", "window_minutes": window_minutes, "sample_count": len(history), "metrics": {}}
    if len(history) < 6:
        return result
    midpoint = len(history) // 2
    first, second = history[:midpoint], history[midpoint:]
    states: list[str] = []
    for metric in PRIMARY_METRICS:
        before = float(median([metric_value(item.metrics, metric) for item in first]))
        after = float(median([metric_value(item.metrics, metric) for item in second]))
        change_ratio = (after - before) / max(before, 1e-9)
        if change_ratio >= float(policy["trend"]["degrading_change_ratio"]):
            status = "DEGRADING"
        elif change_ratio >= float(policy["trend"]["watch_change_ratio"]):
            status = "WATCH"
        else:
            status = "STABLE"
        result["metrics"][metric] = {"metric": metric, "first_half_median": before, "second_half_median": after, "change_ratio": change_ratio, "status": status}
        states.append(status)
    result["status"] = "DEGRADING" if "DEGRADING" in states else "WATCH" if "WATCH" in states else "STABLE"
    return result
