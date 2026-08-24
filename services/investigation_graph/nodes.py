"""LangGraph node implementations and the investigation security gates."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema import SchemaError, ValidationError, validate

from services.model_gateway.base import (
    CallToolAction,
    FinalAction,
    ModelRequest,
    StructuredOutputInvalidError,
    parse_action,
)
from services.plugin_runtime.executor import ExecutionOrigin

from .schemas import (
    Evidence,
    FinalAnswer,
    FinalResult,
    ToolCallHistory,
    ToolRequest,
    model_dump,
)
from .state import (
    DEFAULT_MAX_TOOL_CALLS,
    MAX_CONTEXT_BYTES,
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_PAYLOAD_BYTES,
    MAX_CONFIGURED_BUDGET,
    MAX_TOOL_HISTORY_ITEMS,
)


@dataclass(frozen=True)
class InvestigationRuntime:
    """Dependencies supplied by the graph factory.

    Keeping the gateway, registry, and executor outside graph state prevents
    provider transports and mutable ORM objects from becoming serialisable
    state.  Tests can inject deterministic fakes through this single object.
    """

    gateway: Any
    registry: Any
    executor: Any


class _ToolBoundaryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_PROTOCOL_SYSTEM_MESSAGE = (
    "Return exactly one documented FINAL or CALL_TOOL JSON action. "
    "Tool calls are read-only and may use only the supplied investigation context."
)
_PROMPT_CONTEXT_BYTES = 1024
_PROMPT_EVIDENCE_BYTES = 512
_PROMPT_HISTORY_BYTES = 512


def build_context(state: Mapping[str, Any]) -> dict[str, Any]:
    """Compress caller context into the bounded form sent to the gateway."""

    result = dict(state)
    result["question"] = _safe_text(state.get("question"))[:4000]
    context = _safe_mapping(state.get("context"))
    claim = (
        state.get("missing_claim")
        or state.get("claim_gap")
        or context.get("missing_claim")
        or context.get("claim_gap")
        or ""
    )
    claim = _canonical_claim(claim)
    if claim:
        context["missing_claim"] = claim
        result["missing_claim"] = claim
        result["claim_gap"] = claim
    else:
        result["missing_claim"] = ""
        result["claim_gap"] = ""
    max_rounds = _positive_int(state.get("max_rounds"), 3)
    max_tool_calls = _positive_int(state.get("max_tool_calls"), DEFAULT_MAX_TOOL_CALLS)
    context["budgets"] = {
        "max_rounds": max_rounds,
        "max_tool_calls": max_tool_calls,
    }
    result["context"] = _bounded_json(context, MAX_CONTEXT_BYTES, protected={"missing_claim", "budgets"})
    result["max_rounds"] = max_rounds
    result["max_tool_calls"] = max_tool_calls
    result["rounds_used"] = min(_nonnegative_int(state.get("rounds_used")), max_rounds)
    result["tool_calls_used"] = min(_nonnegative_int(state.get("tool_calls_used")), max_tool_calls)
    result["evidence"] = _bounded_json(
        _safe_evidence_list(state.get("evidence")),
        MAX_CONTEXT_BYTES,
    )
    result["tool_history"] = _bounded_json(
        _safe_tool_history(state.get("tool_history")),
        MAX_CONTEXT_BYTES,
    )
    result["facts"] = _bounded_json(_string_list(state.get("facts")), MAX_CONTEXT_BYTES)
    result["next_steps"] = _bounded_json(_string_list(state.get("next_steps")), MAX_CONTEXT_BYTES)
    result["messages"] = _bounded_json(_safe_messages(state.get("messages")), MAX_CONTEXT_BYTES)
    return result


def plan_or_answer(state: Mapping[str, Any], *, gateway: Any) -> dict[str, Any]:
    """Ask the injected gateway for one structured FINAL/CALL_TOOL action."""

    result = dict(state)
    if result.get("status") in {"RESOLVED", "UNRESOLVED", "FAILED"}:
        return result
    rounds_used = _nonnegative_int(result.get("rounds_used"))
    max_rounds = _positive_int(result.get("max_rounds"), 3)
    if rounds_used >= max_rounds:
        return _budget_stop(result, "maximum investigation rounds reached")
    question = result.get("question")
    if not isinstance(question, str) or not question.strip():
        return _terminal_failure(result, "QUESTION_INVALID", "question is required")

    result["rounds_used"] = rounds_used + 1
    try:
        response = gateway.invoke(ModelRequest(messages=_request_messages(result)))
        action = _response_action(response)
    except Exception as exc:  # providers expose stable error codes; fakes may not
        code = _safe_error_code(getattr(exc, "code", ""), "MODEL_GATEWAY_ERROR")
        return _terminal_failure(result, code, "model gateway invocation failed")

    if isinstance(action, FinalAction):
        safe_action = {
            "action": "FINAL",
            "answer": {
                "summary": _safe_text(action.summary)[:4000],
                "confidence": action.confidence,
            },
        }
        result["action"] = safe_action
        # LangGraph merges updates; an empty marker explicitly clears a prior
        # tool request rather than relying on a missing key to delete it.
        result["pending_tool"] = {}
    elif isinstance(action, CallToolAction):
        capability_id = _canonical_capability_id(action.capability_id)
        if not capability_id:
            return _terminal_unresolved(
                result,
                "CAPABILITY_REQUEST_INVALID",
                "requested capability identifier is invalid",
            )
        safe_tool = {
            "capability_id": capability_id,
            "arguments": _bounded_json(
                _safe_mapping(action.arguments),
                MAX_CONTEXT_BYTES,
            ),
            "reason": _safe_text(action.reason)[:2000],
        }
        result["action"] = {"action": "CALL_TOOL", "tool": safe_tool}
        result["pending_tool"] = safe_tool
    else:  # parse_action is strict, this protects custom fakes returning a novel object.
        return _terminal_failure(result, "STRUCTURED_OUTPUT_INVALID", "model action is invalid")
    return result


def select_tool(state: Mapping[str, Any], *, registry: Any) -> dict[str, Any]:
    """Resolve and validate the model-selected capability before dispatch."""

    result = dict(state)
    if result.get("status") in {"RESOLVED", "UNRESOLVED", "FAILED"}:
        return result
    pending = result.get("pending_tool")
    try:
        request = ToolRequest.model_validate(pending)
    except Exception:
        return _terminal_unresolved(result, "CAPABILITY_REQUEST_INVALID", "tool request is invalid")

    claim = _claim_from_state(result)
    if not claim:
        _append_tool_history(
            result,
            pending,
            status="REJECTED",
            outcome="REJECTED",
            error_code="MISSING_CLAIM_REQUIRED",
        )
        return _terminal_unresolved(result, "MISSING_CLAIM_REQUIRED", "a canonical missing claim is required")
    capability_id = _canonical_capability_id(request.capability_id)
    if not capability_id:
        return _terminal_unresolved(result, "CAPABILITY_REQUEST_INVALID", "requested capability identifier is invalid")
    request = ToolRequest(
        capability_id=capability_id,
        arguments=_bounded_json(_safe_mapping(request.arguments), MAX_CONTEXT_BYTES),
        reason=_safe_text(request.reason)[:2000],
    )
    version = _resolve_capability(registry, request.capability_id, claim=claim)
    if version is None:
        _append_tool_history(
            result,
            request.model_dump(),
            status="REJECTED",
            outcome="REJECTED",
            error_code="CAPABILITY_NOT_FOUND",
        )
        return _terminal_unresolved(result, "CAPABILITY_NOT_FOUND", "requested capability is unavailable")
    reason = _validate_capability(version, request.capability_id, request.arguments, claim=claim)
    if reason is not None:
        _append_tool_history(
            result,
            request.model_dump(),
            status="REJECTED",
            outcome="REJECTED",
            error_code="CAPABILITY_REJECTED",
        )
        return _terminal_unresolved(result, "CAPABILITY_REJECTED", reason)

    result["selected_capability"] = {
        "capability_id": request.capability_id,
        "arguments": _safe_mapping(request.arguments),
        "reason": request.reason[:2000],
        "claim": claim or "",
    }
    _append_tool_history(result, request.model_dump(), status="SELECTED", outcome="PENDING")
    return result


def execute_readonly_tool(
    state: Mapping[str, Any],
    *,
    registry: Any,
    executor: Any,
) -> dict[str, Any]:
    """Execute one validated LLM-origin capability and emit compact Evidence."""

    result = dict(state)
    if result.get("status") in {"RESOLVED", "UNRESOLVED", "FAILED"}:
        return result
    selected = result.get("selected_capability")
    if not isinstance(selected, Mapping):
        return _terminal_unresolved(result, "CAPABILITY_NOT_SELECTED", "no validated capability is selected")
    tool_calls = _nonnegative_int(result.get("tool_calls_used"))
    max_tool_calls = _positive_int(result.get("max_tool_calls"), DEFAULT_MAX_TOOL_CALLS)
    if tool_calls >= max_tool_calls:
        return _budget_stop(result, "maximum tool calls reached")
    evidence = _safe_evidence_list(result.get("evidence"))
    if len(evidence) >= MAX_EVIDENCE_ITEMS:
        return _budget_stop(result, "maximum evidence items reached")

    capability_id = selected.get("capability_id")
    arguments = selected.get("arguments")
    if not isinstance(capability_id, str) or not isinstance(arguments, Mapping):
        return _terminal_unresolved(result, "CAPABILITY_REQUEST_INVALID", "validated tool request is invalid")
    capability_id = _canonical_capability_id(capability_id)
    claim = _canonical_claim(selected.get("claim")) or _claim_from_state(result)
    if not capability_id:
        return _terminal_unresolved(result, "CAPABILITY_REQUEST_INVALID", "requested capability identifier is invalid")
    if not claim:
        _update_tool_history(result, capability_id, status="REJECTED", outcome="REJECTED", error_code="MISSING_CLAIM_REQUIRED")
        return _terminal_unresolved(result, "MISSING_CLAIM_REQUIRED", "a canonical missing claim is required")
    arguments = _bounded_json(_safe_mapping(arguments), MAX_CONTEXT_BYTES)

    # Count an attempted dispatch exactly once and never beyond the ceiling.
    result["tool_calls_used"] = tool_calls + 1
    try:
        atomic_execute = getattr(registry, "execute_readonly", None)
        if not callable(atomic_execute):
            raise _ToolBoundaryError("ATOMIC_DISPATCH_REQUIRED")
        execution = atomic_execute(
            capability_id,
            claim=claim,
            payload=dict(arguments),
            executor=executor,
            origin=ExecutionOrigin.LLM,
        )
        if not isinstance(execution, tuple) or len(execution) != 2:
            raise _ToolBoundaryError("ATOMIC_RESULT_INVALID")
        version, raw_result = execution
        if version is None:
            raise _ToolBoundaryError("ATOMIC_RESULT_INVALID")
        reason = _validate_capability(version, capability_id, arguments, claim=claim)
        if reason is not None:
            raise _ToolBoundaryError("CAPABILITY_REJECTED")
        output_schema = getattr(version, "output_schema", None)
        _validate_schema_instance(raw_result, output_schema, "output")
        compact = _bounded_json(
            _compact_output(raw_result, allowed_keys=_public_output_keys(output_schema)),
            MAX_EVIDENCE_PAYLOAD_BYTES,
        )
    except Exception as exc:
        code = _safe_error_code(getattr(exc, "code", ""), "TOOL_EXECUTION_FAILED")
        _update_tool_history(result, capability_id, status="FAILED", outcome="FAILED", error_code=code[:64])
        return _terminal_unresolved(result, code[:64], "read-only capability execution failed")

    evidence_item = Evidence(
        evidence_key=f"{capability_id}:{result['tool_calls_used']}",
        summary=_summarize(compact),
        payload=compact,
        source=capability_id,
        capability_id=capability_id,
    )
    evidence.append(model_dump(evidence_item))
    result["evidence"] = evidence[:MAX_EVIDENCE_ITEMS]
    _update_tool_history(
        result,
        capability_id,
        status="SUCCEEDED",
        outcome="SUCCEEDED",
        evidence_key=evidence_item.evidence_key,
    )
    facts = _string_list(result.get("facts"))
    if evidence_item.summary not in facts:
        facts.append(evidence_item.summary)
    result["facts"] = facts
    result["selected_capability"] = {}
    result["pending_tool"] = {}
    if result["tool_calls_used"] >= max_tool_calls:
        return _budget_stop(result, "maximum tool calls reached")
    if _nonnegative_int(result.get("rounds_used")) >= _positive_int(result.get("max_rounds"), 3):
        return _budget_stop(result, "maximum investigation rounds reached")
    return result


def final_answer(state: Mapping[str, Any]) -> dict[str, Any]:
    """Materialise one stable result shape for direct, failure, and budget paths."""

    result = dict(state)
    existing = result.get("final")
    if isinstance(existing, Mapping):
        # Re-normalise even an injected terminal state so public types remain stable.
        status = _status(existing.get("status"), result.get("status"))
        summary = _safe_text(existing.get("summary")) or _safe_text(result.get("summary"))
        conclusion = _safe_text(existing.get("conclusion")) or _safe_text(result.get("conclusion"))
        confidence = _confidence(existing.get("confidence"), result.get("confidence"))
    else:
        action = _response_action(result.get("action")) if result.get("action") else None
        status = _status(result.get("status"), "RESOLVED" if isinstance(action, FinalAction) else "UNRESOLVED")
        if isinstance(action, FinalAction):
            answer = FinalAnswer(summary=action.summary, confidence=action.confidence)
            summary = answer.summary
            conclusion = answer.summary
            confidence = answer.confidence
        else:
            summary = _safe_text(result.get("summary")) or "Investigation did not reach a final answer"
            conclusion = _safe_text(result.get("conclusion")) or summary
            confidence = _confidence(result.get("confidence"), 0.0)
    facts = _string_list(result.get("facts"))
    next_steps = _string_list(result.get("next_steps"))
    tool_history = _safe_tool_history(result.get("tool_history"))
    if status != "RESOLVED" and not next_steps:
        next_steps = ["Collect the missing evidence and retry the investigation."]
    final = FinalResult(
        status=status,
        summary=summary,
        conclusion=conclusion,
        facts=facts,
        next_steps=next_steps,
        confidence=confidence,
        evidence=[Evidence.model_validate(item) for item in _safe_evidence_list(result.get("evidence"))],
        tool_history=[ToolCallHistory.model_validate(item) for item in tool_history],
        rounds_used=_nonnegative_int(result.get("rounds_used")),
        tool_calls_used=_nonnegative_int(result.get("tool_calls_used")),
    )
    dumped = model_dump(final)
    result.update(
        {
            "status": dumped["status"],
            "summary": dumped["summary"],
            "conclusion": dumped["conclusion"],
            "facts": dumped["facts"],
            "next_steps": dumped["next_steps"],
            "confidence": dumped["confidence"],
            "evidence": dumped["evidence"],
            "tool_history": dumped["tool_history"],
            "rounds_used": dumped["rounds_used"],
            "tool_calls_used": dumped["tool_calls_used"],
            "final": dumped,
        }
    )
    return result


def route_after_plan(state: Mapping[str, Any]) -> str:
    if state.get("status") in {"RESOLVED", "UNRESOLVED", "FAILED"}:
        return "final_answer"
    pending = state.get("pending_tool")
    return "select_tool" if isinstance(pending, Mapping) and bool(pending) else "final_answer"


def route_after_select(state: Mapping[str, Any]) -> str:
    selected = state.get("selected_capability")
    return "execute_readonly_tool" if isinstance(selected, Mapping) and bool(selected) else "final_answer"


def route_after_tool(state: Mapping[str, Any]) -> str:
    if state.get("status") in {"RESOLVED", "UNRESOLVED", "FAILED"}:
        return "final_answer"
    return "plan_or_answer"


def _resolve_capability(registry: Any, capability_id: str, *, claim: str | None):
    canonical_claim = _canonical_claim(claim)
    if not canonical_claim or _canonical_capability_id(capability_id) != capability_id:
        return None
    resolver = getattr(registry, "resolve_capability", None)
    if resolver is None:
        resolver = getattr(registry, "resolve", None)
    if resolver is None:
        return None
    try:
        # A resolver that cannot accept the canonical claim is not safe for
        # this path.  Never fall back to a broad capability lookup with
        # ``claim=None``.
        return resolver(capability_id, claim=canonical_claim)
    except Exception:
        return None


def _validate_capability(version: Any, capability_id: str, arguments: Mapping[str, Any], *, claim: str | None) -> str | None:
    canonical_claim = _canonical_claim(claim)
    if not canonical_claim or canonical_claim != claim:
        return "a canonical missing claim is required"
    capability = getattr(version, "capability", version)
    actual_id = getattr(capability, "capability_id", None) or getattr(version, "capability_id", None)
    if actual_id != capability_id:
        return "requested capability does not match the registry entry"
    capability_status = _enum_value(getattr(capability, "status", "ACTIVE"))
    version_status = _enum_value(getattr(version, "status", "ACTIVE"))
    if capability_status != "ACTIVE" or version_status != "ACTIVE":
        return "capability and version must be ACTIVE"
    if getattr(capability, "read_only", getattr(version, "read_only", None)) is not True:
        return "LLM execution requires a read-only capability"
    current_version = getattr(capability, "current_version", None)
    if current_version is not None:
        current_id = getattr(current_version, "pk", None) or getattr(current_version, "id", None)
        version_id = getattr(version, "pk", None) or getattr(version, "id", None)
        if current_id is not None and version_id is not None and current_id != version_id:
            return "capability version is not current"
    resolves = getattr(version, "resolves", None)
    if not isinstance(resolves, Sequence) or isinstance(resolves, (str, bytes)) or canonical_claim not in resolves:
        return "capability does not resolve the requested claim"
    input_schema = getattr(version, "input_schema", None)
    if not isinstance(input_schema, Mapping):
        return "capability input schema is invalid"
    try:
        validate(dict(arguments), input_schema)
    except (ValidationError, SchemaError, TypeError):
        return "tool arguments do not satisfy the capability schema"
    return None


def _validate_schema_instance(value: Any, schema: Any, label: str) -> None:
    if not isinstance(schema, Mapping):
        raise ValueError(f"{label} schema is invalid")
    try:
        validate(value, schema)
    except (ValidationError, SchemaError, TypeError) as exc:
        raise ValueError(f"{label} schema validation failed") from exc


def _response_action(response: Any):
    if isinstance(response, (FinalAction, CallToolAction)):
        return _round_trip_action(response)
    if isinstance(response, Mapping):
        return parse_action(response)
    action = getattr(response, "action", None)
    if isinstance(action, (FinalAction, CallToolAction)):
        return _round_trip_action(action)
    if isinstance(action, Mapping):
        return parse_action(action)
    content = getattr(response, "content", None)
    if isinstance(content, (FinalAction, CallToolAction)):
        return _round_trip_action(content)
    if content is not None:
        return parse_action(content)
    return parse_action(response)


def _round_trip_action(action: FinalAction | CallToolAction):
    try:
        payload = action.to_dict()
    except Exception as exc:
        raise StructuredOutputInvalidError("structured model action is invalid") from exc
    return parse_action(payload)


def _request_messages(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    context = _bounded_json(
        _safe_mapping(state.get("context")),
        _PROMPT_CONTEXT_BYTES,
        protected={"missing_claim", "budgets"},
    )
    evidence = _bounded_json(
        _safe_evidence_list(state.get("evidence")),
        _PROMPT_EVIDENCE_BYTES,
    )
    history = _safe_messages(state.get("messages"))
    history = _bounded_json(
        [{"role": item["role"]} for item in history],
        _PROMPT_HISTORY_BYTES,
    )
    body = {
        "question": _safe_text(state.get("question"))[:512],
        "context": context,
        "evidence": evidence,
        "history": history,
        "constraints": {
            "read_only_only": True,
            "max_rounds": _positive_int(state.get("max_rounds"), 3),
            "max_tool_calls": _positive_int(state.get("max_tool_calls"), DEFAULT_MAX_TOOL_CALLS),
        },
    }
    return _bounded_prompt_messages(body)


def _bounded_prompt_messages(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep the fixed protocol envelope and complete packet within the cap."""

    system = {"role": "system", "content": _PROTOCOL_SYSTEM_MESSAGE}
    candidate = dict(body)
    for _ in range(16):
        content = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        packet = [system, {"role": "user", "content": content}]
        if _serialized_bytes(packet) <= MAX_CONTEXT_BYTES:
            return packet
        current_size = _serialized_bytes(candidate)
        candidate = _bounded_json(
            candidate,
            max(current_size - 256, 0),
            protected={"context", "constraints"},
        )

    fallback = {
        "question": "",
        "context": _bounded_json(
            body.get("context"),
            256,
            protected={"missing_claim", "budgets"},
        ),
        "evidence": [],
        "history": [],
        "constraints": body.get("constraints", {"read_only_only": True}),
    }
    content = json.dumps(fallback, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return [system, {"role": "user", "content": content}]


def _compact_output(value: Any, *, allowed_keys: set[str] | None = None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        compact = _safe_mapping(value, depth=0, allowed_keys=allowed_keys)
    else:
        safe = _safe_value(value, depth=0)
        if safe is _DROP:
            raise ValueError("tool output is not safely serialisable")
        compact = {"value": safe}
    return compact


def _safe_mapping(
    value: Any,
    *,
    depth: int = 0,
    allowed_keys: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, Any] = {}
    for index, (key, item) in enumerate(sorted(value.items(), key=lambda pair: str(pair[0]))):
        if index >= 32:
            break
        key_text = str(key)[:192]
        if not _public_key(key_text) or _sensitive_key(key_text):
            continue
        if allowed_keys is not None and key_text not in allowed_keys:
            continue
        safe = _safe_value(item, depth=depth + 1)
        if safe is not _DROP:
            output[key_text] = safe
    return output


_DROP = object()


def _safe_value(value: Any, *, depth: int):
    if depth > 3:
        return _DROP
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, str):
        text = value[:500]
        lowered = text.lower()
        if _looks_sensitive(text) or "bearer " in lowered:
            return _DROP
        return text
    if isinstance(value, Mapping):
        return _safe_mapping(value, depth=depth)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = []
        for item in list(value)[:32]:
            safe = _safe_value(item, depth=depth + 1)
            if safe is not _DROP:
                items.append(safe)
        return items
    return _DROP


def _safe_evidence_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output = []
    for item in value[:MAX_EVIDENCE_ITEMS]:
        if isinstance(item, Mapping):
            try:
                cleaned = {
                    "evidence_key": _safe_text(item.get("evidence_key"))[:192],
                    "summary": _safe_text(item.get("summary"))[:4000],
                    "payload": _bounded_json(
                        _safe_mapping(item.get("payload")),
                        MAX_EVIDENCE_PAYLOAD_BYTES,
                    ),
                    "source": _safe_text(item.get("source"))[:128],
                    "capability_id": _safe_text(item.get("capability_id"))[:192],
                    "confidence": item.get("confidence", 1.0),
                    "materiality": item.get("materiality", 0.0),
                }
                output.append(model_dump(Evidence.model_validate(cleaned)))
            except Exception:
                continue
    return output


def _safe_tool_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output = []
    for item in value[:MAX_TOOL_HISTORY_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        capability_id = _canonical_capability_id(item.get("capability_id"))
        if not capability_id:
            continue
        try:
            history = ToolCallHistory(
                capability_id=capability_id,
                arguments=_bounded_json(
                    _safe_mapping(item.get("arguments")),
                    MAX_CONTEXT_BYTES,
                ),
                reason=_safe_text(item.get("reason"))[:2000],
                status=_safe_history_label(item.get("status")),
                outcome=_safe_history_label(item.get("outcome")),
                error_code=_safe_error_code(item.get("error_code"), ""),
                evidence_key=_safe_text(item.get("evidence_key"))[:192],
            )
            output.append(model_dump(history))
        except Exception:
            continue
    return output


def _bounded_json(value: Any, limit: int, *, protected: set[str] | None = None):
    """Return deterministic JSON-compatible data within a byte ceiling."""

    protected = protected or set()
    candidate = value
    if _serialized_bytes(candidate) <= limit:
        return candidate
    if isinstance(candidate, Mapping):
        candidate = dict(candidate)
        for key in sorted(candidate, key=str, reverse=True):
            if str(key) in protected:
                continue
            candidate.pop(key, None)
            if _serialized_bytes(candidate) <= limit:
                return _mark_truncated(candidate, limit, protected)
        # Protected values are bounded by their own scalar limits; if a caller
        # still supplies an oversized value, retain only a stable marker.
        return {"_truncated": True} if _serialized_bytes({"_truncated": True}) <= limit else {}
    if isinstance(candidate, list):
        candidate = list(candidate)
        while candidate and _serialized_bytes(candidate) > limit:
            candidate.pop()
        return _mark_truncated(candidate, limit, protected)
    if isinstance(candidate, str):
        encoded = candidate.encode("utf-8")
        candidate = encoded[: max(limit - 32, 0)].decode("utf-8", errors="ignore")
        return candidate if _serialized_bytes(candidate) <= limit else ""
    return {"_truncated": True} if _serialized_bytes({"_truncated": True}) <= limit else {}


def _mark_truncated(value: Any, limit: int, protected: set[str]):
    if isinstance(value, dict):
        value = dict(value)
        value["_truncated"] = True
        while _serialized_bytes(value) > limit:
            removable = [
                key
                for key in sorted(value, key=str, reverse=True)
                if str(key) not in protected and key != "_truncated"
            ]
            if not removable:
                return {"_truncated": True} if _serialized_bytes({"_truncated": True}) <= limit else {}
            value.pop(removable[0], None)
        return value
    return value


def _serialized_bytes(value: Any) -> int:
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        return 10**9


def _public_output_keys(schema: Any) -> set[str] | None:
    """Use declared output properties as a positive public-field allowlist."""

    if not isinstance(schema, Mapping):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        return None
    return {
        str(key)[:192]
        for key in properties
        if _public_key(str(key)[:192]) and not _sensitive_key(str(key)[:192])
    }


def _summarize(payload: Mapping[str, Any]) -> str:
    if not payload:
        return "Tool returned no public fields"
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))[:4000]
    except (TypeError, ValueError):
        return "Tool returned no serialisable public fields"


