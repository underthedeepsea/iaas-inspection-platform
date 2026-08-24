"""Small, synchronous conversation boundary around the investigation graph."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Mapping
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.investigations.models import (
    Conversation,
    ConversationMessage,
    Investigation,
    InvestigationEvent,
    ToolCall,
)
from apps.risks.models import Evidence, Risk
from services.investigation_graph.graph import build_investigation_graph
from services.model_gateway.base import configured_value


MAX_TURN_MESSAGE = 4000
MAX_EVENT_PAYLOAD = 8192
MAX_RESULT_TEXT = 4000
MAX_RESULT_ITEMS = 64
MAX_RESULT_DEPTH = 4
PROMPT_VERSION = "1.0.0"


class ConversationError(Exception):
    """An expected API error with a safe public code and HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class _NoToolsRegistry:
    def resolve_capability(self, capability_id: str, *, claim: str | None = None):
        return None

    def execute_readonly(self, *args: Any, **kwargs: Any):
        return None


def create_conversation(user: Any, payload: Mapping[str, Any]) -> Conversation:
    """Create a Risk-bound conversation using the Risk's environment."""

    if not getattr(user, "is_authenticated", False):
        raise ConversationError("authentication_required", "authentication is required", 401)
    if not isinstance(payload, Mapping):
        raise ConversationError("invalid_json", "request body must be a JSON object")
    context_type = payload.get("context_type")
    if not isinstance(context_type, str):
        raise ConversationError("invalid_field", "context_type is required")
    context_type = context_type.strip().upper()
    if context_type != Conversation.ContextType.RISK:
        raise ConversationError(
            "unsupported_context_type",
            "only RISK conversations are available in this API",
        )
    context_id = _uuid(payload.get("context_id"), "context_id")
    try:
        risk = Risk.objects.select_related("environment", "inspection_item").get(pk=context_id)
    except Risk.DoesNotExist:
        raise ConversationError("not_found", "risk does not exist", 404) from None

    title = payload.get("title")
    if title is None or title == "":
        title = risk.title
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 255:
        raise ConversationError("invalid_field", "title must be a non-empty string of at most 255 characters")
    return Conversation.objects.create(
        environment=risk.environment,
        user=user,
        context_type=Conversation.ContextType.RISK,
        context_id=risk.pk,
        risk=risk,
        title=title.strip(),
    )


def get_conversation(user: Any, conversation_id: Any, *, lock: bool = False) -> Conversation:
    """Return only a conversation owned by ``user``."""

    parsed = _uuid(conversation_id, "conversation_id")
    query = Conversation.objects.select_related("environment", "risk", "investigation")
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=parsed, user=user)
    except Conversation.DoesNotExist:
        raise ConversationError("not_found", "conversation does not exist", 404) from None


def serialize_conversation(conversation: Conversation) -> dict[str, Any]:
    return {
        "conversation_id": str(conversation.pk),
        "id": str(conversation.pk),
        "environment_id": str(conversation.environment_id),
        "context_type": conversation.context_type,
        "context_id": str(conversation.context_id),
        "risk_id": str(conversation.risk_id) if conversation.risk_id else None,
        "investigation_id": str(conversation.investigation_id) if conversation.investigation_id else None,
        "title": conversation.title,
        "status": conversation.status,
        "created_at": _isoformat(conversation.created_at),
    }


def list_messages(user: Any, conversation_id: Any) -> list[dict[str, Any]]:
    conversation = get_conversation(user, conversation_id)
    return [_serialize_message(message) for message in conversation.conversationmessage_set.order_by("created_at", "pk")]


def close_conversation(user: Any, conversation_id: Any) -> Conversation:
    with transaction.atomic():
        conversation = get_conversation(user, conversation_id, lock=True)
        if conversation.status != Conversation.Status.CLOSED:
            conversation.status = Conversation.Status.CLOSED
            conversation.save(update_fields=["status", "updated_at"])
        return conversation


