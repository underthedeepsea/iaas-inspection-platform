from apps.inference_performance.services.policy import deep_merge, resolve_policy


def test_policy_model_override_inherits_default_and_has_stable_hash():
    resolved = resolve_policy(engine_type="vllm", model_name="Qwen/Qwen3-32B")
    repeated = resolve_policy(engine_type="vllm", model_name="Qwen/Qwen3-32B")
    assert resolved.level == "ENGINE_MODEL"
    assert resolved.policy["fixed"]["ttft.p95_ms"] == {"warning": 500, "critical": 900}
    assert resolved.policy["fixed"]["e2e.p95_ms"]["warning"] == 10000
    assert resolved.config_hash == repeated.config_hash


def test_policy_default_and_recursive_merge():
    resolved = resolve_policy(engine_type="sglang", model_name="unknown")
    assert resolved.level == "ENGINE"
    assert resolved.policy["fixed"]["ttft.p95_ms"]["warning"] == 800
    assert deep_merge({"fixed": {"a": 1, "b": 2}}, {"fixed": {"a": 3}}) == {"fixed": {"a": 3, "b": 2}}