_PUBLIC_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}")
_CAPABILITY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}")
_CLAIM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}")
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:api[\W_]*key|access[\W_]*key|id[\W_]*token|pass(?:word|wd)|"
    r"secret(?:[\W_]*key)?|authorization)(?:[\W_]|$)"
)

_SENSITIVE_KEYS = {
    "accesskey",
    "apikey",
    "authtoken",
    "authorization",
    "bearer",
    "clientsecret",
    "connectionstring",
    "cookie",
    "credential",
    "credentials",
    "databaseurl",
    "dbpassword",
    "dsn",
    "endpoint",
    "env",
    "environment",
    "idtoken",
    "password",
    "passwd",
    "passphrase",
    "pwd",
    "privatekey",
    "raw",
    "rawpayload",
    "secret",
    "secretkey",
    "sessiontoken",
    "token",
    "url",
    "uri",
}
_SAFE_HISTORY_LABELS = {
    "BUDGET_EXHAUSTED",
    "FAILED",
    "PENDING",
    "REJECTED",
    "RUNNING",
    "SELECTED",
    "SUCCEEDED",
    "TIMEOUT",
    "UNKNOWN",
}


def _public_key(key: str) -> bool:
    return bool(_PUBLIC_KEY_RE.fullmatch(key))


def _canonical_key(key: str) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def _sensitive_key(key: str) -> bool:
    canonical = _canonical_key(key)
    return (
        canonical in _SENSITIVE_KEYS
        or canonical.startswith(
            (
                "raw",
                "authorization",
                "privatekey",
                "clientsecret",
                "credential",
                "apikey",
                "accesskey",
                "idtoken",
                "password",
                "passwd",
                "passphrase",
                "pwd",
                "secret",
                "token",
            )
        )
        or canonical.endswith(("apikey", "accesskey", "credential", "password", "passwd", "passphrase", "secret", "token", "url", "uri"))
    )


