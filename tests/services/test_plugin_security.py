import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

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


def test_exec_cannot_execute_a_write_capability_for_a_code_origin_before_dispatch():
    from services.plugin_runtime.executor import (
        ExecutionOrigin,
        PluginExecutor,
        ReadOnlyCapabilityError,
    )

    class MustNotRun:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("backend must not be dispatched")

    executor = PluginExecutor(exec_executor=MustNotRun())

    with pytest.raises(ReadOnlyCapabilityError, match="read-only"):
        executor.execute(
            capability_version(implementation_type="EXEC", read_only=False),
            {},
            origin=ExecutionOrigin.CODE,
        )


def test_exec_direct_boundary_rejects_a_write_capability():
    from services.plugin_runtime.exec_executor import ExecExecutor, ReadOnlyCapabilityError

    with pytest.raises(ReadOnlyCapabilityError, match="read-only"):
        ExecExecutor().execute(
            capability_version(implementation_type="EXEC", read_only=False),
            {},
        )


@pytest.mark.parametrize("origin", ["llm", "unknown", object()])
def test_unknown_execution_origin_is_rejected_before_dispatch(origin):
    from services.plugin_runtime.executor import InvalidExecutionOriginError, PluginExecutor

    class MustNotRun:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("backend must not be dispatched")

    with pytest.raises(InvalidExecutionOriginError, match="origin"):
        PluginExecutor(rule_executor=MustNotRun()).execute(
            capability_version(),
            {},
            origin=origin,
        )


def test_typed_execution_origin_is_accepted():
    from services.plugin_runtime.executor import ExecutionOrigin, PluginExecutor

    class Returns:
        def execute(self, *_args, **_kwargs):
            return {"ok": True}

    assert PluginExecutor(rule_executor=Returns()).execute(
        capability_version(), {}, origin=ExecutionOrigin.CODE
    ) == {"ok": True}


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


def test_exec_success_uses_argv_without_a_shell_and_returns_json(tmp_path, monkeypatch):
    from services.plugin_runtime.exec_executor import ExecExecutor

    allowlist = tmp_path / "plugins" / "exec"
    allowlist.mkdir(parents=True)
    script = allowlist / "safe.py"
    script.write_text("print('{}')")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"result": "ok"}'))
    monkeypatch.setattr("services.plugin_runtime.exec_executor.subprocess.run", run)
    payload = {"entity_id": "host-1", "quoted": "$(touch /tmp/pwned)"}

    result = ExecExecutor(allowlist=allowlist).execute(
        capability_version(implementation_type="EXEC", script_path=script),
        payload,
    )

    assert result == {"result": "ok"}
    assert run.call_args.args[0] == [sys.executable, str(script), json.dumps(payload)]
    assert run.call_args.kwargs["shell"] is False


def test_exec_timeout_is_a_domain_error(tmp_path, monkeypatch):
    from services.plugin_runtime.exec_executor import ExecExecutionError, ExecExecutor

    allowlist = tmp_path / "plugins" / "exec"
    allowlist.mkdir(parents=True)
    script = allowlist / "timeout.py"
    script.write_text("print('{}')")
    monkeypatch.setattr(
        "services.plugin_runtime.exec_executor.subprocess.run",
        Mock(side_effect=subprocess.TimeoutExpired([sys.executable, str(script)], 1)),
    )

    with pytest.raises(ExecExecutionError, match="timed out"):
        ExecExecutor(allowlist=allowlist).execute(
            capability_version(implementation_type="EXEC", script_path=script),
            {},
        )


def test_exec_nonzero_exit_is_a_domain_error(tmp_path, monkeypatch):
    from services.plugin_runtime.exec_executor import ExecExecutionError, ExecExecutor

    allowlist = tmp_path / "plugins" / "exec"
    allowlist.mkdir(parents=True)
    script = allowlist / "failure.py"
    script.write_text("print('{}')")
    monkeypatch.setattr(
        "services.plugin_runtime.exec_executor.subprocess.run",
        Mock(return_value=SimpleNamespace(returncode=7, stdout="{}")),
    )

    with pytest.raises(ExecExecutionError, match="status 7"):
        ExecExecutor(allowlist=allowlist).execute(
            capability_version(implementation_type="EXEC", script_path=script),
            {},
        )


def test_exec_malformed_stdout_is_a_domain_error(tmp_path, monkeypatch):
    from services.plugin_runtime.exec_executor import ExecExecutionError, ExecExecutor

    allowlist = tmp_path / "plugins" / "exec"
    allowlist.mkdir(parents=True)
    script = allowlist / "malformed.py"
    script.write_text("print('{}')")
    monkeypatch.setattr(
        "services.plugin_runtime.exec_executor.subprocess.run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout="not-json")),
    )

    with pytest.raises(ExecExecutionError, match="must be JSON"):
        ExecExecutor(allowlist=allowlist).execute(
            capability_version(implementation_type="EXEC", script_path=script),
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


@pytest.mark.parametrize("schema", [{"type": "not-a-json-schema-type"}, None])
def test_invalid_stored_json_schema_is_a_validation_domain_error(schema):
    from services.plugin_runtime.executor import InputValidationError, PluginExecutor

    version = capability_version(input_schema=schema)

    with pytest.raises(InputValidationError, match="input schema"):
        PluginExecutor().execute(version, {})


def test_rest_rejects_a_hostname_that_only_looks_like_a_local_prefix():
    from services.plugin_runtime.rest_executor import RestExecutionError, RestExecutor

    with pytest.raises(RestExecutionError, match="outside"):
        RestExecutor().execute(
            capability_version(implementation_type="REST", endpoint="http://localhost.evil/"),
            {},
        )


def test_rest_default_authority_rejects_a_non_default_port():
    from services.plugin_runtime.rest_executor import RestExecutor

    assert not RestExecutor._is_allowed(
        "http://localhost:8080/health",
        "http://localhost",
    )


def test_rest_explicit_port_is_compared_with_the_effective_port():
    from services.plugin_runtime.rest_executor import RestExecutor

    assert RestExecutor._is_allowed("http://localhost:8080/health", "http://localhost:8080")
    assert not RestExecutor._is_allowed("http://localhost:8081/health", "http://localhost:8080")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost/allowed/../secret",
        "http://localhost/allowed/%2e%2e/secret",
        "http://localhost/allowed/%2fsecret",
        "http://localhost/allowed/%5csecret",
        "http://localhost/allowed/%252e%252e/secret",
    ],
)
def test_rest_rejects_raw_or_encoded_path_escape_segments(endpoint):
    from services.plugin_runtime.rest_executor import RestExecutor

    assert not RestExecutor._is_allowed(endpoint, "http://localhost/allowed")


def test_rest_malformed_port_is_normalized_to_a_domain_error():
    from services.plugin_runtime.rest_executor import RestExecutionError, RestExecutor

    with pytest.raises(RestExecutionError, match="outside"):
        RestExecutor(allowed_prefixes=("http://localhost",)).execute(
            capability_version(implementation_type="REST", endpoint="http://localhost:not-a-port/"),
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
