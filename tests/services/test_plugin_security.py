from types import SimpleNamespace

import pytest


def capability_version(*, implementation_type="RULE", read_only=True, **values):
    capability = SimpleNamespace(read_only=read_only)
    defaults = {
        "capability": capability,
        "implementation_type": implementation_type,
        "input_schema": {"type": "object"},
        "output_schema": {},
        "manifest": {},
        "script_path": None,
        "endpoint": None,
        "timeout_seconds": 1,
    }
    return SimpleNamespace(**(defaults | values))


def test_llm_cannot_execute_a_write_capability_before_dispatch():
    from services.plugin_runtime.executor import PluginExecutor, ReadOnlyCapabilityError

    class MustNotRun:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("backend must not be dispatched")

    executor = PluginExecutor(rule_executor=MustNotRun())

    with pytest.raises(ReadOnlyCapabilityError, match="read-only"):
        executor.execute(capability_version(read_only=False), {}, llm=True)


def test_exec_rejects_a_script_outside_the_allowlist():
    from services.plugin_runtime.exec_executor import ExecExecutor, UnsafeScriptPathError

    version = capability_version(
        implementation_type="EXEC",
        script_path="plugins/not-allowed.py",
    )

    with pytest.raises(UnsafeScriptPathError, match="allowlist"):
        ExecExecutor().execute(version, {})


def test_exec_rejects_a_symlink_that_escapes_the_allowlist(tmp_path):
    from services.plugin_runtime.exec_executor import ExecExecutor, UnsafeScriptPathError

    allowlist = tmp_path / "plugins" / "exec"
    allowlist.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("print('{}')")
    escaped = allowlist / "escaped.py"
    escaped.symlink_to(outside)

    with pytest.raises(UnsafeScriptPathError, match="allowlist"):
        ExecExecutor(allowlist=allowlist).execute(
            capability_version(implementation_type="EXEC", script_path=escaped),
            {},
        )


def test_exec_rejects_traversal_even_when_it_resolves_back_into_the_allowlist(tmp_path):
    from services.plugin_runtime.exec_executor import ExecExecutor, UnsafeScriptPathError

    allowlist = tmp_path / "plugins" / "exec"
    allowlist.mkdir(parents=True)
    script = allowlist / "safe.py"
    script.write_text("print('{}')")

    with pytest.raises(UnsafeScriptPathError, match="traversal"):
        ExecExecutor(allowlist=allowlist).execute(
            capability_version(
                implementation_type="EXEC",
                script_path=allowlist / ".." / "exec" / "safe.py",
            ),
            {},
        )


def test_input_that_violates_the_stored_json_schema_is_rejected_before_dispatch():
    from services.plugin_runtime.executor import InputValidationError, PluginExecutor

    version = capability_version(
        input_schema={
            "type": "object",
            "required": ["entity_id"],
            "properties": {"entity_id": {"type": "string"}},
        }
    )

    with pytest.raises(InputValidationError, match="input schema"):
        PluginExecutor().execute(version, {"entity_id": 42})


def test_rest_rejects_a_hostname_that_only_looks_like_a_local_prefix():
    from services.plugin_runtime.rest_executor import RestExecutionError, RestExecutor

    with pytest.raises(RestExecutionError, match="outside"):
        RestExecutor().execute(
            capability_version(implementation_type="REST", endpoint="http://localhost.evil/"),
            {},
        )


def test_rule_executor_returns_the_deterministic_manifest_result_when_all_conditions_match():
    from services.plugin_runtime.executor import PluginExecutor

    version = capability_version(
        manifest={
            "rule": {
                "all": [
                    {"field": "packet_loss", "equals": True},
                    {"field": "softirq", "equals": "SURGE"},
                ],
                "result": "RX_PATH_PRESSURE",
            }
        },
    )

    assert PluginExecutor().execute(
        version,
        {"packet_loss": True, "softirq": "SURGE"},
    ) == {"matched": True, "result": "RX_PATH_PRESSURE"}