def _canonical_capability_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not _CAPABILITY_ID_RE.fullmatch(candidate) or _sensitive_key(candidate):
        return ""
    return candidate


def _canonical_claim(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not _CLAIM_RE.fullmatch(candidate) or _sensitive_key(candidate):
        return ""
    return candidate


def _claim_from_state(state: Mapping[str, Any]) -> str:
    context = _safe_mapping(state.get("context"))
    return _canonical_claim(
        state.get("missing_claim")
        or state.get("claim_gap")
        or context.get("missing_claim")
        or context.get("claim_gap")
    )


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith(("http://", "https://"))
        or "://" in lowered
        or "password=" in lowered
        or "token=" in lowered
        or bool(_SENSITIVE_TEXT_RE.search(value))
    )


def _append_tool_history(
    state: dict[str, Any],
    request: Mapping[str, Any] | None,
    *,
    status: str,
    outcome: str,
    error_code: str = "",
    evidence_key: str = "",
) -> None:
    if not isinstance(request, Mapping):
        return
    capability_id = _canonical_capability_id(request.get("capability_id"))
    if not capability_id:
        return
    history = _safe_tool_history(state.get("tool_history"))
    try:
        item = ToolCallHistory(
            capability_id=capability_id,
            arguments=_bounded_json(_safe_mapping(request.get("arguments")), MAX_CONTEXT_BYTES),
            reason=_safe_text(request.get("reason"))[:2000],
            status=_safe_history_label(status),
            outcome=_safe_history_label(outcome),
            error_code=_safe_error_code(error_code, ""),
            evidence_key=evidence_key[:192],
        )
        history.append(model_dump(item))
    except Exception:
        return
    state["tool_history"] = history[-MAX_TOOL_HISTORY_ITEMS:]


