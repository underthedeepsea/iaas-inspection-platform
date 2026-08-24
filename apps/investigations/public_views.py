"""Bounded, session-authenticated projections for investigations."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.api.pagination import paginate
from apps.audits.services import record_event

from .models import Conversation, Investigation, InvestigationEvent, ToolCall


_EVENT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SAFE_KEY_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}\Z")
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[\W_]*key|access[\W_]*key|token|secret|password|passwd|credential|authorization|cookie|private[\W_]*key|raw|provider|model|endpoint|url|uri)"
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:[A-Za-z][A-Za-z0-9+.-]*://|\b(?:api[_ -]?key|password|passwd|token|secret|authorization)\s*=|bearer\s+)"
)
_MAX_DEPTH = 3
_MAX_ITEMS = 64
_MAX_BYTES = 4096


def detail(request, investigation_id):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "investigation only accepts GET", 405)
    investigation = _owned(request.user, investigation_id)
    if investigation is None:
        return _not_found("investigation does not exist")
    return JsonResponse(_serialize_investigation(investigation))


def events(request, investigation_id):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "events only accepts GET", 405)
    investigation = _owned(request.user, investigation_id)
    if investigation is None:
        return _not_found("investigation does not exist")
    rows = InvestigationEvent.objects.filter(investigation=investigation).order_by(
        "sequence", "pk"
    )
    return paginate(rows, request, _serialize_event)


def tool_calls(request, investigation_id):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "tool-calls only accepts GET", 405)
    investigation = _owned(request.user, investigation_id)
    if investigation is None:
        return _not_found("investigation does not exist")
    rows = (
        ToolCall.objects.filter(investigation=investigation)
        .select_related("capability_version__capability")
        .order_by("created_at", "pk")
    )
    return paginate(rows, request, _serialize_tool_call)


def cancel(request, investigation_id):
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "cancel only accepts POST", 405)
    try:
        payload = parse_json_object(request)
        if payload:
            return _error(
                "VALIDATION_ERROR",
                "investigation cancellation does not accept a request body",
                400,
            )
    except APIRequestError as error:
        return _error(error.code, error.message, 400, error.details)

    with transaction.atomic():
        investigation = _owned(request.user, investigation_id, lock=True)
        if investigation is None:
            return _not_found("investigation does not exist")
        if investigation.status not in {
            Investigation.Status.CREATED,
            Investigation.Status.RUNNING,
        }:
            return _error(
                "INVALID_INVESTIGATION_TRANSITION",
                "only CREATED or RUNNING investigations can be cancelled",
                409,
                {"status": investigation.status},
            )
        before = investigation.status
        investigation.status = Investigation.Status.CANCELLED
        investigation.finished_at = timezone.now()
        investigation.claim_token = None
        investigation.claim_heartbeat_at = None
        investigation.save(
            update_fields=[
                "status",
                "finished_at",
                "claim_token",
                "claim_heartbeat_at",
                "updated_at",
            ]
        )
        record_event(
            actor=request.user,
            environment=_investigation_environment(investigation),
            event_type="investigation.cancelled",
            object_type="Investigation",
            object_id=investigation.pk,
            payload={"from_status": before, "to_status": investigation.status},
        )
    return JsonResponse(_serialize_investigation(investigation))


def _owned(user, investigation_id, *, lock=False):
    parsed = _uuid(investigation_id)
    if parsed is None:
        return None
    conversations = Conversation.objects.filter(
        user=user, investigation_id=parsed
    )
    if not conversations.exists():
        return None
    query = Investigation.objects
    if lock:
        query = query.select_for_update(of=("self",))
    else:
        query = query.select_related("risk")
    return query.filter(pk=parsed).first()


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _investigation_environment(investigation):
    if investigation.risk_id and investigation.risk is not None:
        return investigation.risk.environment
    conversation = (
        Conversation.objects.select_related("environment")
        .filter(investigation_id=investigation.pk)
        .first()
    )
    return conversation.environment if conversation is not None else None


def _serialize_investigation(investigation):
    return {
        "investigation_id": str(investigation.pk),
        "id": str(investigation.pk),
        "status": investigation.status,
        "entry_reason": investigation.entry_reason,
        "missing_claim": investigation.missing_claim,
        "conclusion": _text(investigation.conclusion, 4000),
        "confidence": _number(investigation.confidence),
        "max_rounds": investigation.max_rounds,
        "rounds_used": investigation.rounds_used,
        "max_tool_calls": investigation.max_tool_calls,
        "tool_calls_used": investigation.tool_calls_used,
        "used_tools": investigation.tool_calls_used,
        "started_at": _iso(investigation.started_at),
        "finished_at": _iso(investigation.finished_at),
    }


def _serialize_event(event):
    event_type = event.event_type if _EVENT_RE.fullmatch(event.event_type or "") else "turn.error"
    data = _public_json(event.payload)
    return {
        "id": event.sequence,
        "sequence": event.sequence,
        "event": event_type,
        "event_type": event_type,
        "node_name": _text(event.node_name, 64),
        "status": event.status,
        "data": data,
        "created_at": _iso(event.created_at),
    }


def _serialize_tool_call(call):
    capability_id = ""
    if call.capability_version_id and call.capability_version is not None:
        capability_id = call.capability_version.capability.capability_id
    return {
        "tool_call_id": str(call.pk),
        "id": str(call.pk),
        "call_id": _text(call.call_id, 128),
        "capability_id": _safe_label(capability_id),
        "tool_name": _safe_label(call.tool_name),
        "status": call.status,
        "started_at": _iso(call.started_at),
        "finished_at": _iso(call.finished_at),
        "duration_ms": call.duration_ms,
        "result_summary": _text(call.result_summary, 2000),
        "error_code": _safe_label(call.error_code),
    }


def _public_json(value, depth=0):
    if depth > _MAX_DEPTH:
        return {}
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        return "[redacted]" if _SENSITIVE_TEXT_RE.search(value) else value[:1000]
    if isinstance(value, Mapping):
        result = {}
        for key, item in list(sorted(value.items(), key=lambda pair: str(pair[0])))[:_MAX_ITEMS]:
            key = str(key)[:192]
            if _SENSITIVE_KEY_RE.search(key):
                continue
            safe = _public_json(item, depth + 1)
            result[key] = safe
        return _fit(result)
    if isinstance(value, list):
        return _fit([_public_json(item, depth + 1) for item in value[:_MAX_ITEMS]])
    return {}


def _fit(value):
    try:
        while len(json.dumps(value, ensure_ascii=True, sort_keys=True).encode()) > _MAX_BYTES:
            if isinstance(value, dict) and value:
                value.pop(next(reversed(value)))
            elif isinstance(value, list) and value:
                value.pop()
            else:
                return {}
    except (TypeError, ValueError):
        return {}
    return value


def _safe_label(value):
    value = str(value or "")
    return value[:192] if _SAFE_KEY_RE.fullmatch(value) and not _SENSITIVE_KEY_RE.search(value) else ""


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return "[redacted]" if _SENSITIVE_TEXT_RE.search(value) else value[:limit]


def _number(value):
    return float(value) if value is not None else None


def _iso(value):
    return value.isoformat() if value is not None else None


def _not_found(message):
    return _error("NOT_FOUND", message, 404)


def _error(code, message, status, details=None):
    return api_error(code, message, status=status, details=details)


investigation_detail = detail
investigation_events = events
investigation_tool_calls = tool_calls
cancel_investigation = cancel


__all__ = [
    "cancel",
    "cancel_investigation",
    "detail",
    "events",
    "investigation_detail",
    "investigation_events",
    "investigation_tool_calls",
    "tool_calls",
]
