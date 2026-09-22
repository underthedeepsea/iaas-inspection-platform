from datetime import datetime, timedelta, timezone


def sample(sample_id="sample-1", end=None, *, ttft_p95=300, qps=5, waiting=1):
    end = end or datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    return {
        "sample_id": sample_id,
        "window_start": (end - timedelta(minutes=1)).isoformat(),
        "window_end": end.isoformat(),
        "ttft": {"avg_ms": 100, "p90_ms": 200, "p95_ms": ttft_p95, "p99_ms": ttft_p95 + 100, "e2e_ratio": 0.2},
        "tpot": {"avg_ms": 10, "p90_ms": 15, "p95_ms": 20, "p99_ms": 30},
        "e2e": {"avg_ms": 1000, "p90_ms": 1500, "p95_ms": 2000, "p99_ms": 2500},
        "traffic": {"qps": qps, "qpm": qps * 60},
        "throughput": {"generation_tps": 1000, "prompt_tps": 2000},
        "cache": {"kv_cache_hit_rate": 0.6},
        "requests": {"running": 3, "waiting": waiting},
    }


def payload(environment_id, *, sample_id="sample-1", end=None, ttft_p95=300, qps=5, waiting=1):
    return {
        "source": "inference-monitor", "environment_id": environment_id,
        "engine": {"engine_id": "qwen-prod-1", "engine_type": "vllm", "model_name": "Qwen/Qwen3-32B"},
        "sample": sample(sample_id, end, ttft_p95=ttft_p95, qps=qps, waiting=waiting),
    }
