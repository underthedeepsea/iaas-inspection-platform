from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings


@dataclass(frozen=True)
class ResolvedPolicy:
    policy: dict[str, Any]
    level: str
    config_hash: str


def deep_merge(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(parent)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_policy_config() -> dict[str, Any]:
    path = Path(settings.BASE_DIR) / "config" / "inference_performance_policies.json"
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict) or not isinstance(value.get("default"), dict):
        raise ValueError("inference performance policy configuration is invalid")
    return value


def validate_policy(policy: dict[str, Any]) -> None:
    import math
    from .fixed import PRIMARY_METRICS

    fixed = policy.get('fixed')
    if not isinstance(fixed, dict) or any(metric not in fixed for metric in PRIMARY_METRICS):
        raise ValueError('all primary metric thresholds are required')
    for metric in PRIMARY_METRICS:
        thresholds = fixed[metric]
        if not isinstance(thresholds, dict):
            raise ValueError(f'invalid threshold for {metric}')
        warning, critical = thresholds.get('warning'), thresholds.get('critical')
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (warning, critical)):
            raise ValueError(f'invalid threshold for {metric}')
        if not 0 <= warning < critical:
            raise ValueError(f'invalid threshold order for {metric}')
    persistence = (policy.get('persistence') or {}).get('consecutive_hits')
    if isinstance(persistence, bool) or not isinstance(persistence, int) or persistence < 1:
        raise ValueError('consecutive_hits must be a positive integer')
    dynamic = policy.get('dynamic') or {}
    trend = policy.get('trend') or {}
    for section, fields in ((dynamic, ('warning_z', 'critical_z', 'warning_change_ratio', 'critical_change_ratio')),
                            (trend, ('watch_change_ratio', 'degrading_change_ratio'))):
        for field in fields:
            value = section.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'invalid policy parameter {field}')
    window = trend.get('window_minutes')
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError('trend.window_minutes must be positive')
    quality = policy.get('quality') or {}
    for field in ('max_age_seconds', 'max_gap_seconds'):
        value = quality.get(field, 300)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f'quality.{field} must be a positive integer')


def resolve_policy(*, engine_type: str, model_name: str) -> ResolvedPolicy:
    config = load_policy_config()
    policy = deepcopy(config["default"])
    level = "DEFAULT"
    engine_policy = config.get("engines", {}).get(engine_type)
    if isinstance(engine_policy, dict):
        policy = deep_merge(policy, engine_policy)
        level = "ENGINE"
    model_policy = config.get("models", {}).get(engine_type, {}).get(model_name)
    if isinstance(model_policy, dict) and model_policy:
        policy = deep_merge(policy, model_policy)
        level = "ENGINE_MODEL"
    validate_policy(policy)
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ResolvedPolicy(policy=policy, level=level, config_hash=f"sha256:{digest}")
