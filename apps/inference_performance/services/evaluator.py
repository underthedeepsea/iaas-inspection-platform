from __future__ import annotations

from typing import Any

from .baseline import build_baseline, evaluate_dynamic
from .fixed import STATUS_RANK, evaluate_fixed
from .policy import resolve_policy
from .trend import evaluate_trend


def _metric_code(metric: str) -> str:
    return {
        "requests.waiting": "WAITING_REQUESTS",
    }.get(metric, metric.replace(".", "_").replace("_ms", "").upper())


def _reasons(fixed: dict[str, Any], dynamic: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    for metric, item in fixed.get("metrics", {}).items():
        if item["effective_status"] in {"WARNING", "CRITICAL"}:
            threshold = item["critical"] if item["effective_status"] == "CRITICAL" else item["warning"]
            reasons.append({
                "code": f"{_metric_code(metric)}_FIXED_HIGH", "metric": metric, "status": item["effective_status"],
                "current": item["current"], "threshold": threshold,
            })
    for metric, item in dynamic.get("metrics", {}).items():
        if item["contributes_to_status"] and item["status"] in {"WARNING", "CRITICAL"}:
            boundary = item["critical"] if item["status"] == "CRITICAL" else item["warning"]
            reasons.append({
                "code": f"{_metric_code(metric)}_DYNAMIC_HIGH", "metric": metric, "status": item["status"],
                "current": item["current"], "baseline_median": item["baseline_median"],
                "boundary": boundary, "change_ratio": item["change_ratio"],
            })
    return reasons


def _overall_status(fixed: dict[str, Any], dynamic: dict[str, Any]) -> str:
    statuses = [fixed.get("status", "NORMAL")]
    if dynamic.get("status") != "NOT_READY":
        statuses.append(dynamic.get("status", "NORMAL"))
    return max(statuses, key=lambda status: STATUS_RANK[status])


def evaluate_snapshot(snapshot) -> dict[str, Any]:
    resolved = resolve_policy(engine_type=snapshot.engine_type, model_name=snapshot.model_name)
    persistence = max(1, int(resolved.policy.get("persistence", {}).get("consecutive_hits", 2)))
    previous_metrics = list(
        snapshot.__class__.objects.filter(
            environment=snapshot.environment, engine_id=snapshot.engine_id, engine_type=snapshot.engine_type,
            model_name=snapshot.model_name, window_end__lt=snapshot.window_end,
        ).order_by("-window_end", "-pk").values_list("metrics", flat=True)[:persistence - 1]
    )
    fixed = evaluate_fixed(current_metrics=snapshot.metrics, policy=resolved.policy, previous_metrics=previous_metrics)
    baseline = build_baseline(snapshot=snapshot)
    dynamic = evaluate_dynamic(current_metrics=snapshot.metrics, baseline=baseline, policy=resolved.policy)
    trend = evaluate_trend(snapshot=snapshot, policy=resolved.policy)
    return {
        "status": _overall_status(fixed, dynamic), "fixed": fixed, "dynamic": dynamic, "trend": trend,
        "policy_source": {"level": resolved.level, "config_hash": resolved.config_hash},
        "reasons": _reasons(fixed, dynamic),
    }
