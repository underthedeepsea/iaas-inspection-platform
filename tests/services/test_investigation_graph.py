import json
from copy import deepcopy
from types import SimpleNamespace

import pytest


class FakeGateway:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    def invoke(self, request):
        self.calls.append(request)
        if not self.actions:
            raise AssertionError("fake gateway was called more times than expected")
        return self.actions.pop(0)


class FakeRegistry:
    def __init__(self, version=None):
        self.version = version
        self.calls = []

    def resolve_capability(self, capability_id, *, claim=None):
        self.calls.append((capability_id, claim))
        if self.version is not None and capability_id == self.version.capability.capability_id:
            return self.version
        return None

    def execute_readonly(self, capability_id, *, claim, payload, executor, origin):
        from services.plugin_runtime.errors import PluginExecutionError

        if self.version is None or capability_id != self.version.capability.capability_id:
            raise PluginExecutionError("capability unavailable")
        return self.version, executor.execute(self.version, payload, origin=origin)


class AtomicRegistry(FakeRegistry):
    def __init__(self, version=None, *, fail=False):
        super().__init__(version)
        self.atomic_calls = []
        self.fail = fail

    def execute_readonly(self, capability_id, *, claim, payload, executor, origin):
        self.atomic_calls.append((capability_id, claim, payload, origin))
        if self.fail:
            from services.plugin_runtime.errors import ReadOnlyCapabilityError

            raise ReadOnlyCapabilityError("capability changed")
        return self.version, executor.execute(self.version, payload, origin=origin)


class BareResultRegistry(FakeRegistry):
    def execute_readonly(self, capability_id, *, claim, payload, executor, origin):
        return {"scheduler_queue_ratio": 2.15}


class NoneVersionRegistry(FakeRegistry):
    def execute_readonly(self, capability_id, *, claim, payload, executor, origin):
        return None, {"scheduler_queue_ratio": 2.15}


class FakeExecutor:
    def __init__(self, result=None):
        self.result = result or {"scheduler_queue_ratio": 2.15}
        self.calls = []

    def execute(self, capability_version, payload, *, origin=None):
        self.calls.append((capability_version, payload, origin))
        return self.result


class RaisingGateway:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def invoke(self, request):
        self.calls += 1
        raise self.error


def final_action(summary="healthy", confidence=0.9):
    from services.model_gateway.base import FinalAction

    return FinalAction(summary=summary, confidence=confidence)


def call_tool_action(capability_id="llm.scheduler.pressure", arguments=None):
    from services.model_gateway.base import CallToolAction

    return CallToolAction(
        capability_id=capability_id,
        arguments=arguments or {"asset_id": "llm-0"},
        reason="confirm scheduler pressure",
    )


def active_readonly_version(*, capability_id="llm.scheduler.pressure", claim="degradation_category"):
    capability = SimpleNamespace(
        capability_id=capability_id,
        status="ACTIVE",
        read_only=True,
    )
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000012",
        capability=capability,
        status="ACTIVE",
        resolves=[claim],
        input_schema={
            "type": "object",
            "required": ["asset_id"],
            "properties": {"asset_id": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["scheduler_queue_ratio"],
            "properties": {"scheduler_queue_ratio": {"type": "number"}},
        },
        implementation_type="RULE",
    )


def run_graph(gateway, *, registry=None, executor=None, **values):
    from services.investigation_graph.graph import build_investigation_graph

    graph = build_investigation_graph(
        gateway=gateway,
        registry=registry or FakeRegistry(),
        executor=executor or FakeExecutor(),
        **values,
    )
    return graph.invoke(
        {
            "question": "Why is TTFT increasing?",
            "context": {"missing_claim": "degradation_category"},
            "missing_claim": "degradation_category",
        }
    )


def run_graph_without_claim(gateway, *, registry=None, executor=None, **values):
    from services.investigation_graph.graph import build_investigation_graph

    graph = build_investigation_graph(
        gateway=gateway,
        registry=registry or FakeRegistry(),
        executor=executor or FakeExecutor(),
        **values,
    )
    return graph.invoke({"question": "Why is TTFT increasing?", "context": {}})


