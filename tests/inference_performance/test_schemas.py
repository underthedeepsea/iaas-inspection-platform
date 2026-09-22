import copy

import pytest

from apps.api.http import APIRequestError
from apps.inference_performance.schemas import parse_snapshot_request
from .helpers import payload


def test_accepts_complete_finite_snapshot():
    parsed = parse_snapshot_request(payload("prod-a"))
    assert parsed.engine.engine_type == "vllm"
    assert parsed.sample.metrics["ttft"]["p95_ms"] == 300


@pytest.mark.parametrize(
    ("path", "value"),
    [("sample.ttft.p95_ms", -1), ("sample.cache.kv_cache_hit_rate", 1.1), ("sample.ttft.e2e_ratio", 1.1)],
)
def test_rejects_out_of_range_metrics(path, value):
    raw = payload("prod-a")
    target = raw
    pieces = path.split(".")
    for piece in pieces[:-1]:
        target = target[piece]
    target[pieces[-1]] = value
    with pytest.raises(APIRequestError):
        parse_snapshot_request(raw)


def test_rejects_invalid_percentile_order_and_naive_timestamp():
    raw = payload("prod-a")
    raw["sample"]["ttft"]["p90_ms"] = 400
    with pytest.raises(APIRequestError):
        parse_snapshot_request(raw)
    raw = payload("prod-a")
    raw["sample"]["window_start"] = "2026-09-22T08:00:00"
    with pytest.raises(APIRequestError):
        parse_snapshot_request(raw)


def test_rejects_unknown_engine_type():
    raw = payload("prod-a")
    raw["engine"]["engine_type"] = "triton"
    with pytest.raises(APIRequestError):
        parse_snapshot_request(raw)


def test_rejects_integer_too_large_for_float_conversion():
    raw = payload("prod-a")
    raw["sample"]["ttft"]["avg_ms"] = 10 ** 400
    with pytest.raises(APIRequestError) as error:
        parse_snapshot_request(raw)
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details == {"field": "ttft.avg_ms"}