def _update_tool_history(
    state: dict[str, Any],
    capability_id: str,
    *,
    status: str,
    outcome: str,
    error_code: str = "",
    evidence_key: str = "",
) -> None:
    history = _safe_tool_history(state.get("tool_history"))
    for index in range(len(history) - 1, -1, -1):
        if history[index].get("capability_id") == capability_id and history[index].get("status") in {"SELECTED", "PENDING"}:
            history[index].update(
                {
                    "status": _safe_history_label(status),
                    "outcome": _safe_history_label(outcome),
                    "error_code": _safe_error_code(error_code, ""),
                    "evidence_key": evidence_key[:192],
                }
            )
            state["tool_history"] = history[-MAX_TOOL_HISTORY_ITEMS:]
            return
    _append_tool_history(
        state,
        {"capability_id": capability_id, "arguments": {}, "reason": ""},
        status=status,
        outcome=outcome,
        error_code=error_code,
        evidence_key=evidence_key,
    )


def _terminal_unresolved(state: Mapping[str, Any], code: str, message: str) -> dict[str, Any]:
    result = dict(state)
    result.update(
        {
            "status": "UNRESOLVED",
            "error_code": code,
            "error_message": message,
            "summary": message,
            "conclusion": message,
            "next_steps": ["Collect the missing evidence and retry the investigation."],
        }
    )
    result.pop("selected_capability", None)
    result.pop("pending_tool", None)
    return result


