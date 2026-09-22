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
    digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ResolvedPolicy(policy=policy, level=level, config_hash=f"sha256:{digest}")
