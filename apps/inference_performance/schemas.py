"""Strict, dependency-free validation for external performance snapshots."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apps.api.http import APIRequestError, parse_bool

ENGINE_TYPES = frozenset({"vllm", "sglang"})
PERCENTILE_GROUPS = ("ttft", "tpot", "e2e")
METRIC_FIELDS = {
    "ttft": ("avg_ms", "p90_ms", "p95_ms", "p99_ms", "e2e_ratio"),
    "tpot": ("avg_ms", "p90_ms", "p95_ms", "p99_ms"),
    "e2e": ("avg_ms", "p90_ms", "p95_ms", "p99_ms"),
    "traffic": ("qps", "qpm"),
    "throughput": ("generation_tps", "prompt_tps"),
    "cache": ("kv_cache_hit_rate",),
    "requests": ("running", "waiting"),
}


@dataclass(frozen=True)
class EngineIdentity:
    engine_id: str
    engine_type: str
    model_name: str


@dataclass(frozen=True)
class PerformanceSample:
    sample_id: str
    window_start: datetime
    window_end: datetime
    metrics: dict[str, dict[str, float]]


@dataclass(frozen=True)
class SnapshotRequest:
    source: str
    environment_id: str
    engine: EngineIdentity
    sample: PerformanceSample


@dataclass(frozen=True)
class BatchSnapshotRequest:
    source: str
    environment_id: str
    engine: EngineIdentity
    samples: tuple[PerformanceSample, ...]
    evaluate_latest: bool


def _error(message: str, field: str) -> None:
    raise APIRequestError("VALIDATION_ERROR", message, details={"field": field})


def _object(value: Any, field: str, *, exact: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error(f"{field} must be an object", field)
    if exact is not None:
        unknown = sorted(set(value) - exact)
        missing = sorted(exact - set(value))
        if unknown or missing:
            _error(f"{field} must contain the supported fields exactly", field)
    return value


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _error(f"{field} must be a non-empty string no longer than {maximum} characters", field)
    return value.strip()


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(f"{field} must be a finite number", field)
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _error(f"{field} must be a finite number", field)
    if not math.isfinite(result):
        _error(f"{field} must be a finite number", field)
    if result < 0:
        _error(f"{field} must not be negative", field)
    return result


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        _error(f"{field} must be an ISO-8601 timestamp with timezone", field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _error(f"{field} must be an ISO-8601 timestamp with timezone", field)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _error(f"{field} must include timezone", field)
    return parsed


def parse_engine(value: Any) -> EngineIdentity:
    raw = _object(value, "engine", exact={"engine_id", "engine_type", "model_name"})
    engine_type = _text(raw["engine_type"], "engine.engine_type", 32).lower()
    if engine_type not in ENGINE_TYPES:
        _error("engine.engine_type must be vllm or sglang", "engine.engine_type")
    return EngineIdentity(
        engine_id=_text(raw["engine_id"], "engine.engine_id", 192),
        engine_type=engine_type,
        model_name=_text(raw["model_name"], "engine.model_name", 256),
    )


def parse_sample(value: Any) -> PerformanceSample:
    raw = _object(value, "sample", exact={"sample_id", "window_start", "window_end", *METRIC_FIELDS})
    metrics: dict[str, dict[str, float]] = {}
    for group, names in METRIC_FIELDS.items():
        nested = _object(raw[group], group, exact=set(names))
        metrics[group] = {name: _number(nested[name], f"{group}.{name}") for name in names}
    for group in PERCENTILE_GROUPS:
        values = metrics[group]
        if not values["p90_ms"] <= values["p95_ms"] <= values["p99_ms"]:
            _error(f"{group} percentiles must satisfy p90_ms <= p95_ms <= p99_ms", group)
    if metrics["cache"]["kv_cache_hit_rate"] > 1:
        _error("cache.kv_cache_hit_rate must be between 0 and 1", "cache.kv_cache_hit_rate")
    if metrics["ttft"]["e2e_ratio"] > 1:
        _error("ttft.e2e_ratio must be between 0 and 1", "ttft.e2e_ratio")
    window_start = _timestamp(raw["window_start"], "sample.window_start")
    window_end = _timestamp(raw["window_end"], "sample.window_end")
    if window_start >= window_end:
        _error("sample.window_start must be before sample.window_end", "sample.window_start")
    return PerformanceSample(
        sample_id=_text(raw["sample_id"], "sample.sample_id", 192),
        window_start=window_start,
        window_end=window_end,
        metrics=metrics,
    )


def parse_snapshot_request(payload: Any) -> SnapshotRequest:
    raw = _object(payload, "request", exact={"source", "environment_id", "engine", "sample"})
    return SnapshotRequest(
        source=_text(raw["source"], "source", 64),
        environment_id=_text(raw["environment_id"], "environment_id", 128),
        engine=parse_engine(raw["engine"]),
        sample=parse_sample(raw["sample"]),
    )


def parse_batch_snapshot_request(payload: Any) -> BatchSnapshotRequest:
    raw = _object(payload, "request", exact={"source", "environment_id", "engine", "samples", "evaluate_latest"})
    samples = raw["samples"]
    if not isinstance(samples, list) or not 1 <= len(samples) <= 500:
        _error("samples must contain between 1 and 500 snapshots", "samples")
    parsed_samples = tuple(parse_sample(sample) for sample in samples)
    sample_ids = [sample.sample_id for sample in parsed_samples]
    if len(sample_ids) != len(set(sample_ids)):
        _error("samples must not repeat sample_id in one batch", "samples")
    return BatchSnapshotRequest(
        source=_text(raw["source"], "source", 64),
        environment_id=_text(raw["environment_id"], "environment_id", 128),
        engine=parse_engine(raw["engine"]),
        samples=parsed_samples,
        evaluate_latest=parse_bool(raw["evaluate_latest"]),
    )