def test_direct_final_has_zero_tool_calls_and_stable_final_shape():
    gateway = FakeGateway([final_action("queue is healthy")])
    executor = FakeExecutor()

    result = run_graph(gateway, executor=executor)

    assert executor.calls == []
    assert result["tool_calls_used"] == 0
    assert result["status"] == "RESOLVED"
    assert result["summary"] == "queue is healthy"
    assert result["conclusion"] == "queue is healthy"
    assert isinstance(result["facts"], list)
    assert isinstance(result["next_steps"], list)
    assert result["final"]["summary"] == "queue is healthy"


def test_claim_gap_calls_only_active_readonly_capability_and_compacts_evidence():
    gateway = FakeGateway([call_tool_action(), final_action("scheduler pressure confirmed")])
    version = active_readonly_version()
    registry = FakeRegistry(version)
    executor = FakeExecutor(
        {
            "scheduler_queue_ratio": 2.15,
            "provider_url": "https://user:secret@provider.invalid",
            "raw_payload": {"password": "do-not-leak"},
        }
    )

    result = run_graph(gateway, registry=registry, executor=executor)

    assert len(registry.calls) >= 1
    assert len(executor.calls) == 1
    assert executor.calls[0][1] == {"asset_id": "llm-0"}
    assert getattr(executor.calls[0][2], "value", executor.calls[0][2]) == "LLM"
    evidence = result["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["source"] == "llm.scheduler.pressure"
    assert evidence[0]["payload"] == {"scheduler_queue_ratio": 2.15}
    assert result["summary"] == "scheduler pressure confirmed"


def test_claim_gap_rejects_write_capability_before_executor_dispatch():
    gateway = FakeGateway([call_tool_action(), final_action("cannot verify")])
    version = active_readonly_version()
    version.capability.read_only = False
    registry = FakeRegistry(version)
    executor = FakeExecutor()

    result = run_graph(gateway, registry=registry, executor=executor)

    assert executor.calls == []
    assert result["status"] == "UNRESOLVED"
    assert result["tool_calls_used"] == 0
    assert result["next_steps"]


def test_max_rounds_is_a_hard_ceiling_and_stops_deterministically():
    gateway = FakeGateway([call_tool_action()] * 10)
    version = active_readonly_version()
    executor = FakeExecutor()

    result = run_graph(
        gateway,
        registry=FakeRegistry(version),
        executor=executor,
        max_rounds=3,
        max_tool_calls=50,
    )

    assert len(gateway.calls) == 3
    assert len(executor.calls) == 3
    assert result["rounds_used"] == 3
    assert result["tool_calls_used"] == 3
    assert result["status"] == "UNRESOLVED"
    assert set(("summary", "conclusion", "facts", "next_steps")) <= result.keys()


def test_max_tool_calls_is_a_hard_ceiling_even_when_round_budget_is_larger():
    gateway = FakeGateway([call_tool_action()] * 10)
    version = active_readonly_version()
    executor = FakeExecutor()

    result = run_graph(
        gateway,
        registry=FakeRegistry(version),
        executor=executor,
        max_rounds=8,
        max_tool_calls=5,
    )

    assert len(gateway.calls) == 5
    assert len(executor.calls) == 5
    assert result["rounds_used"] == 5
    assert result["tool_calls_used"] == 5
    assert result["status"] == "UNRESOLVED"
    assert isinstance(result["summary"], str)
    assert isinstance(result["conclusion"], str)
    assert isinstance(result["facts"], list)
    assert isinstance(result["next_steps"], list)


@pytest.mark.parametrize(
    "read_only,status",
    [(True, "DISABLED"), (True, "RETIRED"), (False, "ACTIVE")],
)
def test_claim_gap_rejects_inactive_or_non_readonly_capability(read_only, status):
    gateway = FakeGateway([call_tool_action()])
    version = active_readonly_version()
    version.status = status
    version.capability.read_only = read_only
    executor = FakeExecutor()

    result = run_graph(
        gateway,
        registry=FakeRegistry(version),
        executor=executor,
    )

    assert executor.calls == []
    assert result["status"] == "UNRESOLVED"


def test_invalid_tool_output_never_becomes_evidence_or_crashes_graph():
    gateway = FakeGateway([call_tool_action(), final_action("tool returned no usable evidence")])
    version = active_readonly_version()
    version.output_schema = {}
    executor = FakeExecutor(object())

    result = run_graph(
        gateway,
        registry=FakeRegistry(version),
        executor=executor,
    )

    assert result["status"] == "UNRESOLVED"
    assert result["evidence"] == []
    assert isinstance(result["summary"], str)
    assert isinstance(result["conclusion"], str)


def test_model_tool_arguments_are_bounded_before_state_and_execution():
    gateway = FakeGateway(
        [
            call_tool_action(
                arguments={
                    "asset_id": "llm-0",
                    "provider_url": "https://user:secret@provider.invalid",
                    "password": "do-not-leak",
                }
            ),
            final_action("evidence collected"),
        ]
    )
    version = active_readonly_version()
    executor = FakeExecutor()

    result = run_graph(
        gateway,
        registry=FakeRegistry(version),
        executor=executor,
    )

    assert executor.calls[0][1] == {"asset_id": "llm-0"}
    assert "secret" not in repr(result)
    assert "provider.invalid" not in repr(result)


def test_counters_are_clamped_and_never_report_over_budget():
    from services.investigation_graph.graph import build_investigation_graph

    gateway = FakeGateway([call_tool_action()])
    version = active_readonly_version()
    executor = FakeExecutor()

    result = build_investigation_graph(
        gateway=gateway,
        registry=FakeRegistry(version),
        executor=executor,
        max_rounds=3,
        max_tool_calls=5,
    ).invoke(
        {
            "question": "Why is TTFT increasing?",
            "context": {"missing_claim": "degradation_category"},
            "missing_claim": "degradation_category",
            "rounds_used": 99,
            "tool_calls_used": 99,
        }
    )

    assert result["rounds_used"] == 3
    assert result["tool_calls_used"] == 5
    assert len(gateway.calls) == 0
    assert executor.calls == []


def test_gateway_failure_still_returns_the_stable_terminal_shape():
    from services.model_gateway.base import LLMUnavailableError

    result = run_graph(RaisingGateway(LLMUnavailableError("secret provider url")))

    assert result["status"] == "FAILED"
    assert result["error_code"] == "LLM_UNAVAILABLE"
    assert all(key in result for key in ("summary", "conclusion", "facts", "next_steps"))
    assert "secret provider url" not in repr(result)


def test_sensitive_key_variants_are_removed_from_evidence_payload():
    gateway = FakeGateway([call_tool_action(), final_action("sanitised")])
    version = active_readonly_version()
    version.output_schema = {
        "type": "object",
        "properties": {"scheduler_queue_ratio": {"type": "number"}},
    }
    executor = FakeExecutor(
        {
            "scheduler_queue_ratio": 2.15,
            "apiKey": "secret-1",
            "api-key": "secret-2",
            "accessKey": "secret-3",
            "id_token": "secret-4",
            "passwd": "secret-5",
            "authorizationHeader": "secret-6",
            "secretValue": "secret-7",
            "unlisted_public_field": "drop-me",
        }
    )

    result = run_graph(gateway, registry=FakeRegistry(version), executor=executor)

    assert result["evidence"][0]["payload"] == {"scheduler_queue_ratio": 2.15}
    assert all(
        secret not in repr(result)
        for secret in ("secret-1", "secret-2", "secret-3", "secret-4", "secret-5", "secret-6", "secret-7", "drop-me")
    )


def test_model_capability_id_is_validated_before_entering_state_or_registry():
    gateway = FakeGateway(
        [call_tool_action("https://user:secret@provider.invalid/tool")]
    )
    registry = FakeRegistry()

    result = run_graph(gateway, registry=registry)

    assert registry.calls == []
    assert result["status"] == "UNRESOLVED"
    assert "secret" not in repr(result)
    assert "provider.invalid" not in repr(result)


def test_call_tool_without_a_canonical_missing_claim_is_rejected_before_resolution():
    gateway = FakeGateway([call_tool_action()])
    registry = FakeRegistry(active_readonly_version())

    result = run_graph_without_claim(gateway, registry=registry)

    assert registry.calls == []
    assert result["status"] == "UNRESOLVED"
    assert result["error_code"] == "MISSING_CLAIM_REQUIRED"


def test_context_and_evidence_payloads_have_deterministic_serialized_byte_caps():
    huge = {
        f"metric_{index}": {"deep": {"level": {"value": "x" * 800}}}
        for index in range(80)
    }
    gateway = FakeGateway([call_tool_action(), final_action("bounded")])
    version = active_readonly_version()
    version.output_schema = {}
    executor = FakeExecutor(huge)

    from services.investigation_graph.state import MAX_CONTEXT_BYTES, MAX_EVIDENCE_PAYLOAD_BYTES
    from services.investigation_graph.graph import build_investigation_graph

    graph = build_investigation_graph(
        gateway=gateway,
        registry=FakeRegistry(version),
        executor=executor,
    )
    result = graph.invoke(
        {
            "question": "Why?",
            "context": huge,
            "missing_claim": "degradation_category",
        }
    )

    request_context = json.loads(gateway.calls[0].messages[-1]["content"])["context"]
    assert len(json.dumps(request_context, sort_keys=True, ensure_ascii=True).encode()) <= MAX_CONTEXT_BYTES
    payload = result["evidence"][0]["payload"]
    assert len(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()) <= MAX_EVIDENCE_PAYLOAD_BYTES
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_eight_round_eight_tool_budget_terminates_without_recursion_error():
    gateway = FakeGateway([call_tool_action()] * 8)
    version = active_readonly_version()
    executor = FakeExecutor()

    result = run_graph(
        gateway,
        registry=FakeRegistry(version),
        executor=executor,
        max_rounds=8,
        max_tool_calls=8,
    )

    assert result["status"] == "UNRESOLVED"
    assert result["rounds_used"] == 8
    assert result["tool_calls_used"] == 8


def test_tool_history_is_safe_and_available_in_final_handoff():
    gateway = FakeGateway([call_tool_action(), final_action("confirmed")])
    version = active_readonly_version()
    executor = FakeExecutor({"scheduler_queue_ratio": 2.15, "provider_url": "https://secret.invalid"})

    result = run_graph(gateway, registry=FakeRegistry(version), executor=executor)

    assert result["tool_history"][0]["capability_id"] == "llm.scheduler.pressure"
    assert result["tool_history"][0]["status"] == "SUCCEEDED"
    assert result["tool_history"][0]["capability_version_id"] == str(version.id)
    assert result["tool_history"][0]["evidence_key"]
    assert result["final"]["tool_history"] == result["tool_history"]
    assert "secret.invalid" not in repr(result)
    assert "provider_url" not in repr(result)


def test_atomic_registry_rechecks_authorization_before_dispatch():
    gateway = FakeGateway([call_tool_action()])
    version = active_readonly_version()
    registry = AtomicRegistry(version, fail=True)
    executor = FakeExecutor()

    result = run_graph(gateway, registry=registry, executor=executor)

    assert registry.atomic_calls
    assert executor.calls == []
    assert result["status"] == "UNRESOLVED"
    assert result["tool_history"][0]["capability_version_id"] == str(version.id)


def test_input_budgets_derive_recursion_limit_when_config_is_nonempty():
    from services.investigation_graph.graph import build_investigation_graph

    gateway = FakeGateway([call_tool_action()] * 8)
    version = active_readonly_version()
    graph = build_investigation_graph(
        gateway=gateway,
        registry=FakeRegistry(version),
        executor=FakeExecutor(),
    )

    result = graph.invoke(
        {
            "question": "Why?",
            "context": {"missing_claim": "degradation_category"},
            "missing_claim": "degradation_category",
            "max_rounds": 8,
            "max_tool_calls": 8,
        },
        config={"configurable": {"request_id": "round-2"}},
    )

    assert result["status"] == "UNRESOLVED"
    assert result["rounds_used"] == 8
    assert result["tool_calls_used"] == 8


def test_explicit_insufficient_recursion_limit_returns_structured_failure():
    from services.investigation_graph.graph import build_investigation_graph

    gateway = FakeGateway([call_tool_action()] * 8)
    version = active_readonly_version()
    graph = build_investigation_graph(
        gateway=gateway,
        registry=FakeRegistry(version),
        executor=FakeExecutor(),
    )

    try:
        result = graph.invoke(
            {
                "question": "Why?",
                "context": {"missing_claim": "degradation_category"},
                "missing_claim": "degradation_category",
                "max_rounds": 8,
                "max_tool_calls": 8,
            },
            config={"configurable": {"request_id": "round-2"}, "recursion_limit": 1},
        )
    except Exception as exc:
        pytest.fail(f"insufficient recursion_limit must be structured: {exc}")

    assert result["status"] == "UNRESOLVED"
    assert result["error_code"] == "BUDGET_EXHAUSTED"
    assert gateway.calls == []


@pytest.mark.parametrize("registry_type", [BareResultRegistry, NoneVersionRegistry])
def test_atomic_dispatch_requires_version_and_raw_result_tuple(registry_type):
    gateway = FakeGateway([call_tool_action(), final_action("should not run")])
    version = active_readonly_version()
    executor = FakeExecutor()

    result = run_graph(
        gateway,
        registry=registry_type(version),
        executor=executor,
    )

    assert result["status"] == "UNRESOLVED"
    assert result["error_code"] == "ATOMIC_RESULT_INVALID"
    assert result["evidence"] == []


def test_supplied_messages_keep_protocol_context_and_whole_packet_byte_cap():
    from services.investigation_graph.graph import build_investigation_graph
    from services.investigation_graph.state import MAX_CONTEXT_BYTES

    gateway = FakeGateway([final_action("bounded")])
    graph = build_investigation_graph(gateway=gateway)
    raw_log = "raw-log-" + ("x" * 8000)
    context = {
        f"metric_{index}": {"deep": {"value": "x" * 500}}
        for index in range(50)
    }

    result = graph.invoke(
        {
            "question": "Why?",
            "context": context,
            "messages": [{"role": "assistant", "content": raw_log}],
        }
    )

    request_messages = gateway.calls[0].messages
    serialized = json.dumps(request_messages, sort_keys=True, ensure_ascii=True).encode()
    assert len(serialized) <= MAX_CONTEXT_BYTES
    assert request_messages[0]["role"] == "system"
    assert "read-only" in request_messages[0]["content"].lower()
    assert len(request_messages) == 2
    body = json.loads(request_messages[-1]["content"])
    assert isinstance(body["context"], dict)
    assert raw_log not in repr(request_messages)
    assert result["status"] == "RESOLVED"


def test_budget_precheck_closes_selected_history_without_dispatch():
    from services.investigation_graph.nodes import execute_readonly_tool

    version = active_readonly_version()
    executor = FakeExecutor()
    registry = FakeRegistry(version)
    state = {
        "question": "Why?",
        "context": {"missing_claim": "degradation_category"},
        "missing_claim": "degradation_category",
        "max_rounds": 3,
        "max_tool_calls": 1,
        "rounds_used": 1,
        "tool_calls_used": 1,
        "evidence": [],
        "facts": [],
        "next_steps": [],
        "selected_capability": {
            "capability_id": version.capability.capability_id,
            "arguments": {"asset_id": "llm-0"},
            "reason": "confirm scheduler pressure",
            "claim": "degradation_category",
        },
        "tool_history": [
            {
                "capability_id": version.capability.capability_id,
                "arguments": {"asset_id": "llm-0"},
                "reason": "confirm scheduler pressure",
                "status": "SELECTED",
                "outcome": "PENDING",
            }
        ],
    }

    result = execute_readonly_tool(state, registry=registry, executor=executor)

    assert result["status"] == "UNRESOLVED"
    assert result["error_code"] == "BUDGET_EXHAUSTED"
    assert result["tool_history"][0]["status"] == "REJECTED"
    assert result["tool_history"][0]["outcome"] == "BUDGET_EXHAUSTED"
    assert result["tool_history"][0]["error_code"] == "BUDGET_EXHAUSTED"
    assert executor.calls == []


def test_direct_invalid_action_is_round_trip_validated_to_structured_failure():
    from services.model_gateway.base import FinalAction

    result = run_graph(FakeGateway([FinalAction(summary="", confidence=0.9)]))

    assert result["status"] == "FAILED"
    assert result["error_code"] == "STRUCTURED_OUTPUT_INVALID"


def test_low_recursion_limit_normalizes_initial_state_before_budget_final():
    from services.investigation_graph.graph import build_investigation_graph
    from services.investigation_graph.state import MAX_CONTEXT_BYTES, MAX_EVIDENCE_ITEMS

    gateway = FakeGateway([final_action("must not be called")])
    executor = FakeExecutor({"scheduler_queue_ratio": 2.15})
    graph = build_investigation_graph(
        gateway=gateway,
        registry=FakeRegistry(active_readonly_version()),
        executor=executor,
    )
    values = {
        "question": "https://question.invalid/raw?apiKey=question-secret",
        "context": {
            "missing_claim": "degradation_category",
            "apiKey": "context-secret",
            "credential_url": "https://user:password@provider.invalid/api",
            "raw_payload": {"token": "nested-secret"},
            "说明": "巡检上下文" * 2000,
        },
        "missing_claim": "degradation_category",
        "messages": [
            {"role": "user", "content": "raw-log https://log.invalid apiKey=message-secret"},
        ],
        "rounds_used": 99,
        "tool_calls_used": 99,
        "evidence": [
            {
                "evidence_key": f"evidence-{index}",
                "summary": "safe fact",
                "payload": {"metric": index},
                "source": "fake",
                "capability_id": "llm.scheduler.pressure",
            }
            for index in range(99)
        ],
    }
    original = deepcopy(values)

    result = graph.invoke(
        values,
        config={"configurable": {"request_id": "round-3"}, "recursion_limit": 1},
    )

    assert values == original
    assert gateway.calls == []
    assert executor.calls == []
    assert result["status"] == "UNRESOLVED"
    assert result["error_code"] == "BUDGET_EXHAUSTED"
    assert result["rounds_used"] == 3
    assert result["tool_calls_used"] == 5
    assert len(result["evidence"]) <= MAX_EVIDENCE_ITEMS
    assert len(json.dumps(result["context"], ensure_ascii=False).encode("utf-8")) <= MAX_CONTEXT_BYTES
    assert all("content" not in message for message in result["messages"])
    assert all(secret not in repr(result) for secret in ("question-secret", "context-secret", "nested-secret", "message-secret"))
    assert "provider.invalid" not in repr(result)
    assert set(("summary", "conclusion", "facts", "next_steps")) <= result.keys()
    assert set(("summary", "conclusion", "facts", "next_steps")) <= result["final"].keys()


def test_normal_execution_public_state_keeps_only_bounded_message_roles():
    from services.investigation_graph.graph import build_investigation_graph
    from services.investigation_graph.state import MAX_CONTEXT_BYTES

    gateway = FakeGateway([final_action("safe")])
    graph = build_investigation_graph(gateway=gateway)
    values = {
        "question": "Why is TTFT increasing?",
        "context": {"missing_claim": "degradation_category"},
        "missing_claim": "degradation_category",
        "messages": [
            {"role": "user", "content": "raw conversation https://secret.invalid apiKey=secret"},
            {"role": "assistant", "content": "模型输出凭证" * 2000},
        ],
    }
    original = deepcopy(values)

    result = graph.invoke(values)

    assert values == original
    assert result["status"] == "RESOLVED"
    assert result["messages"] == [{"role": "user"}, {"role": "assistant"}]
    assert all("content" not in message for message in result["messages"])
    assert len(json.dumps(result["messages"], ensure_ascii=False).encode("utf-8")) <= MAX_CONTEXT_BYTES
    assert "secret.invalid" not in repr(result)
    assert "apiKey=secret" not in repr(result)
    outbound = gateway.calls[0].messages
    assert outbound[0]["role"] == "system"
    assert "read-only" in outbound[0]["content"].lower()
    assert json.loads(outbound[1]["content"])["history"] == [{"role": "user"}, {"role": "assistant"}]
    assert all(key in result for key in ("summary", "conclusion", "facts", "next_steps"))
