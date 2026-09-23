from __future__ import annotations

import os
import re
from typing import Any

from django.conf import settings

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


def _deployment_commit() -> str | None:
    """Read an explicit deployment identity; never infer it from the current checkout."""
    candidate = getattr(settings, 'DEPLOY_COMMIT_SHA', None) or os.environ.get('DEPLOY_COMMIT_SHA')
    if isinstance(candidate, str) and re.fullmatch(r'[0-9a-fA-F]{40}', candidate):
        return candidate.lower()
    return None


def evaluate_snapshot(snapshot, *, resolved_policy=None) -> dict[str, Any]:
    resolved = resolved_policy or resolve_policy(engine_type=snapshot.engine_type, model_name=snapshot.model_name)
    persistence = max(1, int(resolved.policy.get("persistence", {}).get("consecutive_hits", 2)))
    previous = list(
        snapshot.__class__.objects.filter(
            environment=snapshot.environment, engine_id=snapshot.engine_id, engine_type=snapshot.engine_type,
            model_name=snapshot.model_name, window_end__lt=snapshot.window_end,
        ).order_by("-window_end", "-pk").values("metrics", "window_start", "window_end")[:persistence - 1]
    )
    fixed = evaluate_fixed(current_metrics=snapshot.metrics, policy=resolved.policy, previous_metrics=previous,
                           current_window=(snapshot.window_start, snapshot.window_end))
    baseline = build_baseline(snapshot=snapshot)
    dynamic = evaluate_dynamic(current_metrics=snapshot.metrics, baseline=baseline, policy=resolved.policy)
    trend = evaluate_trend(snapshot=snapshot, policy=resolved.policy)
    idle = all(metric_value == 0 for metric_value in (
        snapshot.metrics['traffic']['qps'], snapshot.metrics['requests']['running'],
        snapshot.metrics['requests']['waiting'], snapshot.metrics['throughput']['generation_tps'],
        snapshot.metrics['throughput']['prompt_tps'],
    ))
    pending = any(item['raw_status'] != 'NORMAL' and item['effective_status'] == 'NORMAL' for item in fixed['metrics'].values())
    plugin = {"id": "inference-performance", "version": "1.0.0", "rule_code": "llm.performance_profile", "operation": "evaluate"}
    deployment_commit = _deployment_commit()
    if deployment_commit is not None:
        plugin['deployment_commit'] = deployment_commit
    return {
        "schema_version": 1,
        "plugin": plugin,
        "input": {"snapshot_id": str(snapshot.pk), "window_start": snapshot.window_start.isoformat(), "window_end": snapshot.window_end.isoformat()},
        "resolved_policy": resolved.policy,
        "quality": {"state": "IDLE" if idle else "READY", "pending_confirmation": pending},
        "status": _overall_status(fixed, dynamic), "fixed": fixed, "dynamic": dynamic, "trend": trend,
        "policy_source": {"level": resolved.level, "config_hash": resolved.config_hash},
        "reasons": _reasons(fixed, dynamic),
    }