def create_turn(
    user: Any,
    conversation_id: Any,
    payload: Mapping[str, Any],
    *,
    graph_runner: Any | None = None,
    gateway: Any | None = None,
    graph_factory: Any | None = None,
) -> dict[str, Any]:
    """Persist the input, execute the injected graph, then persist its terminal result.

    The first transaction ends before ``graph_runner`` is called.  The final
    transaction is short and contains only sanitized graph data and database
    writes, so no DB lock spans model or tool execution.
    """

    if not getattr(user, "is_authenticated", False):
        raise ConversationError("authentication_required", "authentication is required", 401)
    if not isinstance(payload, Mapping):
        raise ConversationError("invalid_json", "request body must be a JSON object")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > MAX_TURN_MESSAGE:
        raise ConversationError("invalid_field", "message must be a non-empty string of at most 4000 characters")
    allow_tools = payload.get("allow_tools", True)
    if not isinstance(allow_tools, bool):
        raise ConversationError("invalid_field", "allow_tools must be a boolean")
    idempotency_key = _idempotency_key(payload)

    with transaction.atomic():
        conversation = get_conversation(user, conversation_id, lock=True)
        if conversation.status != Conversation.Status.ACTIVE:
            raise ConversationError("conversation_closed", "conversation is closed", 409)
        investigation, user_message, existing_terminal = _start_turn(
            conversation,
            message.strip(),
            idempotency_key=idempotency_key,
        )

    if existing_terminal:
        return _turn_response(conversation, investigation)

    graph_input = _graph_input(conversation, investigation, user_message, allow_tools=allow_tools)
    try:
        if graph_runner is not None:
            raw_result = _invoke_runner(graph_runner, graph_input)
        else:
            raw_result = run_graph(
                graph_input,
                gateway=gateway,
                graph_factory=graph_factory,
                allow_tools=allow_tools,
            )
    except Exception:
        raw_result = {
            "status": "FAILED",
            "summary": "Investigation failed before a result was produced",
            "conclusion": "Investigation failed before a result was produced",
            "facts": [],
            "next_steps": ["Retry the investigation after the provider issue is resolved."],
            "confidence": 0,
            "evidence": [],
            "tool_history": [],
            "rounds_used": 0,
            "tool_calls_used": 0,
            "error_code": "GRAPH_EXECUTION_FAILED",
        }

    final = sanitize_result(raw_result)
    metadata = _model_metadata(gateway, raw_result)
    _persist_turn(conversation.pk, investigation.pk, user_message.pk, final, metadata)
    return _turn_response(conversation, investigation)


def run_graph(
    values: Mapping[str, Any],
    *,
    gateway: Any | None = None,
    graph_factory: Any | None = None,
    allow_tools: bool = True,
) -> Mapping[str, Any]:
    """Run the provider-injected graph synchronously for this request."""

    gateway = gateway or _default_gateway()
    factory = graph_factory or build_investigation_graph
    kwargs = {
        "gateway": gateway,
        "max_rounds": _configured_limit("LLM_MAX_ROUNDS", 3),
        "max_tool_calls": _configured_limit("LLM_MAX_TOOL_CALLS", 5),
    }
    if not allow_tools:
        kwargs["registry"] = _NoToolsRegistry()
    graph = factory(**kwargs)
    return graph.invoke(dict(values))


def events_for_turn(user: Any, conversation_id: Any, turn_id: Any) -> list[InvestigationEvent]:
    conversation = get_conversation(user, conversation_id)
    investigation_id = _turn_uuid(turn_id)
    # Investigation has no owner column.  Every Task 12 event carries the
    # conversation id; checking it here keeps historical turns owner-scoped.
    events = InvestigationEvent.objects.filter(investigation_id=investigation_id).order_by("sequence", "pk")
    owned = [
        event
        for event in events
        if investigation_id == conversation.investigation_id
        or _conversation_id_from_payload(event.payload) == str(conversation.pk)
    ]
    if not owned:
        raise ConversationError("not_found", "turn does not exist", 404)
    return owned


