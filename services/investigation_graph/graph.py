"""LangGraph assembly and provider-injected execution entry points."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes import (
    InvestigationRuntime,
    build_context,
    execute_readonly_tool,
    final_answer,
    plan_or_answer,
    route_after_plan,
    route_after_select,
    route_after_tool,
    select_tool,
)
from .state import MAX_CONFIGURED_BUDGET, InvestigationState, initial_state


MAX_RECURSION_LIMIT = 256


def build_investigation_graph(
    gateway: Any,
    registry: Any | None = None,
    executor: Any | None = None,
    max_rounds: int = 3,
    max_tool_calls: int = 5,
):
    """Compile the investigation graph with all external dependencies injected.

    ``gateway`` is intentionally required: creating a graph must never start
    or implicitly connect to an Ollama/HTTP provider.  Registry and executor
    defaults are lazy so direct-FINAL tests and callers do not need Django
    database access.
    """

    if gateway is None:
        raise TypeError("gateway is required")
    if registry is None:
        registry = _LazyCapabilityRegistry()
    if executor is None:
        executor = _LazyPluginExecutor()
    runtime = InvestigationRuntime(gateway=gateway, registry=registry, executor=executor)

    workflow = StateGraph(InvestigationState)
    workflow.add_node("build_context", build_context)
    workflow.add_node(
        "plan_or_answer",
        lambda state: plan_or_answer(state, gateway=runtime.gateway),
    )
    workflow.add_node(
        "select_tool",
        lambda state: select_tool(state, registry=runtime.registry),
    )
    workflow.add_node(
        "execute_readonly_tool",
        lambda state: execute_readonly_tool(
            state,
            registry=runtime.registry,
            executor=runtime.executor,
        ),
    )
    workflow.add_node("final_answer", final_answer)

    workflow.add_edge(START, "build_context")
    workflow.add_edge("build_context", "plan_or_answer")
    workflow.add_conditional_edges(
        "plan_or_answer",
        route_after_plan,
        {
            "select_tool": "select_tool",
            "final_answer": "final_answer",
        },
    )
    workflow.add_conditional_edges(
        "select_tool",
        route_after_select,
        {
            "execute_readonly_tool": "execute_readonly_tool",
            "final_answer": "final_answer",
        },
    )
    workflow.add_conditional_edges(
        "execute_readonly_tool",
        route_after_tool,
        {
            "plan_or_answer": "plan_or_answer",
            "final_answer": "final_answer",
        },
    )
    workflow.add_edge("final_answer", END)
    compiled = workflow.compile()
    return _ConfiguredGraph(compiled, max_rounds=max_rounds, max_tool_calls=max_tool_calls)


class _ConfiguredGraph:
    """Small wrapper that injects default budgets without hiding LangGraph APIs."""

    def __init__(self, compiled: Any, *, max_rounds: int, max_tool_calls: int):
        self._compiled = compiled
        self.max_rounds = (
            min(max_rounds, MAX_CONFIGURED_BUDGET)
            if isinstance(max_rounds, int) and max_rounds > 0
            else 3
        )
        self.max_tool_calls = (
            min(max_tool_calls, MAX_CONFIGURED_BUDGET)
            if isinstance(max_tool_calls, int) and max_tool_calls > 0
            else 5
        )
        self.recursion_limit = min(
            MAX_RECURSION_LIMIT,
            max(16, 3 * max(self.max_rounds, self.max_tool_calls) + 8),
        )

    def invoke(self, values: Mapping[str, Any] | None = None, config: Any = None, **kwargs: Any):
        state, config, blocked = self._prepare(values, config)
        if blocked:
            return final_answer(state)
        return self._compiled.invoke(state, config=config, **kwargs)

    def stream(self, values: Mapping[str, Any] | None = None, config: Any = None, **kwargs: Any):
        state, config, blocked = self._prepare(values, config)
        if blocked:
            yield final_answer(state)
            return
        yield from self._compiled.stream(state, config=config, **kwargs)

    def _prepare(self, values: Mapping[str, Any] | None, config: Any):
        state = initial_state(dict(values or {}))
        # Explicit input values are authoritative; factory defaults fill only
        # omitted limits and are bounded before any node increments counters.
        if not isinstance(values, Mapping) or "max_rounds" not in values:
            state["max_rounds"] = self.max_rounds
        if not isinstance(values, Mapping) or "max_tool_calls" not in values:
            state["max_tool_calls"] = self.max_tool_calls
        effective_limit = min(
            MAX_RECURSION_LIMIT,
            max(16, 3 * max(state["max_rounds"], state["max_tool_calls"]) + 8),
        )
        if config is None:
            config = {"recursion_limit": effective_limit}
        elif "recursion_limit" not in config:
            config = dict(config)
            config["recursion_limit"] = effective_limit
        else:
            configured_limit = config.get("recursion_limit")
            if (
                isinstance(configured_limit, bool)
                or not isinstance(configured_limit, int)
                or configured_limit < effective_limit
            ):
                state.update(
                    {
                        "status": "UNRESOLVED",
                        "error_code": "RECURSION_LIMIT_TOO_LOW",
                        "error_message": "configured recursion limit is below the safe investigation budget",
                        "summary": "Investigation stopped before execution",
                        "conclusion": "configured recursion limit is below the safe investigation budget",
                        "next_steps": ["Increase recursion_limit and retry the investigation."],
                    }
                )
                return state, config, True
        return state, config, False

    def __getattr__(self, name: str):
        return getattr(self._compiled, name)


class _LazyCapabilityRegistry:
    """Avoid importing Django models until a CALL_TOOL path actually needs them."""

    def resolve_capability(self, capability_id: str, *, claim: str | None = None):
        from services.plugin_runtime.registry import CapabilityRegistry

        return CapabilityRegistry().resolve_capability(capability_id, claim=claim)

    def execute_readonly(self, capability_id: str, **kwargs: Any):
        from services.plugin_runtime.registry import CapabilityRegistry

        return CapabilityRegistry().execute_readonly(capability_id, **kwargs)


class _LazyPluginExecutor:
    """Avoid constructing plugin backends for a direct FINAL path."""

    def execute(self, capability_version: Any, payload: Mapping[str, Any], *, origin: Any = None):
        from services.plugin_runtime.executor import PluginExecutor

        return PluginExecutor().execute(capability_version, payload, origin=origin)


# Public aliases used by callers that prefer a factory verb or a compact name.
create_investigation_graph = build_investigation_graph
compile_investigation_graph = build_investigation_graph


def run_investigation(values: Mapping[str, Any], *, gateway: Any, registry: Any | None = None, executor: Any | None = None, **kwargs: Any):
    """Run one investigation synchronously without persistence or workers."""

    return build_investigation_graph(
        gateway=gateway,
        registry=registry,
        executor=executor,
        **kwargs,
    ).invoke(values)
