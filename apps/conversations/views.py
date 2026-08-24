"""Authenticated JSON and SSE views for conversations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from django.http import JsonResponse, StreamingHttpResponse

from . import services


def collection(request):
    if request.method != "POST":
        return _error("method_not_allowed", "conversations only accepts POST", 405)
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    try:
        conversation = services.create_conversation(request.user, _body(request))
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    return JsonResponse(services.serialize_conversation(conversation), status=201)


def detail(request, conversation_id):
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method == "GET":
        try:
            conversation = services.get_conversation(request.user, conversation_id)
        except services.ConversationError as error:
            return _error(error.code, error.message, error.status)
        return JsonResponse(services.serialize_conversation(conversation))
    if request.method == "POST":
        try:
            conversation = services.close_conversation(request.user, conversation_id)
        except services.ConversationError as error:
            return _error(error.code, error.message, error.status)
        return JsonResponse(services.serialize_conversation(conversation))
    return _error("method_not_allowed", "unsupported conversation method", 405)


def messages(request, conversation_id):
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method != "GET":
        return _error("method_not_allowed", "messages only accepts GET", 405)
    try:
        values = services.list_messages(request.user, conversation_id)
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    return JsonResponse({"conversation_id": str(conversation_id), "messages": values})


def turns(request, conversation_id):
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method != "POST":
        return _error("method_not_allowed", "turns only accepts POST", 405)
    try:
        payload = _body(request)
        if "idempotency_key" not in payload and request.META.get("HTTP_IDEMPOTENCY_KEY"):
            payload["idempotency_key"] = request.META["HTTP_IDEMPOTENCY_KEY"]
        values = services.create_turn(request.user, conversation_id, payload)
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    return JsonResponse(values, status=202)


def events(request, conversation_id, turn_id):
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method != "GET":
        return _error("method_not_allowed", "events only accepts GET", 405)
    try:
        # Parse before opening a query so malformed cursors have no side effects.
        from .sse import parse_last_event_id

        last_event_id = parse_last_event_id(request.META.get("HTTP_LAST_EVENT_ID"))
        event_rows = services.events_for_turn(request.user, conversation_id, turn_id)
        # Resolve ownership and the event snapshot before returning the response;
        # otherwise a lazy generator would turn a cross-owner request into a
        # misleading 200 after the view had already returned.
        from .sse import replay_event_rows

        stream = replay_event_rows(event_rows, last_event_id)
        response = StreamingHttpResponse(stream, content_type="text/event-stream")
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    response["Cache-Control"] = "no-store"
    response["X-Accel-Buffering"] = "no"
    return response


def close(request, conversation_id):
    return detail(request, conversation_id)


def _authenticate(request):
    if not getattr(getattr(request, "user", None), "is_authenticated", False):
        return _error("authentication_required", "authentication is required", 401)
    return None


def _body(request) -> dict[str, Any]:
    try:
        value = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise services.ConversationError("invalid_json", "request body must be valid JSON") from None
    if not isinstance(value, Mapping):
        raise services.ConversationError("invalid_json", "request body must be a JSON object")
    return dict(value)


def _error(code: str, message: str, status: int):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)