def sanitize_result(value: Any) -> dict[str, Any]:
    """Keep only the graph's bounded public terminal contract."""

    if not isinstance(value, Mapping):
        return _failed_result()
    final_source = value.get("final") if isinstance(value.get("final"), Mapping) else value
    if not isinstance(final_source, Mapping):
        return _failed_result()
    status = final_source.get("status", value.get("status"))
    status = status.value if hasattr(status, "value") else status
    if status not in {"RESOLVED", "UNRESOLVED", "FAILED"}:
        status = "FAILED"
    summary = _safe_text(final_source.get("summary")) or "Investigation did not reach a final answer"
    conclusion = _safe_text(final_source.get("conclusion")) or summary
    facts = _safe_text_list(final_source.get("facts"))
    next_steps = _safe_text_list(final_source.get("next_steps"))
    if status != "RESOLVED" and not next_steps:
        next_steps = ["Collect the missing evidence and retry the investigation."]
    confidence = _safe_float(final_source.get("confidence"), 0)
    evidence = _safe_evidence(final_source.get("evidence"))
    tool_history = _safe_tool_history(final_source.get("tool_history"))
    result = {
        "status": status,
        "summary": summary,
        "conclusion": conclusion,
        "facts": facts,
        "next_steps": next_steps,
        "confidence": confidence,
        "evidence": evidence,
        "tool_history": tool_history,
        "rounds_used": _safe_count(final_source.get("rounds_used", value.get("rounds_used"))),
        "tool_calls_used": _safe_count(final_source.get("tool_calls_used", value.get("tool_calls_used"))),
    }
    code = value.get("error_code", final_source.get("error_code", ""))
    if isinstance(code, str) and _safe_key(code):
        result["error_code"] = code[:64]
    return result


def serialize_event(event: InvestigationEvent) -> dict[str, Any]:
    payload = _safe_json(event.payload, MAX_EVENT_PAYLOAD)
    event_type = event.event_type if _EVENT_TYPE_RE.fullmatch(event.event_type or "") else "turn.error"
    return {
        "id": event.sequence,
        "sequence": event.sequence,
        "event": event_type,
        "event_type": event_type,
        "node_name": event.node_name,
        "status": event.status,
        "data": payload,
        "created_at": _isoformat(event.created_at),
    }


def _start_turn(
    conversation: Conversation,
    message: str,
    *,
    idempotency_key: str | None,
) -> tuple[Investigation, ConversationMessage, bool]:
    investigation = None
    deterministic_id = None
    if idempotency_key:
        deterministic_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"ai-inspect:{conversation.pk}:turn:{idempotency_key}",
        )
        investigation = Investigation.objects.filter(pk=deterministic_id).first()
        if investigation is not None:
            user_message = _existing_user_message(conversation, investigation)
            if user_message is not None and user_message.content != message:
                raise ConversationError(
                    "idempotency_conflict",
                    "idempotency_key is already bound to a different message",
                    409,
                )
            terminal = InvestigationEvent.objects.filter(
                investigation=investigation,
                event_type__in=("turn.completed", "turn.error"),
            ).exists()
            if user_message is None:
                user_message = ConversationMessage.objects.create(
                    conversation=conversation,
                    role=ConversationMessage.Role.USER,
                    content=message,
                    structured_content={},
                )
            return investigation, user_message, terminal

    user_message = ConversationMessage.objects.create(
        conversation=conversation,
        role=ConversationMessage.Role.USER,
        content=message,
        structured_content={},
    )
    risk = conversation.risk
    investigation_kwargs = {
        "risk": risk,
        "trigger_type": Investigation.TriggerType.HUMAN,
        "entry_reason": Investigation.EntryReason.USER_QUESTION,
        "missing_claim": _missing_claim(risk),
        "model_provider": str(configured_value("LLM_PROVIDER", "ollama"))[:32],
        "model_name": str(configured_value("OLLAMA_MODEL", "configured"))[:128],
        "max_rounds": _configured_limit("LLM_MAX_ROUNDS", 3),
        "max_tool_calls": _configured_limit("LLM_MAX_TOOL_CALLS", 5),
    }
    if deterministic_id is not None:
        investigation = Investigation.objects.create(id=deterministic_id, **investigation_kwargs)
    else:
        investigation = Investigation.objects.create(**investigation_kwargs)
    _append_events(
        investigation,
        [
            (
                "turn.started",
                InvestigationEvent.Status.STARTED,
                {"conversation_id": str(conversation.pk), "investigation_id": str(investigation.pk)},
            )
        ],
    )
    return investigation, user_message, False


