import json
import re
import uuid
from functools import wraps

from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.api.pagination import paginate
from apps.core.models import Environment
from apps.inspections.models import InspectionRun, ResourceType
from apps.investigations.services.context_builder import (
    build_resource_run_context,
    build_resource_type_context,
)
from apps.investigations import public_views

from .models import Conversation, Investigation, InvestigationEvent
from .services.runtime import run_resource_investigation


class ResourceInvestigationError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def _boundary(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ResourceInvestigationError as error:
            return api_error(error.code, error.message, status=error.status, details=error.details)
        except APIRequestError as error:
            return api_error(error.code, error.message, status=400, details=error.details)
        except ValueError as error:
            return api_error("VALIDATION_ERROR", str(error), status=400)

    return wrapped


def _endpoint(methods):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            auth_error = require_role(request, "viewer")
            if auth_error is not None:
                return auth_error
            if request.method not in methods:
                return api_error("METHOD_NOT_ALLOWED", "unsupported method", status=405)
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


@_boundary
@_endpoint({"POST"})
def create_resource_investigation(request, resource_type_code):
    payload = parse_json_object(request)
    _reject_unknown(payload, {"context_type", "environment_id", "inspection_run_id", "date_from", "date_to"})
    resource_type = _resource_type(resource_type_code)
    context_type = str(payload.get("context_type") or "").strip().upper()
    if context_type not in {
        Conversation.ContextType.RESOURCE_TYPE,
        Conversation.ContextType.RESOURCE_RUN,
    }:
        raise ResourceInvestigationError(
            "UNSUPPORTED_CONTEXT_TYPE",
            "context_type must be RESOURCE_TYPE or RESOURCE_RUN",
            status=400,
        )
    run = None
    if context_type == Conversation.ContextType.RESOURCE_RUN:
        run_id = _uuid(payload.get("inspection_run_id"), "inspection_run_id")
        try:
            run = InspectionRun.objects.get(pk=run_id)
        except InspectionRun.DoesNotExist:
            raise ResourceInvestigationError("NOT_FOUND", "inspection run does not exist", status=404) from None
        requested_environment = _environment(payload.get("environment_id"), required=False)
        if requested_environment is not None and requested_environment.pk != run.environment_id:
            raise ResourceInvestigationError(
                "ENVIRONMENT_MISMATCH",
                "inspection run belongs to another environment",
                status=403,
            )
        resolved_codes = ((run.config_snapshot or {}).get("resolved_scope") or {}).get("resource_types") or []
        if resource_type.code not in resolved_codes:
            raise ResourceInvestigationError(
                "RESOURCE_SCOPE_MISMATCH",
                "resource type was not part of the inspection run scope",
                status=400,
            )
        environment = run.environment
        context = build_resource_run_context(
            resource_type_code=resource_type.code,
            inspection_run_id=run.pk,
        )
        context_id = run.pk
    else:
        environment = _environment(payload.get("environment_id"), required=True)
        context = build_resource_type_context(
            environment_id=environment.pk,
            resource_type_code=resource_type.code,
            date_from=payload.get("date_from"),
            date_to=payload.get("date_to"),
        )
        context_id = resource_type.pk
    with transaction.atomic():
        investigation = Investigation.objects.create(
            inspection_item_run=(
                run.item_runs.filter(inspection_item__resource_types__resource_type=resource_type).first()
                if run is not None
                else None
            ),
            trigger_type=Investigation.TriggerType.HUMAN,
            status=Investigation.Status.RUNNING,
            entry_reason=Investigation.EntryReason.TREND_GAP,
            model_provider="resource",
            model_name="bounded",
            started_at=timezone.now(),
        )
        Conversation.objects.create(
            environment=environment,
            user=request.user,
            context_type=context_type,
            context_id=context_id,
            investigation=investigation,
            title=f"{resource_type.name} AI 分析",
        )
    investigation = run_resource_investigation(investigation, context)
    return JsonResponse(
        {
            "investigation_id": str(investigation.pk),
            "id": str(investigation.pk),
            "status": investigation.status,
            "context_type": context_type,
            "events_url": f"/api/v1/investigations/{investigation.pk}/events",
        },
        status=201,
    )


@_boundary
@_endpoint({"GET"})
def resource_investigations(request, resource_type_code):
    resource_type = _resource_type(resource_type_code)
    rows = (
        Investigation.objects.filter(
            conversation__user=request.user,
            conversation__context_type=Conversation.ContextType.RESOURCE_TYPE,
            conversation__context_id=resource_type.pk,
        )
        .order_by("-created_at", "-pk")
        .distinct()
    )
    return paginate(rows, request, _serialize_investigation)


def resource_investigation_collection(request, resource_type_code):
    if request.method == "POST":
        return create_resource_investigation(request, resource_type_code)
    return resource_investigations(request, resource_type_code)


@_boundary
@_endpoint({"GET"})
def investigation_events(request, investigation_id):
    # Keep the existing JSON event projection for non-resource investigations;
    # resource investigations use this route for replayable SSE.
    investigation = _owned_investigation(request, investigation_id)
    if investigation is None:
        raise ResourceInvestigationError("NOT_FOUND", "investigation does not exist", status=404)
    if not Conversation.objects.filter(
        investigation=investigation,
        context_type__in=(Conversation.ContextType.RESOURCE_TYPE, Conversation.ContextType.RESOURCE_RUN),
    ).exists():
        return public_views.events(request, investigation_id)
    raw_last_id = request.META.get("HTTP_LAST_EVENT_ID", "")
    if raw_last_id and not re.fullmatch(r"0|[1-9][0-9]*", raw_last_id):
        raise APIRequestError(
            "VALIDATION_ERROR",
            "Last-Event-ID must be a canonical non-negative integer",
            details={"field": "Last-Event-ID"},
        )
    rows = InvestigationEvent.objects.filter(
        investigation=investigation,
        sequence__gt=int(raw_last_id or 0),
    ).order_by("sequence", "pk")

    def stream():
        for row in rows:
            envelope = {
                "sequence": row.sequence,
                "event_type": row.event_type,
                "status": row.status,
                "payload": row.payload or {},
            }
            yield f"id: {row.sequence}\nevent: {row.event_type}\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"

    response = StreamingHttpResponse(stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _owned_investigation(request, investigation_id):
    parsed = _uuid(investigation_id, "investigation_id")
    if parsed is None:
        return None
    if not Conversation.objects.filter(investigation_id=parsed, user=request.user).exists():
        return None
    return Investigation.objects.filter(pk=parsed).first()


def _serialize_investigation(investigation):
    return {
        "investigation_id": str(investigation.pk),
        "id": str(investigation.pk),
        "status": investigation.status,
        "entry_reason": investigation.entry_reason,
        "conclusion": investigation.conclusion,
        "confidence": float(investigation.confidence) if investigation.confidence is not None else None,
        "started_at": investigation.started_at.isoformat() if investigation.started_at else None,
        "finished_at": investigation.finished_at.isoformat() if investigation.finished_at else None,
    }


def _resource_type(code):
    try:
        return ResourceType.objects.get(code=str(code).upper(), enabled=True)
    except ResourceType.DoesNotExist:
        raise ResourceInvestigationError("RESOURCE_TYPE_NOT_FOUND", "resource type does not exist", status=404) from None


def _environment(value, *, required):
    if value in (None, ""):
        if required:
            raise APIRequestError("VALIDATION_ERROR", "environment_id is required", details={"field": "environment_id"})
        return None
    parsed = _uuid(value, "environment_id")
    try:
        return Environment.objects.get(pk=parsed)
    except Environment.DoesNotExist:
        raise ResourceInvestigationError("NOT_FOUND", "environment does not exist", status=404) from None


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a UUID", details={"field": field}) from None


def _reject_unknown(payload, allowed):
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise APIRequestError(
            "VALIDATION_ERROR",
            "request contains unsupported fields",
            details={"fields": unknown},
        )


__all__ = [
    "create_resource_investigation",
    "investigation_events",
    "resource_investigation_collection",
    "resource_investigations",
]
