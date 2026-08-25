from collections import Counter
from datetime import date
import uuid
from functools import wraps

from django.http import JsonResponse

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error
from apps.api.pagination import paginate
from apps.assets.models import Asset
from apps.inspections.models import (
    Finding,
    InspectionItemResourceType,
    InspectionItemRun,
    ResourceInspectionSummary,
    ResourceType,
)
from apps.risks.models import Risk, RiskObservation
from apps.operations_api.serializers import serialize_risk

from .serializers import serialize_resource_summary


class ResourceAPIError(Exception):
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
        except ResourceAPIError as error:
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


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a UUID", details={"field": field}) from None


def _environment(request, *, required=True):
    value = request.GET.get("environment_id") or request.GET.get("environment")
    if not value:
        if required:
            raise APIRequestError("VALIDATION_ERROR", "environment_id is required", details={"field": "environment_id"})
        return None
    from apps.core.models import Environment

    parsed = _uuid(value, "environment_id")
    try:
        return Environment.objects.get(pk=parsed)
    except Environment.DoesNotExist:
        raise ResourceAPIError("NOT_FOUND", "environment does not exist", status=404) from None


def _resource_type(code):
    try:
        return ResourceType.objects.get(code=str(code).upper(), enabled=True)
    except ResourceType.DoesNotExist:
        raise ResourceAPIError("RESOURCE_TYPE_NOT_FOUND", "resource type does not exist", status=404) from None


def _latest_summary(resource_type, environment):
    return (
        ResourceInspectionSummary.objects.filter(
            resource_type=resource_type,
            inspection_run__environment=environment,
        )
        .select_related("inspection_run", "resource_type")
        .order_by("-inspection_run__run_date", "-inspection_run__created_at", "-pk")
        .first()
    )


def _asset_count(resource_type, environment):
    asset_types = (resource_type.asset_selector or {}).get("asset_types", [])
    return Asset.objects.filter(
        environment=environment,
        status=Asset.Status.ACTIVE,
        asset_type__in=asset_types,
    ).count()


def _item_count(resource_type):
    return InspectionItemResourceType.objects.filter(
        resource_type=resource_type,
        enabled=True,
        inspection_item__enabled=True,
    ).count()


def _serialize_resource_type(resource_type, environment):
    latest = _latest_summary(resource_type, environment) if environment else None
    return {
        "code": resource_type.code,
        "name": resource_type.name,
        "description": resource_type.description,
        "icon": resource_type.icon,
        "asset_count": latest.assets_total if latest else _asset_count(resource_type, environment),
        "inspection_item_count": latest.inspection_item_count if latest else _item_count(resource_type),
        "health_score": float(latest.health_score) if latest else None,
        "risk_count": latest.risk_count if latest else 0,
        "p1_count": latest.p1_count if latest else 0,
        "p2_count": latest.p2_count if latest else 0,
        "last_inspection_at": (
            (latest.finished_at or latest.started_at or latest.inspection_run.created_at).isoformat()
            if latest
            else None
        ),
    }


@_boundary
@_endpoint({"GET"})
def resource_types(request):
    environment = _environment(request, required=False)
    items = [
        _serialize_resource_type(resource_type, environment)
        for resource_type in ResourceType.objects.filter(enabled=True).order_by("sort_order", "code", "pk")
    ]
    return JsonResponse({"items": items, "page": 1, "page_size": len(items), "total": len(items)})


@_boundary
@_endpoint({"GET"})
def resource_overview(request, resource_type_code):
    environment = _environment(request)
    resource_type = _resource_type(resource_type_code)
    summaries = (
        ResourceInspectionSummary.objects.filter(
            resource_type=resource_type,
            inspection_run__environment=environment,
        )
        .select_related("inspection_run", "resource_type")
        .order_by("-inspection_run__run_date", "-inspection_run__created_at", "-pk")
    )
    latest = summaries.first()
    trend = list(summaries.order_by("inspection_run__run_date", "inspection_run__created_at", "pk")[:30])
    return JsonResponse(
        {
            "resource_type": _serialize_resource_type(resource_type, environment),
            "latest": serialize_resource_summary(latest) if latest else None,
            "health_trend": [serialize_resource_summary(item) for item in trend],
        }
    )