def _persist_turn(
    conversation_id: uuid.UUID,
    investigation_id: uuid.UUID,
    user_message_id: uuid.UUID,
    result: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> None:
    with transaction.atomic():
        investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
        conversation = Conversation.objects.select_for_update().get(pk=conversation_id)
        terminal_exists = InvestigationEvent.objects.filter(
            investigation=investigation,
            event_type__in=("turn.completed", "turn.error"),
        ).exists()
        if terminal_exists:
            return

        status = result["status"]
        investigation.status = {
            "RESOLVED": Investigation.Status.RESOLVED,
            "UNRESOLVED": Investigation.Status.UNRESOLVED,
            "FAILED": Investigation.Status.FAILED,
        }[status]
        investigation.rounds_used = result["rounds_used"]
        investigation.tool_calls_used = result["tool_calls_used"]
        investigation.conclusion = result["conclusion"]
        investigation.confidence = result["confidence"]
        investigation.started_at = investigation.started_at or timezone.now()
        investigation.finished_at = timezone.now()
        if metadata.get("provider"):
            investigation.model_provider = str(metadata["provider"])[:32]
        if metadata.get("model"):
            investigation.model_name = str(metadata["model"])[:128]
        investigation.save(
            update_fields=[
                "status",
                "rounds_used",
                "tool_calls_used",
                "conclusion",
                "confidence",
                "started_at",
                "finished_at",
                "model_provider",
                "model_name",
                "updated_at",
            ]
        )

        evidence_rows = _persist_evidence(conversation, investigation, result["evidence"])
        user_message = ConversationMessage.objects.get(pk=user_message_id)
        assistant = _existing_assistant(conversation, investigation.pk)
        if assistant is None:
            assistant = ConversationMessage.objects.create(
                conversation=conversation,
                role=ConversationMessage.Role.ASSISTANT,
                content=result["summary"],
                structured_content={
                    "investigation_id": str(investigation.pk),
                    **dict(result),
                    "evidence_ids": [str(row.pk) for row in evidence_rows],
                },
                model_provider=metadata.get("provider"),
                model_name=metadata.get("model"),
                prompt_version=PROMPT_VERSION,
                input_tokens=_safe_count(metadata.get("input_tokens")),
                output_tokens=_safe_count(metadata.get("output_tokens")),
                parent_message=user_message,
            )
        _persist_tool_calls(conversation, investigation, assistant, result["tool_history"], evidence_rows)
        conversation.investigation = investigation
        conversation.save(update_fields=["investigation", "updated_at"])

        events: list[tuple[str, str, Mapping[str, Any]]] = [
            (
                "context.ready",
                InvestigationEvent.Status.INFO,
                {"conversation_id": str(conversation.pk)},
            )
        ]
        for index, history in enumerate(result["tool_history"]):
            outcome = history.get("outcome")
            event_type = "tool.completed" if outcome == "SUCCEEDED" else "tool.failed" if outcome == "FAILED" else "tool.requested"
            events.append(
                (
                    event_type,
                    InvestigationEvent.Status.COMPLETED if outcome == "SUCCEEDED" else InvestigationEvent.Status.FAILED if outcome == "FAILED" else InvestigationEvent.Status.INFO,
                    {
                        "conversation_id": str(conversation.pk),
                        "tool_index": index,
                        "capability_id": history.get("capability_id", ""),
                        "status": history.get("status", "UNKNOWN"),
                        "outcome": outcome or "UNKNOWN",
                        "evidence_key": history.get("evidence_key", ""),
                    },
                )
            )
        for row in evidence_rows:
            events.append(
                (
                    "evidence.created",
                    InvestigationEvent.Status.COMPLETED,
                    {
                        "conversation_id": str(conversation.pk),
                        "evidence_id": str(row.pk),
                        "evidence_key": row.evidence_key,
                        "summary": _safe_text(row.summary),
                    },
                )
            )
        events.extend(
            [
                (
                    "assistant.final",
                    InvestigationEvent.Status.COMPLETED,
                    {"conversation_id": str(conversation.pk), "message_id": str(assistant.pk), "result": dict(result)},
                ),
                (
                    "turn.completed" if status != "FAILED" else "turn.error",
                    InvestigationEvent.Status.COMPLETED if status != "FAILED" else InvestigationEvent.Status.FAILED,
                    {
                        "conversation_id": str(conversation.pk),
                        "message_id": str(assistant.pk),
                        "status": status,
                        "error_code": result.get("error_code", "") if status == "FAILED" else "",
                        "rounds_used": result["rounds_used"],
                        "tool_calls_used": result["tool_calls_used"],
                    },
                ),
            ]
        )
        _append_events(investigation, events)


def _append_events(investigation: Investigation, events: list[tuple[str, str, Mapping[str, Any]]]) -> None:
    """Append events while the investigation row is locked by the caller."""

    last = InvestigationEvent.objects.filter(investigation=investigation).aggregate(Max("sequence"))["sequence__max"] or 0
    for offset, (event_type, status, payload) in enumerate(events, start=1):
        InvestigationEvent.objects.create(
            investigation=investigation,
            sequence=last + offset,
            event_type=event_type,
            node_name="conversation",
            status=status,
            payload=_safe_json(
                {"investigation_id": str(investigation.pk), **dict(payload)},
                MAX_EVENT_PAYLOAD,
            ),
        )


def _persist_evidence(conversation: Conversation, investigation: Investigation, items: list[Mapping[str, Any]]) -> list[Evidence]:
    rows: list[Evidence] = []
    for item in items:
        evidence_key = item["evidence_key"]
        row = Evidence.objects.filter(investigation=investigation, evidence_key=evidence_key).first()
        if row is None:
            row = Evidence.objects.create(
                risk=conversation.risk,
                investigation=investigation,
                evidence_type=Evidence.EvidenceType.TOOL_RESULT,
                evidence_key=evidence_key,
                summary=item["summary"],
                payload=item["payload"],
                source=item["source"],
                confidence=item["confidence"],
                materiality=item["materiality"],
            )
        rows.append(row)
    return rows


def _persist_tool_calls(
    conversation: Conversation,
    investigation: Investigation,
    assistant: ConversationMessage,
    items: list[Mapping[str, Any]],
    evidence_rows: list[Evidence],
) -> None:
    """Best-effort reuse of ToolCall when its required capability FK exists."""

    try:
        from apps.capabilities.models import CapabilityVersion
    except ImportError:
        return
    for index, item in enumerate(items):
        capability_id = item.get("capability_id")
        version = (
            CapabilityVersion.objects.select_related("capability")
            .filter(capability__capability_id=capability_id)
            .order_by("-created_at")
            .first()
        )
        if version is None:
            continue
        outcome = item.get("outcome")
        status = {
            "SUCCEEDED": ToolCall.Status.SUCCEEDED,
            "FAILED": ToolCall.Status.FAILED,
            "REJECTED": ToolCall.Status.REJECTED,
        }.get(outcome, ToolCall.Status.PENDING)
        evidence = next((row for row in evidence_rows if row.evidence_key == item.get("evidence_key")), None)
        ToolCall.objects.get_or_create(
            call_id=f"{investigation.pk}:{index}"[:128],
            defaults={
                "investigation": investigation,
                "conversation": conversation,
                "assistant_message": assistant,
                "capability_version": version,
                "tool_name": capability_id[:192],
                "input_args": item.get("arguments", {}),
                "status": status,
                "result_summary": _safe_text(evidence.summary) if evidence else "",
                "result_payload": evidence.payload if evidence else {},
                "error_code": item.get("error_code") or None,
                "evidence": evidence,
                "finished_at": timezone.now() if status in {ToolCall.Status.SUCCEEDED, ToolCall.Status.FAILED, ToolCall.Status.REJECTED} else None,
            },
        )


def _graph_input(conversation: Conversation, investigation: Investigation, message: ConversationMessage, *, allow_tools: bool) -> dict[str, Any]:
    risk = conversation.risk
    context: dict[str, Any] = {
        "conversation_id": str(conversation.pk),
        "investigation_id": str(investigation.pk),
        "allow_tools": allow_tools,
    }
    if risk is not None:
        context.update(
            {
                "risk_id": str(risk.pk),
                "risk_key": _safe_text(risk.risk_key),
                "title": _safe_text(risk.title),
                "domain": _safe_text(risk.domain),
                "severity": _safe_text(risk.severity),
                "status": _safe_text(risk.status),
                "current_conclusion": _safe_text(risk.current_conclusion),
                "impact_summary": _safe_text(risk.impact_summary),
                "recommendation": _safe_text(risk.recommendation),
            }
        )
        if risk.inspection_item_id:
            item = risk.inspection_item
            context["inspection_item"] = {
                "code": _safe_text(item.code),
                "name": _safe_text(item.name),
                "domain": _safe_text(item.domain),
                "required_claims": _safe_text_list(item.required_claims),
                "resolved_claims": _safe_text_list(item.resolved_claims),
            }
    messages = ConversationMessage.objects.filter(conversation=conversation).order_by("created_at", "pk")
    return {
        "question": message.content,
        "context": context,
        "missing_claim": investigation.missing_claim or "",
        "messages": [{"role": item.role} for item in messages],
        "max_rounds": investigation.max_rounds,
        "max_tool_calls": investigation.max_tool_calls if allow_tools else 1,
    }


def _existing_user_message(conversation: Conversation, investigation: Investigation) -> ConversationMessage | None:
    for message in ConversationMessage.objects.filter(conversation=conversation, role=ConversationMessage.Role.USER).order_by("-created_at", "-pk"):
        if message.created_at and investigation.created_at and message.created_at <= investigation.created_at:
            return message
    return None


def _existing_assistant(conversation: Conversation, investigation_id: uuid.UUID) -> ConversationMessage | None:
    for message in ConversationMessage.objects.filter(conversation=conversation, role=ConversationMessage.Role.ASSISTANT).order_by("-created_at", "-pk"):
        if isinstance(message.structured_content, Mapping) and message.structured_content.get("investigation_id") == str(investigation_id):
            return message
    return None


def _turn_response(conversation: Conversation, investigation: Investigation) -> dict[str, Any]:
    return {
        "turn_id": str(investigation.pk),
        "investigation_id": str(investigation.pk),
        "events_url": f"/api/v1/conversations/{conversation.pk}/turns/{investigation.pk}/events",
    }


def _model_metadata(gateway: Any, raw_result: Any) -> dict[str, Any]:
    metadata = {}
    for source in (gateway, raw_result if isinstance(raw_result, Mapping) else {}):
        if not source:
            continue
        provider = getattr(source, "provider_name", None) or getattr(source, "provider", None)
        model = getattr(source, "model", None) or getattr(source, "model_name", None)
        if isinstance(source, Mapping):
            provider = source.get("provider", source.get("model_provider", provider))
            model = source.get("model", source.get("model_name", model))
            usage = source.get("usage")
            if isinstance(usage, Mapping):
                metadata["input_tokens"] = _safe_count(usage.get("prompt_tokens"))
                metadata["output_tokens"] = _safe_count(usage.get("completion_tokens"))
            metadata["input_tokens"] = _safe_count(source.get("input_tokens", metadata.get("input_tokens")))
            metadata["output_tokens"] = _safe_count(source.get("output_tokens", metadata.get("output_tokens")))
        if isinstance(provider, str) and _safe_key(provider):
            metadata["provider"] = provider[:32]
        if isinstance(model, str) and model.strip() and not _looks_sensitive(model):
            metadata["model"] = model.strip()[:128]
    return metadata


def _default_gateway() -> Any:
    provider = str(configured_value("LLM_PROVIDER", "ollama")).lower().strip()
    if provider in {"openai", "openai_compatible", "openai-compatible"}:
        from services.model_gateway.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider()
    from services.model_gateway.ollama import OllamaProvider

    return OllamaProvider()


def _invoke_runner(runner: Any, values: Mapping[str, Any]) -> Any:
    if hasattr(runner, "invoke"):
        return runner.invoke(dict(values))
    if callable(runner):
        return runner(dict(values))
    raise TypeError("graph_runner must be callable or expose invoke")


def _idempotency_key(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("idempotency_key")
    if value is None:
        value = payload.get("turn_key")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ConversationError("invalid_field", "idempotency_key must be a non-empty string of at most 128 characters")
    return value.strip()


def _missing_claim(risk: Risk | None) -> str | None:
    if risk is None or not risk.inspection_item_id:
        return None
    required = risk.inspection_item.required_claims
    resolved = set(risk.inspection_item.resolved_claims or [])
    if isinstance(required, list):
        for claim in required:
            if isinstance(claim, str) and claim.strip() and claim not in resolved and _safe_key(claim.strip()):
                return claim.strip()[:192]
    return None


def _serialize_message(message: ConversationMessage) -> dict[str, Any]:
    return {
        "message_id": str(message.pk),
        "id": str(message.pk),
        "role": message.role,
        "content": message.content,
        "structured_content": _safe_json(message.structured_content, MAX_EVENT_PAYLOAD),
        "model_provider": message.model_provider,
        "model_name": message.model_name,
        "prompt_version": message.prompt_version,
        "input_tokens": message.input_tokens,
        "output_tokens": message.output_tokens,
        "latency_ms": message.latency_ms,
        "created_at": _isoformat(message.created_at),
    }


def _safe_evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:MAX_RESULT_ITEMS]:
        if not isinstance(item, Mapping):
            continue
        evidence_key = item.get("evidence_key")
        source = item.get("source")
        capability_id = item.get("capability_id")
        if not all(isinstance(entry, str) and _safe_key(entry) for entry in (evidence_key, source, capability_id)):
            continue
        result.append(
            {
                "evidence_key": evidence_key[:192],
                "summary": _safe_text(item.get("summary"))[:MAX_RESULT_TEXT],
                "payload": _safe_json(item.get("payload"), 4096),
                "source": source[:128],
                "capability_id": capability_id[:192],
                "confidence": _safe_float(item.get("confidence"), 1),
                "materiality": _safe_float(item.get("materiality"), 0),
            }
        )
    return result


def _safe_tool_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:MAX_RESULT_ITEMS]:
        if not isinstance(item, Mapping) or not isinstance(item.get("capability_id"), str) or not _safe_key(item["capability_id"]):
            continue
        result.append(
            {
                "capability_id": item["capability_id"][:192],
                "arguments": _safe_json(item.get("arguments"), 4096),
                "reason": _safe_text(item.get("reason"))[:2000],
                "status": _safe_label(item.get("status")),
                "outcome": _safe_label(item.get("outcome")),
                "error_code": _safe_error_code(item.get("error_code")),
                "evidence_key": _safe_text(item.get("evidence_key"))[:192],
            }
        )
    return result


