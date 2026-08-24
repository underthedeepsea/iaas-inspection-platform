"""Authenticated operations and risk API views.

The slice intentionally stays thin: query/filter/HTTP validation lives here,
while lifecycle and investigation mutations remain in their domain services.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from datetime import date, timedelta
from functools import wraps

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_json_object, parse_positive_int
from apps.api.pagination import paginate
from apps.audits.services import record_event
from apps.core.models import Environment
from apps.inspections.models import (
    DailySnapshot,
    Finding,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
    Severity,
)
from apps.investigations.models import Conversation, Investigation
from apps.risks.models import Evidence, Risk, RiskObservation, RiskStatusHistory
from apps.risks.services.lifecycle import ACTIVE_RISK_STATUSES, mark_handled as lifecycle_mark_handled
from apps.risks.services.lifecycle import transition_risk
from apps.risks.services.reverify import reverify_pending_risks

from .serializers import (
    serialize_capability_binding,
    serialize_evidence,
    serialize_finding,
    serialize_history,
    serialize_inspection_item,
    serialize_item_run,
    serialize_risk,
    serialize_run,
    serialize_snapshot,
)


class PublicAPIError(Exception):
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
        except PublicAPIError as error:
            return api_error(error.code, error.message, status=error.status, details=error.details)
        except APIRequestError as error:
            return api_error(error.code, error.message, status=400, details=error.details)
        except ObjectDoesNotExist:
            return api_error("NOT_FOUND", "the requested resource does not exist", status=404)
        except IntegrityError:
            return api_error("INVALID_RISK_TRANSITION", "the requested mutation conflicted with persisted state", status=409)
        except ValueError as error:
            return api_error("VALIDATION_ERROR", str(error) or "the request is invalid", status=400)
        except Exception:
            return api_error("INTERNAL_ERROR", "the request could not be completed", status=500)

    return wrapped


def _endpoint(role, methods):
    methods = frozenset(methods)

    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            auth_error = require_role(request, role)
            if auth_error is not None:
                return auth_error
            if request.method not in methods:
                return api_error(
                    "METHOD_NOT_ALLOWED",
                    f"this endpoint only accepts {'/'.join(sorted(methods))}",
                    status=405,
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a UUID", details={"field": field}) from None


def _date(value, field):
    if not isinstance(value, str):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO date", details={"field": field})
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO date", details={"field": field}) from None


def _text(value, field, *, required=False, limit=2000):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a non-empty string", details={"field": field})
    value = value.strip()
    if len(value) > limit:
        raise APIRequestError("VALIDATION_ERROR", f"{field} is too long", details={"field": field})
    return value


def _reject_unknown(payload, allowed):
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise APIRequestError(
            "VALIDATION_ERROR",
            "request contains unsupported fields",
            details={"fields": unknown},
        )


def _query_list(request, key, *, limit=32):
    raw = request.GET.get(key)
    if raw in (None, ""):
        return None
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if not values or len(values) > limit:
        raise APIRequestError("VALIDATION_ERROR", f"{key} contains too many values", details={"field": key})
    return values


def _choice_filter(values, enum, field):
    if not values:
        return values
    allowed = set(enum.values)
    normalized = [value.upper() for value in values]
    if any(value not in allowed for value in normalized):
        raise APIRequestError("VALIDATION_ERROR", f"invalid {field}", details={"field": field})
    return normalized


def _query_bool(request, key):
    raw = request.GET.get(key)
    if raw is None:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise APIRequestError("VALIDATION_ERROR", f"{key} must be true or false", details={"field": key})


def _query_page_limit(request, *, default=50, maximum=100):
    value = request.GET.get("limit")
    return parse_positive_int(value, default=default, maximum=maximum)


def _paginate(request, queryset, serializer):
    return paginate(queryset, request, serializer)


def _environment(value=None, *, required=False):
    if value in (None, ""):
        if required:
            raise APIRequestError("VALIDATION_ERROR", "environment_id is required", details={"field": "environment_id"})
        return None
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        parsed = None
    query = Environment.objects
    try:
        if parsed is not None:
            return query.get(pk=parsed)
        return query.get(slug=str(value))
    except Environment.DoesNotExist:
        raise PublicAPIError("NOT_FOUND", "environment does not exist", status=404)


def _environment_for_dashboard(request):
    return _environment(request.GET.get("environment"))


def _lookup(model, value, field="id"):
    parsed = _uuid(value, field)
    try:
        return model.objects.get(pk=parsed)
    except model.DoesNotExist:
        raise PublicAPIError("NOT_FOUND", "the requested resource does not exist", status=404)


def _query_date_filter(queryset, request, field):
    value = request.GET.get(field)
    return queryset.filter(**{field: _date(value, field)}) if value else queryset


def _item_queryset(request):
    queryset = InspectionItem.objects.all().order_by("code", "created_at", "pk")
    for key in ("domain", "execution_mode", "code_status"):
        values = _query_list(request, key)
        if key == "execution_mode":
            values = _choice_filter(values, InspectionItem.ExecutionMode, key)
        elif key == "code_status":
            values = _choice_filter(values, InspectionItem.CodeStatus, key)
        if values:
            queryset = queryset.filter(**{f"{key}__in": values})
    enabled = _query_bool(request, "enabled")
    if enabled is not None:
        queryset = queryset.filter(enabled=enabled)
    ai_dependent = _query_bool(request, "ai_dependent")
    if ai_dependent is not None:
        if ai_dependent:
            queryset = queryset.exclude(llm_responsibilities=[])
        else:
            queryset = queryset.filter(llm_responsibilities=[])
    return queryset


@_boundary
@_endpoint("viewer", {"GET"})
def inspection_items(request):
    return _paginate(request, _item_queryset(request), serialize_inspection_item)


@_boundary
@_endpoint("viewer", {"GET"})
def inspection_item_detail(request, item_id):
    item = _lookup(InspectionItem, item_id, "inspection_item_id")
    result = serialize_inspection_item(item, detail=True)
    from apps.capabilities.models import InspectionCapabilityBinding

    bindings = (
        InspectionCapabilityBinding.objects.filter(inspection_item=item)
        .select_related("capability_version__capability")
        .order_by("priority", "pk")[:64]
    )
    result["capabilities"] = [serialize_capability_binding(binding) for binding in bindings]
    return JsonResponse(result)


def _item_conversation(user, payload):
    """Create an item-bound conversation for the shortcut endpoint.

    The existing conversation service intentionally accepts risk contexts only;
    this adapter keeps the item shortcut in this slice without expanding that
    service's state machine.
    """

    if payload.get("context_type") == Conversation.ContextType.INSPECTION_ITEM:
        item = _lookup(InspectionItem, payload.get("context_id"), "context_id")
        environment = _environment(payload.get("environment_id"))
        if environment is None:
            environment = Environment.objects.order_by("created_at", "pk").first()
        if environment is None:
            raise PublicAPIError("NOT_FOUND", "an environment is required for this conversation", status=404)
        return Conversation.objects.create(
            environment=environment,
            user=user,
            context_type=Conversation.ContextType.INSPECTION_ITEM,
            context_id=item.pk,
            title=payload.get("title") or item.name,
        )
    from apps.conversations.services import create_conversation as service_create_conversation

    return service_create_conversation(user, payload)


create_conversation = _item_conversation


from apps.conversations.services import create_turn  # noqa: E402  (injection seam)


@_boundary
@_endpoint("viewer", {"POST"})
def inspection_item_ask(request, item_id):
    payload = parse_json_object(request)
    message = _text(payload.get("message"), "message", required=True, limit=4000)
    item = _lookup(InspectionItem, item_id, "inspection_item_id")
    with transaction.atomic():
        conversation = create_conversation(
            request.user,
            {
                "context_type": Conversation.ContextType.INSPECTION_ITEM,
                "context_id": str(_uuid(item_id, "inspection_item_id")),
                "title": payload.get("title") or item.name,
                "environment_id": payload.get("environment_id"),
            },
        )
        if getattr(conversation, "environment_id", None):
            record_event(
                actor=request.user,
                environment=conversation.environment,
                event_type="inspection_item.asked",
                object_type="Conversation",
                object_id=conversation.pk,
                payload={},
            )
    try:
        turn = create_turn(request.user, conversation.pk, {"message": message})
    except Exception as error:
        # The persisted conversation is still useful for retrying; expose only
        # the stable public error for expected conversation failures.
        from apps.conversations.services import ConversationError

        if isinstance(error, ConversationError):
            raise PublicAPIError(_conversation_code(error.code), error.message, error.status)
        raise
    turn = turn if isinstance(turn, Mapping) else {}
    turn_id = turn.get("turn_id") or turn.get("investigation_id")
    return JsonResponse(
        {
            "conversation_id": str(conversation.pk),
            "turn_id": str(turn_id) if turn_id else None,
            "investigation_id": str(turn.get("investigation_id")) if turn.get("investigation_id") else None,
            "events_url": turn.get("events_url") or (
                f"/api/v1/conversations/{conversation.pk}/turns/{turn_id}/events" if turn_id else None
            ),
        },
        status=201,
    )


def _run_queryset(request):
    queryset = InspectionRun.objects.all().order_by("-run_date", "-created_at", "-pk")
    if request.GET.get("environment_id"):
        queryset = queryset.filter(environment_id=_uuid(request.GET["environment_id"], "environment_id"))
    if request.GET.get("run_date"):
        queryset = queryset.filter(run_date=_date(request.GET["run_date"], "run_date"))
    statuses = _choice_filter(_query_list(request, "status"), InspectionRun.Status, "status")
    if statuses:
        queryset = queryset.filter(status__in=statuses)
    return queryset


@_boundary
@_endpoint("viewer", {"GET"})
def inspection_runs(request):
    return _paginate(request, _run_queryset(request), serialize_run)


@_boundary
@_endpoint("viewer", {"GET"})
def inspection_run_detail(request, run_id):
    run = _lookup(InspectionRun, run_id, "inspection_run_id")
    item_runs = list(
        InspectionItemRun.objects.filter(inspection_run=run)
        .order_by("inspection_item__code", "pk")
        [:128]
    )
    for item_run in item_runs:
        item_run._public_findings = list(
            Finding.objects.filter(inspection_item_run=item_run).select_related("inspection_item_run")[:128]
        )
    run._public_item_runs = item_runs
    return JsonResponse(serialize_run(run, detail=True))


@_boundary
@_endpoint("viewer", {"GET"})
def inspection_item_run_detail(request, item_run_id):
    item_run = _lookup(InspectionItemRun, item_run_id, "inspection_item_run_id")
    item_run._public_findings = list(
        Finding.objects.filter(inspection_item_run=item_run).select_related("inspection_item_run")[:128]
    )
    risk_id = (
        RiskObservation.objects.filter(inspection_item_run=item_run)
        .order_by("-created_at", "-pk")
        .values_list("risk_id", flat=True)
        .first()
    )
    for finding in item_run._public_findings:
        finding._public_risk_id = risk_id
    return JsonResponse(serialize_item_run(item_run, detail=True))


def _finding_queryset(request):
    queryset = Finding.objects.all().select_related("inspection_item_run").order_by("-observed_at", "-created_at", "-pk")
    if request.GET.get("run_id"):
        queryset = queryset.filter(inspection_item_run__inspection_run_id=_uuid(request.GET["run_id"], "run_id"))
    if request.GET.get("item_run_id"):
        queryset = queryset.filter(inspection_item_run_id=_uuid(request.GET["item_run_id"], "item_run_id"))
    if request.GET.get("finding_code"):
        queryset = queryset.filter(finding_code=request.GET["finding_code"].strip())
    if request.GET.get("risk_id"):
        risk_id = _uuid(request.GET["risk_id"], "risk_id")
        queryset = queryset.filter(
            inspection_item_run__riskobservation__risk_id=risk_id
        )
    return queryset


@_boundary
@_endpoint("viewer", {"GET"})
def findings(request):
    def serializer(finding):
        finding._public_risk_id = (
            RiskObservation.objects.filter(inspection_item_run_id=finding.inspection_item_run_id)
            .order_by("-created_at", "-pk")
            .values_list("risk_id", flat=True)
            .first()
        )
        return serialize_finding(finding)

    return _paginate(request, _finding_queryset(request), serializer)


def _snapshot_queryset(request):
    queryset = DailySnapshot.objects.all().order_by("-snapshot_date", "-created_at", "-pk")
    environment_value = request.GET.get("environment") or request.GET.get("environment_id")
    if environment_value:
        environment = _environment(environment_value, required=True)
        queryset = queryset.filter(environment_id=environment.pk)
    if request.GET.get("date_from"):
        queryset = queryset.filter(snapshot_date__gte=_date(request.GET["date_from"], "date_from"))
    if request.GET.get("date_to"):
        queryset = queryset.filter(snapshot_date__lte=_date(request.GET["date_to"], "date_to"))
    return queryset


@_boundary
@_endpoint("viewer", {"GET"})
def daily_snapshots(request):
    return _paginate(request, _snapshot_queryset(request), serialize_snapshot)


@_boundary
@_endpoint("viewer", {"GET"})
def daily_snapshot_detail(request, snapshot_id):
    return JsonResponse(serialize_snapshot(_lookup(DailySnapshot, snapshot_id, "snapshot_id")))


_SNAPSHOT_DIFF_FIELDS = (
    "risk_total",
    "p1_count",
    "p2_count",
    "new_count",
    "worsened_count",
    "recovered_count",
    "pending_action_count",
    "pending_reverify_count",
    "code_coverage_rate",
    "ai_displacement_rate",
    "data_completeness_rate",
)


@_boundary
@_endpoint("viewer", {"GET"})
def dashboard_today(request):
    environment = _environment_for_dashboard(request)
    queryset = DailySnapshot.objects.all().order_by("-snapshot_date", "-created_at", "-pk")
    if environment is not None:
        queryset = queryset.filter(environment_id=environment.pk)
    latest = queryset.first()
    if latest is None:
        raise PublicAPIError("NOT_FOUND", "no daily snapshot exists", status=404)
    yesterday = queryset.filter(snapshot_date=latest.snapshot_date - timedelta(days=1)).first()
    trend = list(
        queryset.filter(
            snapshot_date__gte=latest.snapshot_date - timedelta(days=6),
            snapshot_date__lte=latest.snapshot_date,
        ).order_by("snapshot_date", "pk")[:7]
    )
    snapshot = serialize_snapshot(latest)
    yesterday_diff = {}
    if yesterday is not None:
        for field in _SNAPSHOT_DIFF_FIELDS:
            value = getattr(latest, field) - getattr(yesterday, field)
            if hasattr(value, "normalize"):
                value = float(value)
            yesterday_diff[field] = value
    active = ACTIVE_RISK_STATUSES
    top_risks = [
        serialize_risk(risk)
        for risk in Risk.objects.filter(environment_id=latest.environment_id, status__in=active)
        .order_by("severity", "-last_seen_at", "-pk")[:10]
    ]
    return JsonResponse(
        {
            "snapshot": snapshot,
            "top_risks": top_risks,
            "yesterday_diff": yesterday_diff,
            "trend_7d": [serialize_snapshot(item) for item in trend],
            "capability_maturity": _capability_maturity(latest.environment_id),
        }
    )


def _capability_maturity(environment_id):
    # InspectionItem is global in the current schema; expose only bounded
    # aggregate counters rather than pretending it is environment-scoped.
    items = InspectionItem.objects.filter(enabled=True)
    total = items.count()
    coded = items.exclude(code_status=InspectionItem.CodeStatus.NOT_CODED).count()
    return {"enabled_items": total, "coded_items": coded}


def _risk_queryset(request):
    queryset = Risk.objects.all().order_by("severity", "-last_seen_at", "-pk")
    values = _choice_filter(_query_list(request, "severity"), Severity, "severity")
    if values:
        queryset = queryset.filter(severity__in=values)
    values = _choice_filter(_query_list(request, "status"), Risk.Status, "status")
    if values:
        queryset = queryset.filter(status__in=values)
    if request.GET.get("domain"):
        queryset = queryset.filter(domain=request.GET["domain"].strip())
    if request.GET.get("inspection_item_id"):
        queryset = queryset.filter(inspection_item_id=_uuid(request.GET["inspection_item_id"], "inspection_item_id"))
    ai_involved = _query_bool(request, "ai_involved")
    if ai_involved is not None:
        queryset = queryset.filter(llm_involved_last=ai_involved)
    change = request.GET.get("change")
    if change:
        change = change.strip().upper()
        if change not in {"NEW", "PERSISTING", "WORSENED", "RECOVERED"}:
            raise APIRequestError("VALIDATION_ERROR", "invalid change", details={"field": "change"})
        ids = [
            risk.pk
            for risk in queryset[:1000]
            if _risk_change(risk) == change
        ]
        queryset = queryset.filter(pk__in=ids)
    return queryset


def _risk_change(risk):
    history = RiskStatusHistory.objects.filter(risk=risk).order_by("-created_at", "-pk").first()
    if history is not None:
        return {
            Risk.Status.NEW: "NEW",
            Risk.Status.WORSENED: "WORSENED",
            Risk.Status.RECOVERED: "RECOVERED",
        }.get(history.to_status, "PERSISTING")
    return "NEW" if risk.occurrence_count <= 1 else "PERSISTING"


@_boundary
@_endpoint("viewer", {"GET"})
def risks(request):
    return _paginate(request, _risk_queryset(request), serialize_risk)


@_boundary
@_endpoint("viewer", {"GET"})
def risk_detail(request, risk_id):
    risk = _lookup(Risk, risk_id, "risk_id")
    risk._public_investigation = (
        Investigation.objects.filter(risk=risk).order_by("-created_at", "-pk").first()
    )
    return JsonResponse(serialize_risk(risk, detail=True))


@_boundary
@_endpoint("viewer", {"GET"})
def risk_timeline(request, risk_id):
    risk = _lookup(Risk, risk_id, "risk_id")
    events = list(RiskStatusHistory.objects.filter(risk=risk).order_by("created_at", "pk")[:256])
    if not events:
        return JsonResponse(
            {
                "risk_id": str(risk.pk),
                "events": [
                    {
                        "at": risk.first_seen_at.isoformat(),
                        "type": "STATUS_CHANGE",
                        "from_status": None,
                        "to_status": risk.status,
                        "label": "首次发现",
                        "source": "SYSTEM",
                        "reason": "",
                        "actor_user_id": None,
                    }
                ],
            }
        )
    return JsonResponse({"risk_id": str(risk.pk), "events": [serialize_history(event) for event in events]})


@_boundary
@_endpoint("viewer", {"GET"})
def risk_evidence(request, risk_id):
    risk = _lookup(Risk, risk_id, "risk_id")
    limit = _query_page_limit(request, default=50, maximum=100)
    queryset = Evidence.objects.filter(risk=risk).order_by("-created_at", "-pk")
    evidence_type = request.GET.get("type")
    if evidence_type:
        if evidence_type.strip().upper() not in set(Evidence.EvidenceType.values):
            raise APIRequestError("VALIDATION_ERROR", "invalid evidence type", details={"field": "type"})
        queryset = queryset.filter(evidence_type=evidence_type.strip().upper())
    values = queryset[:limit]
    return JsonResponse(
        {
            "risk_id": str(risk.pk),
            "items": [serialize_evidence(item) for item in values],
            "limit": limit,
            "total": queryset.count(),
        }
    )


def _risk_for_mutation(risk_id):
    return Risk.objects.select_for_update().select_related("environment").get(pk=_uuid(risk_id, "risk_id"))


@_boundary
@_endpoint("operator", {"POST"})
def mark_handled(request, risk_id):
    payload = parse_json_object(request)
    _reject_unknown(payload, {"comment", "external_ticket"})
    comment = _text(payload.get("comment"), "comment", limit=2000)
    external_ticket = _text(payload.get("external_ticket"), "external_ticket", limit=255)
    with transaction.atomic():
        risk = _risk_for_mutation(risk_id)
        try:
            updated = lifecycle_mark_handled(
                risk,
                actor_user=request.user,
                reason=comment or "Risk marked handled; awaiting reverification",
            )
        except ValueError as error:
            raise PublicAPIError("INVALID_RISK_TRANSITION", str(error), status=409) from None
        record_event(
            actor=request.user,
            environment=risk.environment,
            event_type="risk.mark_handled",
            object_type="Risk",
            object_id=risk.pk,
            payload={"to_status": updated.status},
        )
    return JsonResponse({"risk_id": str(updated.pk), "status": updated.status})


@_endpoint("operator", {"POST"})
@_boundary
def ignore(request, risk_id):
    payload = parse_json_object(request)
    _reject_unknown(payload, {"reason"})
    reason = _text(payload.get("reason"), "reason", required=True, limit=2000)
    with transaction.atomic():
        risk = _risk_for_mutation(risk_id)
        allowed = ACTIVE_RISK_STATUSES | {Risk.Status.PENDING_REVERIFY}
        if risk.status not in allowed:
            raise PublicAPIError("INVALID_RISK_TRANSITION", "only an active risk can be ignored", status=409)
        try:
            updated = transition_risk(
                risk,
                Risk.Status.IGNORED,
                reason=reason,
                source=RiskStatusHistory.Source.HUMAN,
                actor_user=request.user,
            )
        except ValueError as error:
            raise PublicAPIError("INVALID_RISK_TRANSITION", str(error), status=409) from None
        record_event(
            actor=request.user,
            environment=risk.environment,
            event_type="risk.ignored",
            object_type="Risk",
            object_id=risk.pk,
            payload={"to_status": updated.status},
        )
    return JsonResponse({"risk_id": str(updated.pk), "status": updated.status})


@_boundary
@_endpoint("operator", {"POST"})
def reverify(request, risk_id):
    payload = parse_json_object(request)
    if payload:
        # The endpoint has no mutable knobs; reject accidental state bypasses.
        unknown = set(payload) - {"run_id"}
        if unknown:
            raise APIRequestError("VALIDATION_ERROR", "only run_id is accepted", details={"fields": sorted(unknown)})
    with transaction.atomic():
        risk = _risk_for_mutation(risk_id)
        if risk.status != Risk.Status.PENDING_REVERIFY:
            raise PublicAPIError("INVALID_RISK_TRANSITION", "only a pending risk can be reverified", status=409)
        run_queryset = InspectionRun.objects.filter(
            environment_id=risk.environment_id,
            status=InspectionRun.Status.SUCCEEDED,
            finished_at__isnull=False,
        ).order_by("-finished_at", "-pk")
        if payload.get("run_id"):
            run = run_queryset.filter(pk=_uuid(payload["run_id"], "run_id")).first()
        else:
            run = run_queryset.first()
        if run is None:
            raise PublicAPIError("INVALID_RISK_TRANSITION", "a completed run is required for reverification", status=409)
        reverify_pending_risks(run)
        risk.refresh_from_db()
        record_event(
            actor=request.user,
            environment=risk.environment,
            event_type="risk.reverified",
            object_type="Risk",
            object_id=risk.pk,
            payload={},
        )
    return JsonResponse({"risk_id": str(risk.pk), "status": risk.status, "inspection_run_id": str(run.pk)}, status=202)


@_boundary
@_endpoint("viewer", {"POST"})
def risk_investigations(request, risk_id):
    payload = parse_json_object(request)
    question = _text(payload.get("question"), "question", required=True, limit=4000)
    trigger_type = str(payload.get("trigger_type", "HUMAN")).strip().upper()
    if trigger_type != Investigation.TriggerType.HUMAN:
        raise APIRequestError("VALIDATION_ERROR", "trigger_type must be HUMAN", details={"field": "trigger_type"})
    risk = _lookup(Risk, risk_id, "risk_id")
    with transaction.atomic():
        conversation = create_conversation(
            request.user,
            {
                "context_type": Conversation.ContextType.RISK,
                "context_id": str(risk.pk),
                "title": risk.title,
            },
        )
        record_event(
            actor=request.user,
            environment=risk.environment,
            event_type="risk.investigation.created",
            object_type="Risk",
            object_id=risk.pk,
            payload={},
        )
    try:
        turn = create_turn(request.user, conversation.pk, {"message": question})
    except Exception as error:
        from apps.conversations.services import ConversationError

        if isinstance(error, ConversationError):
            raise PublicAPIError(_conversation_code(error.code), error.message, error.status)
        raise
    turn = turn if isinstance(turn, Mapping) else {}
    investigation_id = turn.get("investigation_id") or getattr(conversation, "investigation_id", None)
    if investigation_id:
        Risk.objects.filter(pk=risk.pk).update(current_investigation_id=investigation_id)
    return JsonResponse(
        {
            "risk_id": str(risk.pk),
            "conversation_id": str(conversation.pk),
            "investigation_id": str(investigation_id) if investigation_id else None,
            "turn_id": str(turn.get("turn_id")) if turn.get("turn_id") else (str(investigation_id) if investigation_id else None),
            "events_url": turn.get("events_url") or (
                f"/api/v1/conversations/{conversation.pk}/turns/{investigation_id}/events"
                if investigation_id
                else None
            ),
        },
        status=202,
    )


def _conversation_code(code):
    return {
        "authentication_required": "AUTH_REQUIRED",
        "not_found": "NOT_FOUND",
        "invalid_json": "VALIDATION_ERROR",
        "invalid_field": "VALIDATION_ERROR",
        "conversation_closed": "INVALID_RISK_TRANSITION",
    }.get(code, str(code).upper())


def _default_airflow_transport(payload):
    raise RuntimeError("Airflow transport is not configured")


# Tests and deployments inject this callable; no network request is made by
# the public slice itself.
airflow_transport = _default_airflow_transport


def _call_airflow_transport(transport, payload):
    if callable(transport):
        return transport(payload)
    trigger = getattr(transport, "trigger", None)
    return trigger(payload) if callable(trigger) else transport(payload)


@_boundary
@_endpoint("operator", {"POST"})
def trigger_inspection_run(request):
    payload = parse_json_object(request)
    environment = _environment(payload.get("environment_id"), required=True)
    run_date = _date(payload.get("run_date"), "run_date")
    scenario = _text(payload.get("scenario"), "scenario", required=True, limit=64)
    seed = payload.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise APIRequestError("VALIDATION_ERROR", "seed must be an integer", details={"field": "seed"})
    request_payload = {
        "environment_id": str(environment.pk),
        "run_date": run_date.isoformat(),
        "scenario": scenario,
        "seed": seed,
    }
    transport = getattr(settings, "API_AIRFLOW_TRANSPORT", None) or airflow_transport
    try:
        result = _call_airflow_transport(transport, request_payload)
    except Exception as error:
        raise PublicAPIError("AIRFLOW_TRIGGER_FAILED", "Airflow could not be triggered", status=502) from error
    if not isinstance(result, Mapping):
        result = {}
    dag_id = str(result.get("dag_id") or os.getenv("AIRFLOW_DAG_ID", "daily_iaas_inspection"))[:128]
    dag_run_id = str(result.get("dag_run_id") or f"manual__{timezone.now().isoformat()}")[:250]
    status = str(result.get("status") or "QUEUED")[:32]
    with transaction.atomic():
        record_event(
            actor=request.user,
            environment=environment,
            event_type="inspection_run.triggered",
            object_type="InspectionRun",
            object_id=dag_run_id,
            payload={},
        )
    return JsonResponse({"dag_id": dag_id, "dag_run_id": dag_run_id, "status": status}, status=202)


# Short aliases make the slice straightforward to include from a root router.
item_detail = inspection_item_detail
item_ask = inspection_item_ask
run_detail = inspection_run_detail
item_run_detail = inspection_item_run_detail
snapshot_detail = daily_snapshot_detail
dashboard = dashboard_today
risk_list = risks
risk_detail_view = risk_detail
timeline = risk_timeline
evidence = risk_evidence
mark_risk_handled = mark_handled
ignore_risk = ignore
reverify_risk = reverify
investigations = risk_investigations


__all__ = [
    "airflow_transport",
    "daily_snapshot_detail",
    "daily_snapshots",
    "dashboard_today",
    "findings",
    "ignore",
    "inspection_item_ask",
    "inspection_item_detail",
    "inspection_item_run_detail",
    "inspection_items",
    "inspection_run_detail",
    "inspection_runs",
    "mark_handled",
    "reverify",
    "risk_detail",
    "risk_evidence",
    "risk_investigations",
    "risk_timeline",
    "risks",
    "trigger_inspection_run",
]
