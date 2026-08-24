"""LangGraph node implementations and the investigation security gates."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema import SchemaError, ValidationError, validate

from services.model_gateway.base import (
    CallToolAction,
    FinalAction,
    ModelRequest,
    parse_action,
)
from services.plugin_runtime.executor import ExecutionOrigin

from .schemas import Evidence, FinalAnswer, FinalResult, ToolRequest, model_dump
from .state import DEFAULT_MAX_TOOL_CALLS, MAX_EVIDENCE_ITEMS


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


def build_context(state: Mapping[str, Any]) -> dict[str, Any]:
    """Compress caller context into the bounded form sent to the gateway."""

    result = dict(state)
    result["question"] = _safe_text(state.get("question"))[:4000]
    context = _safe_mapping(state.get("context"))
    claim = state.get("missing_claim") or context.get("missing_claim") or ""
    if isinstance(claim, str):
        claim = _safe_text(claim)[:192]
    else:
        claim = ""
    if claim:
        context["missing_claim"] = claim
        result["missing_claim"] = claim
    max_rounds = _positive_int(state.get("max_rounds"), 3)
    max_tool_calls = _positive_int(state.get("max_tool_calls"), DEFAULT_MAX_TOOL_CALLS)
    context["budgets"] = {
        "max_rounds": max_rounds,
        "max_tool_calls": max_tool_calls,
    }
    result["context"] = context
    result["max_rounds"] = max_rounds
    result["max_tool_calls"] = max_tool_calls
    result["rounds_used"] = min(_nonnegative_int(state.get("rounds_used")), max_rounds)
    result["tool_calls_used"] = min(_nonnegative_int(state.get("tool_calls_used")), max_tool_calls)
    result["evidence"] = _safe_evidence_list(state.get("evidence"))
    result["facts"] = _string_list(state.get("facts"))
    result["next_steps"] = _string_list(state.get("next_steps"))
    result["messages"] = _safe_messages(state.get("messages"))
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
        code = getattr(exc, "code", "MODEL_GATEWAY_ERROR")
        if not isinstance(code, str) or not code:
            code = "MODEL_GATEWAY_ERROR"
        return _terminal_failure(result, code[:64], "model gateway invocation failed")

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
        safe_tool = {
            "capability_id": action.capability_id[:192],
            "arguments": _safe_mapping(action.arguments),
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

    claim = result.get("missing_claim") or _safe_mapping(result.get("context")).get("missing_claim")
    claim = claim if isinstance(claim, str) and claim else None
    version = _resolve_capability(registry, request.capability_id, claim=claim)
    if version is None:
        return _terminal_unresolved(result, "CAPABILITY_NOT_FOUND", "requested capability is unavailable")
    reason = _validate_capability(version, request.capability_id, request.arguments, claim=claim)
    if reason is not None:
        return _terminal_unresolved(result, "CAPABILITY_REJECTED", reason)

    result["selected_capability"] = {
        "capability_id": request.capability_id,
        "arguments": _safe_mapping(request.arguments),
        "reason": request.reason[:2000],
        "claim": claim or "",
    }
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
    claim = selected.get("claim") or result.get("missing_claim") or None
    version = _resolve_capability(registry, capability_id, claim=claim if isinstance(claim, str) else None)
    if version is None:
        return _terminal_unresolved(result, "CAPABILITY_NOT_FOUND", "requested capability is unavailable")
    reason = _validate_capability(version, capability_id, arguments, claim=claim if isinstance(claim, str) else None)
    if reason is not None:
        return _terminal_unresolved(result, "CAPABILITY_REJECTED", reason)

    # Count an attempted dispatch exactly once and never beyond the ceiling.
    result["tool_calls_used"] = tool_calls + 1
    try:
        raw_result = executor.execute(
            version,
            dict(arguments),
            origin=ExecutionOrigin.LLM,
        )
        output_schema = getattr(version, "output_schema", {})
        _validate_schema_instance(raw_result, output_schema, "output")
        compact = _compact_output(raw_result)
    except Exception as exc:
        code = getattr(exc, "code", "TOOL_EXECUTION_FAILED")
        if not isinstance(code, str) or not code:
            code = "TOOL_EXECUTION_FAILED"
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
    resolver = getattr(registry, "resolve_capability", None)
    if resolver is None:
        resolver = getattr(registry, "resolve", None)
    if resolver is None:
        return None
    try:
        if claim is not None:
            try:
                return resolver(capability_id, claim=claim)
            except TypeError:
                return resolver(capability_id)
        return resolver(capability_id)
    except Exception:
        return None


def _validate_capability(version: Any, capability_id: str, arguments: Mapping[str, Any], *, claim: str | None) -> str | None:
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
    resolves = getattr(version, "resolves", None)
    if claim and (not isinstance(resolves, Sequence) or isinstance(resolves, (str, bytes)) or claim not in resolves):
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
        return response
    if isinstance(response, Mapping):
        return parse_action(response)
    action = getattr(response, "action", None)
    if isinstance(action, (FinalAction, CallToolAction)):
        return action
    if isinstance(action, Mapping):
        return parse_action(action)
    content = getattr(response, "content", None)
    if content is not None:
        return parse_action(content)
    return parse_action(response)


def _request_messages(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    supplied = state.get("messages")
    if isinstance(supplied, list) and supplied:
        return [
            {"role": _safe_text(item.get("role"))[:32], "content": _safe_text(item.get("content"))[:4000]}
            for item in supplied
            if isinstance(item, Mapping)
        ]
    context = _safe_mapping(state.get("context"))
    evidence = _safe_evidence_list(state.get("evidence"))
    body = {
        "question": _safe_text(state.get("question"))[:4000],
        "context": context,
        "evidence": evidence,
        "constraints": {
            "read_only_only": True,
            "max_rounds": _positive_int(state.get("max_rounds"), 3),
            "max_tool_calls": _positive_int(state.get("max_tool_calls"), DEFAULT_MAX_TOOL_CALLS),
        },
    }
    return [
        {
            "role": "system",
            "content": "Return exactly one documented FINAL or CALL_TOOL JSON action. Tool calls are read-only.",
        },
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, separators=(",", ":"))},
    ]


def _compact_output(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        compact = _safe_mapping(value, depth=0)
    else:
        safe = _safe_value(value, depth=0)
        if safe is _DROP:
            raise ValueError("tool output is not safely serialisable")
        compact = {"value": safe}
    return compact


def _safe_mapping(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= 32:
            break
        key_text = str(key)[:192]
        if _sensitive_key(key_text):
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
                    "payload": _safe_mapping(item.get("payload")),
                    "source": _safe_text(item.get("source"))[:128],
                    "capability_id": _safe_text(item.get("capability_id"))[:192],
                    "confidence": item.get("confidence", 1.0),
                    "materiality": item.get("materiality", 0.0),
                }
                output.append(model_dump(Evidence.model_validate(cleaned)))
            except Exception:
                continue
    return output


def _summarize(payload: Mapping[str, Any]) -> str:
    if not payload:
        return "Tool returned no public fields"
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))[:4000]
    except (TypeError, ValueError):
        return "Tool returned no serialisable public fields"


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("password", "secret", "credential", "access_token", "api_key", "authorization", "provider_url", "endpoint", "raw_", "raw")) or lowered in {"url", "uri", "token"}


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://")) or "://" in lowered or "password=" in lowered or "token=" in lowered


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
        content = _safe_text(item.get("content"))[:4000]
        if role and content:
            output.append({"role": role, "content": content})
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
    return number if number > 0 else fallback


def _nonnegative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0
