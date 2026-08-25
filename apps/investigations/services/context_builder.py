from datetime import date, timedelta
import json

from apps.inspections.models import (
    Finding,
    InspectionItemResourceType,
    InspectionItemRun,
    InspectionRun,
    MockChange,
    ResourceInspectionSummary,
    ResourceType,
)
from apps.risks.models import Evidence, Risk, RiskObservation
from apps.risks.services.lifecycle import ACTIVE_RISK_STATUSES


MAX_CONTEXT_BYTES = 4096
MAX_REFERENCE_ITEMS = 32


class InvestigationContext(dict):
    """JSON-like, bounded context accepted by the investigation graph."""


def build_resource_run_context(*, resource_type_code, inspection_run_id):
    resource_type = _resource_type(resource_type_code)
    try:
        summary = (
            ResourceInspectionSummary.objects.select_related("inspection_run", "resource_type")
            .get(resource_type=resource_type, inspection_run_id=inspection_run_id)
        )
    except ResourceInspectionSummary.DoesNotExist:
        raise ValueError("resource inspection summary does not exist") from None
    run = summary.inspection_run
    item_ids = _item_ids(resource_type)
    item_runs = list(
        InspectionItemRun.objects.filter(
            inspection_run=run,
            inspection_item_id__in=item_ids,
        )[:MAX_REFERENCE_ITEMS]
    )
    item_run_ids = [row.pk for row in item_runs]
    findings = [
        {"id": str(row.pk), "code": row.finding_code, "severity": row.severity}
        for row in Finding.objects.filter(inspection_item_run_id__in=item_run_ids)
        .order_by("-severity", "-observed_at", "-pk")[:MAX_REFERENCE_ITEMS]
    ]
    evidence = [
        {
            "id": str(row.pk),
            "evidence_key": row.evidence_key,
            "evidence_type": row.evidence_type,
            "summary": row.summary[:256],
        }
        for row in Evidence.objects.filter(
            inspection_run=run,
            inspection_item_run_id__in=item_run_ids,
        ).order_by("-materiality", "-created_at", "-pk")[:MAX_REFERENCE_ITEMS]
    ]
    risk_ids = set(
        RiskObservation.objects.filter(
            inspection_run=run,
            inspection_item_run_id__in=item_run_ids,
            detected=True,
        ).values_list("risk_id", flat=True)
    )
    risks = [
        {"id": str(row.pk), "title": row.title[:256], "severity": row.severity, "status": row.status}
        for row in Risk.objects.filter(pk__in=risk_ids).order_by("severity", "title", "pk")[:MAX_REFERENCE_ITEMS]
    ]
    previous = (
        ResourceInspectionSummary.objects.filter(
            resource_type=resource_type,
            inspection_run__environment=run.environment,
            inspection_run__run_date__lt=run.run_date,
        )
        .select_related("inspection_run")
        .order_by("-inspection_run__run_date", "-inspection_run__created_at", "-pk")
        .first()
    )
    changes = _change_references(run)
    return _fit_context(
        InvestigationContext(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(run.environment_id),
                "resource_type_code": resource_type.code,
                "inspection_run_id": str(run.id),
                "current_summary": _summary_projection(summary),
                "previous_run": _summary_projection(previous) if previous else None,
                "major_risks": risks,
                "findings": findings,
                "evidence": evidence,
                "changes": changes,
            }
        )
    )


def build_resource_type_context(*, environment_id, resource_type_code, date_from=None, date_to=None):
    resource_type = _resource_type(resource_type_code)
    end = _coerce_date(date_to) if date_to is not None else date.today()
    start = _coerce_date(date_from) if date_from is not None else end - timedelta(days=6)
    if start > end:
        raise ValueError("date_from must not be after date_to")
    if (end - start).days > 30:
        raise ValueError("resource context window cannot exceed 30 days")
    summaries = list(
        ResourceInspectionSummary.objects.filter(
            resource_type=resource_type,
            inspection_run__environment_id=environment_id,
            inspection_run__run_date__gte=start,
            inspection_run__run_date__lte=end,
        )
        .select_related("inspection_run")
        .order_by("inspection_run__run_date", "inspection_run__created_at", "pk")[:31]
    )
    item_ids = _item_ids(resource_type)
    active_risks = [
        {"id": str(row.pk), "title": row.title[:256], "severity": row.severity}
        for row in Risk.objects.filter(
            environment_id=environment_id,
            inspection_item_id__in=item_ids,
            status__in=ACTIVE_RISK_STATUSES,
        ).order_by("severity", "title", "pk")[:MAX_REFERENCE_ITEMS]
    ]
    return _fit_context(
        InvestigationContext(
            {
                "context_type": "RESOURCE_TYPE",
                "environment_id": str(environment_id),
                "resource_type_code": resource_type.code,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "summaries": [_summary_projection(row) for row in summaries],
                "active_risks": active_risks,
            }
        )
    )


def _resource_type(code):
    try:
        return ResourceType.objects.get(code=str(code).upper(), enabled=True)
    except ResourceType.DoesNotExist:
        raise ValueError("resource type does not exist") from None


def _item_ids(resource_type):
    return InspectionItemResourceType.objects.filter(
        resource_type=resource_type,
        enabled=True,
        inspection_item__enabled=True,
    ).values_list("inspection_item_id", flat=True)


def _summary_projection(summary):
    if summary is None:
        return None
    return {
        "inspection_run_id": str(summary.inspection_run_id),
        "run_date": summary.inspection_run.run_date.isoformat(),
        "status": summary.status,
        "health_score": float(summary.health_score),
        "assets_total": summary.assets_total,
        "assets_covered": summary.assets_covered,
        "finding_count": summary.finding_count,
        "risk_count": summary.risk_count,
        "p1_count": summary.p1_count,
        "p2_count": summary.p2_count,
        "ai_dependent_cases": summary.ai_dependent_cases,
        "ai_investigation_count": summary.ai_investigation_count,
    }


def _change_references(run):
    if not run.dataset_id:
        return []
    return [
        {"id": str(row.pk), "change_type": row.change_type, "summary": row.summary[:256]}
        for row in MockChange.objects.filter(dataset_id=run.dataset_id)
        .order_by("-start_at", "-pk")[:MAX_REFERENCE_ITEMS]
    ]


def _fit_context(context):
    while len(json.dumps(context, ensure_ascii=False).encode()) > MAX_CONTEXT_BYTES:
        changed = False
        for key in ("evidence", "findings", "major_risks", "active_risks", "changes", "summaries"):
            values = context.get(key)
            if isinstance(values, list) and values:
                values.pop()
                changed = True
                break
        if not changed:
            break
    return context


def _coerce_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("context dates must be ISO dates") from None


__all__ = [
    "InvestigationContext",
    "build_resource_run_context",
    "build_resource_type_context",
]
