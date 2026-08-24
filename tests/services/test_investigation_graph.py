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