def _terminal_failure(state: Mapping[str, Any], code: str, message: str) -> dict[str, Any]:
    result = dict(state)
    result.update(
        {
            "status": "FAILED",
            "error_code": code,
            "error_message": message,
            "summary": message,
            "conclusion": message,
            "next_steps": ["Retry the investigation after the provider or input issue is resolved."],
        }
    )
    result.pop("selected_capability", None)
    result.pop("pending_tool", None)
    return result


def _budget_stop(state: Mapping[str, Any], reason: str) -> dict[str, Any]:
    result = dict(state)
    pending_ids = []
    for candidate in (
        result.get("selected_capability"),
        result.get("pending_tool"),
    ):
        if isinstance(candidate, Mapping):
            capability_id = _canonical_capability_id(candidate.get("capability_id"))
            if capability_id:
                pending_ids.append(capability_id)
    for item in _safe_tool_history(result.get("tool_history")):
        if item.get("status") in {"SELECTED", "PENDING"}:
            capability_id = _canonical_capability_id(item.get("capability_id"))
            if capability_id:
                pending_ids.append(capability_id)
    for capability_id in dict.fromkeys(pending_ids):
        _update_tool_history(
            result,
            capability_id,
            status="REJECTED",
            outcome="BUDGET_EXHAUSTED",
            error_code="BUDGET_EXHAUSTED",
        )
    result.update(
        {
            "status": "UNRESOLVED",
            "error_code": "BUDGET_EXHAUSTED",
            "error_message": reason,
            "summary": "Investigation stopped before a complete conclusion",
            "conclusion": reason,
            "next_steps": ["Collect the missing evidence and retry the investigation."],
        }
    )
    result.pop("selected_capability", None)
    result.pop("pending_tool", None)
    return result