@_boundary
@_endpoint({"GET"})
def resource_history(request, resource_type_code):
    environment = _environment(request)
    resource_type = _resource_type(resource_type_code)
    queryset = (
        ResourceInspectionSummary.objects.filter(
            resource_type=resource_type,
            inspection_run__environment=environment,
        )
        .select_related("inspection_run", "resource_type")
        .order_by("-inspection_run__run_date", "-inspection_run__created_at", "-pk")
    )
    if request.GET.get("date_from"):
        queryset = queryset.filter(inspection_run__run_date__gte=_date(request.GET["date_from"], "date_from"))
    if request.GET.get("date_to"):
        queryset = queryset.filter(inspection_run__run_date__lte=_date(request.GET["date_to"], "date_to"))
    return paginate(queryset, request, serialize_resource_summary)


@_boundary
@_endpoint({"GET"})
def resource_run_detail(request, resource_type_code, run_id):
    environment = _environment(request)
    resource_type = _resource_type(resource_type_code)
    parsed_run_id = _uuid(run_id, "run_id")
    try:
        summary = ResourceInspectionSummary.objects.select_related("inspection_run", "resource_type").get(
            resource_type=resource_type,
            inspection_run_id=parsed_run_id,
            inspection_run__environment=environment,
        )
    except ResourceInspectionSummary.DoesNotExist:
        raise ResourceAPIError("NOT_FOUND", "resource inspection run does not exist", status=404) from None
    item_ids = InspectionItemResourceType.objects.filter(
        resource_type=resource_type,
        enabled=True,
    ).values_list("inspection_item_id", flat=True)
    item_runs = list(
        InspectionItemRun.objects.filter(
            inspection_run_id=summary.inspection_run_id,
            inspection_item_id__in=item_ids,
        ).select_related("inspection_item")
    )
    item_run_ids = [item_run.pk for item_run in item_runs]
    observations = RiskObservation.objects.filter(
        inspection_run_id=summary.inspection_run_id,
        inspection_item_run_id__in=item_run_ids,
        detected=True,
    )
    risk_ids = list(observations.values_list("risk_id", flat=True).distinct())
    risks = list(
        Risk.objects.filter(pk__in=risk_ids).order_by("severity", "title", "pk")[:20]
    )
    status_counts = Counter(item_run.status for item_run in item_runs)
    severity_counts = {
        "P1": summary.p1_count,
        "P2": summary.p2_count,
        "P3": summary.p3_count,
        "P4": summary.p4_count,
    }
    return JsonResponse(
        {
            "resource_type": resource_type.code,
            "run": {
                "id": str(summary.inspection_run_id),
                "status": summary.inspection_run.status,
                "run_date": summary.inspection_run.run_date.isoformat(),
                "started_at": summary.started_at.isoformat() if summary.started_at else None,
                "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
            },
            "coverage": {
                "assets_total": summary.assets_total,
                "assets_covered": summary.assets_covered,
                "rate": summary.assets_covered / summary.assets_total if summary.assets_total else 1.0,
            },
            "inspection_item_status_counts": dict(status_counts),
            "inspection_item_count": summary.inspection_item_count,
            "finding_count": summary.finding_count,
            "risk_count": summary.risk_count,
            "severity_counts": severity_counts,
            "ai_dependent_cases": summary.ai_dependent_cases,
            "ai_investigation_count": summary.ai_investigation_count,
            "major_risks": [serialize_risk(risk) for risk in risks],
            "summary": summary.summary or {},
        }
    )


def _date(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO date", details={"field": field}) from None


__all__ = ["resource_history", "resource_overview", "resource_run_detail", "resource_types"]