def _safe_json(value: Any, limit: int, depth: int = 0) -> Any:
    if depth > MAX_RESULT_DEPTH:
        return {}
    if value is None or isinstance(value, (bool, int)):
        result = value
    elif isinstance(value, float):
        result = value if math.isfinite(value) else None
    elif isinstance(value, str):
        result = _safe_text(value)[:1000]
    elif isinstance(value, Mapping):
        result = {}
        for key, item in list(sorted(value.items(), key=lambda pair: str(pair[0])))[:MAX_RESULT_ITEMS]:
            key_text = str(key)[:192]
            if not _safe_key(key_text):
                continue
            safe = _safe_json(item, limit, depth + 1)
            if safe is not _DROP:
                result[key_text] = safe
    elif isinstance(value, list):
        result = [_safe_json(item, limit, depth + 1) for item in value[:MAX_RESULT_ITEMS]]
    else:
        return {}
    try:
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError):
        return {}
    if len(encoded) <= limit:
        return result
    if isinstance(result, dict):
        while result and len(json.dumps(result, ensure_ascii=True, sort_keys=True).encode()) > limit:
            result.pop(next(reversed(result)))
        return result
    if isinstance(result, list):
        while result and len(json.dumps(result, ensure_ascii=True, sort_keys=True).encode()) > limit:
            result.pop()
        return result
    return ""


