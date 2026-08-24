"""Authenticated JSON and SSE views for conversations."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse

from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.audits.services import record_event

from . import services


def collection(request):
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "conversations only accepts POST", 405)
    try:
        with transaction.atomic():
            conversation = services.create_conversation(request.user, _body(request))
            record_event(
                actor=request.user,
                environment=conversation.environment,
                event_type="conversation.created",
                object_type="Conversation",
                object_id=conversation.pk,
                payload={"context_type": conversation.context_type},
            )
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    except Exception:
        return _error("INTERNAL_ERROR", "the conversation could not be created", 500)
    return JsonResponse(services.serialize_conversation(conversation), status=201)


def detail(request, conversation_id):
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "conversation detail only accepts GET", 405)
    try:
        conversation = services.get_conversation(request.user, conversation_id)
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    return JsonResponse(services.serialize_conversation(conversation))


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
    auth_error = _authenticate(request)
    if auth_error:
        return auth_error
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "close only accepts POST", 405)
    try:
        # Keep the domain mutation and its public audit row in one outer
        # transaction.  ``close_conversation`` uses a nested savepoint,
        # so this view owns the commit boundary without duplicating the
        # service's lifecycle logic.
        with transaction.atomic():
            before = services.get_conversation(request.user, conversation_id, lock=True)
            conversation = services.close_conversation(request.user, conversation_id)
            if before.status != services.Conversation.Status.CLOSED:
                record_event(
                    actor=request.user,
                    environment=conversation.environment,
                    event_type="conversation.closed",
                    object_type="Conversation",
                    object_id=conversation.pk,
                    payload={"from_status": before.status, "to_status": conversation.status},
                )
    except services.ConversationError as error:
        return _error(error.code, error.message, error.status)
    except Exception:
        return _error("INTERNAL_ERROR", "the conversation could not be closed", 500)
    return JsonResponse(services.serialize_conversation(conversation))


def _authenticate(request):
    if not getattr(getattr(request, "user", None), "is_authenticated", False):
        return _error("AUTH_REQUIRED", "authentication is required", 401)
    return None


def _body(request) -> dict[str, Any]:
    try:
        value = parse_json_object(request)
    except APIRequestError:
        raise services.ConversationError("invalid_json", "request body must be valid JSON") from None
    return dict(value)


def _error(code: str, message: str, status: int):
    # Preserve the SSE cursor's established private code while all public
    # conversation errors use the shared stable envelope.
    mapped = {
        "authentication_required": "AUTH_REQUIRED",
        "invalid_json": "VALIDATION_ERROR",
        "invalid_field": "VALIDATION_ERROR",
        "not_found": "NOT_FOUND",
        "conversation_closed": "INVALID_RISK_TRANSITION",
        "unsupported_context_type": "VALIDATION_ERROR",
    }.get(code, code if code == "invalid_last_event_id" else str(code).upper())
    return api_error(mapped, message, status=status)
