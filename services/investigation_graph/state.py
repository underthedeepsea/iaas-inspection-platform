"""Typed state and hard limits for the provider-neutral investigation graph."""

from __future__ import annotations

from typing import Any, TypedDict


DEFAULT_MAX_ROUNDS = 3
DEFAULT_MAX_TOOL_CALLS = 5
MAX_EVIDENCE_ITEMS = 30
# Keep graph context/tool output small enough for provider prompts and later
# persistence.  Caps are byte counts, not Python character counts.
MAX_CONTEXT_BYTES = 4096
MAX_EVIDENCE_PAYLOAD_BYTES = 4096
MAX_TOOL_HISTORY_ITEMS = 32
MAX_CONFIGURED_BUDGET = 64


class InvestigationState(TypedDict, total=False):
    """Only JSON-like values are carried between graph nodes.

    Capability ORM objects and raw provider responses deliberately never enter
    this state.  A registry is queried again at execution time from the
    injected runtime dependency instead.
    """

    question: str
    context: dict[str, Any]
    messages: list[dict[str, Any]]
    missing_claim: str
    claim_gap: str
    max_rounds: int
    max_tool_calls: int
    rounds_used: int
    tool_calls_used: int
    evidence: list[dict[str, Any]]
    tool_history: list[dict[str, Any]]
    facts: list[str]
    next_steps: list[str]
    action: dict[str, Any]
    pending_tool: dict[str, Any]
    selected_capability: dict[str, Any]
    status: str
    summary: str
    conclusion: str
    confidence: float
    error_code: str
    error_message: str
    final: dict[str, Any]


def initial_state(values: dict[str, Any] | None = None) -> InvestigationState:
    """Return a fresh state with bounded default counters and stable fields."""

    values = dict(values or {})
    state: InvestigationState = {
        "question": values.get("question") if isinstance(values.get("question"), str) else "",
        "context": values.get("context") if isinstance(values.get("context"), dict) else {},
        "messages": values.get("messages") if isinstance(values.get("messages"), list) else [],
        "missing_claim": values.get("missing_claim") if isinstance(values.get("missing_claim"), str) else "",
        "claim_gap": values.get("claim_gap") if isinstance(values.get("claim_gap"), str) else "",
        "max_rounds": _positive_limit(values.get("max_rounds"), DEFAULT_MAX_ROUNDS),
        "max_tool_calls": _positive_limit(values.get("max_tool_calls"), DEFAULT_MAX_TOOL_CALLS),
        "rounds_used": _nonnegative_int(values.get("rounds_used")),
        "tool_calls_used": _nonnegative_int(values.get("tool_calls_used")),
        "evidence": list(values.get("evidence") or []) if isinstance(values.get("evidence"), list) else [],
        "tool_history": list(values.get("tool_history") or []) if isinstance(values.get("tool_history"), list) else [],
        "facts": list(values.get("facts") or []) if isinstance(values.get("facts"), list) else [],
        "next_steps": list(values.get("next_steps") or []) if isinstance(values.get("next_steps"), list) else [],
        "status": str(values.get("status", "")),
    }
    return state


def _positive_limit(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(parsed, MAX_CONFIGURED_BUDGET) if parsed > 0 else default


def _nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)