_DROP = object()
_SENSITIVE_KEY = re.compile(r"(?i)(?:api[\W_]*key|access[\W_]*key|token|secret|password|passwd|credential|authorization|cookie|private[\W_]*key|raw|endpoint|url|uri)")
_SAFE_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}\Z")
_EVENT_TYPE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SENSITIVE_VALUE = re.compile(r"(?i)(?:[A-Za-z][A-Za-z0-9+.-]*://|\b(?:api[_ -]?key|password|passwd|token|secret|authorization)\s*=|bearer\s+)")


def _safe_key(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_KEY_RE.fullmatch(value.strip())) and not _SENSITIVE_KEY.search(value)


def _looks_sensitive(value: Any) -> bool:
    return isinstance(value, str) and bool(_SENSITIVE_VALUE.search(value))


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return "[redacted]" if _looks_sensitive(value) else value


def _safe_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_safe_text(item)[:1000] for item in value[:MAX_RESULT_ITEMS] if isinstance(item, str) and item.strip()]


def _safe_label(value: Any) -> str:
    value = str(value or "").upper()
    return value if _safe_key(value) else "UNKNOWN"


def _safe_error_code(value: Any) -> str:
    return value[:64] if isinstance(value, str) and _safe_key(value) else ""


def _safe_float(value: Any, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(value, 0), 1) if math.isfinite(value) else default


def _safe_count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, min(int(value), 64))
    except (TypeError, ValueError):
        return 0


def _configured_limit(name: str, default: int) -> int:
    return max(1, min(_safe_count(configured_value(name, default)) or default, 64))


def _failed_result() -> dict[str, Any]:
    return {
        "status": "FAILED",
        "summary": "Investigation failed before a safe result was produced",
        "conclusion": "Investigation failed before a safe result was produced",
        "facts": [],
        "next_steps": ["Retry the investigation after the provider issue is resolved."],
        "confidence": 0,
        "evidence": [],
        "tool_history": [],
        "rounds_used": 0,
        "tool_calls_used": 0,
        "error_code": "GRAPH_RESULT_INVALID",
    }


def _uuid(value: Any, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ConversationError("invalid_field", f"{field} must be a UUID") from None


def _turn_uuid(value: Any) -> uuid.UUID:
    text = str(value)
    if text.startswith("turn_"):
        text = text[5:]
    return _uuid(text, "turn_id")


def _conversation_id_from_payload(payload: Any) -> str | None:
    return payload.get("conversation_id") if isinstance(payload, Mapping) else None


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None