def _status(value: Any, fallback: Any) -> str:
    candidate = _enum_value(value)
    return candidate if candidate in {"RESOLVED", "UNRESOLVED", "FAILED"} else _status(fallback, "UNRESOLVED") if fallback != value else "UNRESOLVED"


def _enum_value(value: Any) -> str:
    value = getattr(value, "value", value)
    return value if isinstance(value, str) else str(value)


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return "[redacted]" if _looks_sensitive(text) else text


def _safe_error_code(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    candidate = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", candidate):
        return fallback
    return fallback if _sensitive_key(candidate) else candidate


def _safe_history_label(value: Any) -> str:
    candidate = _safe_text(value).upper()
    return candidate if candidate in _SAFE_HISTORY_LABELS else "UNKNOWN"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_text(item)[:1000] for item in value if isinstance(item, str) and item.strip()][:64]


def _safe_messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    output = []
    for item in value[:32]:
        if not isinstance(item, Mapping):
            continue
        role = _safe_text(item.get("role"))[:32]
        if role:
            # Conversation content is owned by Task 12.  Preserve only the
            # smallest safe role metadata in graph state; outbound prompts
            # are rebuilt from the fixed protocol envelope and compact state.
            output.append({"role": role})
    return output


def _confidence(value: Any, fallback: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        try:
            number = float(fallback)
        except (TypeError, ValueError):
            number = 0.0
    return min(max(number, 0.0), 1.0)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(number, MAX_CONFIGURED_BUDGET) if number > 0 else fallback


def _nonnegative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0
