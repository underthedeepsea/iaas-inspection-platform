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
from apps.assets.models import Asset
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
        )
        .select_related("inspection_item")
        .order_by("inspection_item__code", "pk")[:MAX_REFERENCE_ITEMS]
    )
    item_run_ids = [row.pk for row in item_runs]
    findings = [
        _finding_projection(row)
        for row in Finding.objects.filter(inspection_item_run_id__in=item_run_ids)
        .select_related("asset")
        .order_by("-severity", "-observed_at", "-pk")[:MAX_REFERENCE_ITEMS]
    ]
    evidence = [
        _evidence_projection(row, item_run_ids)
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
        _risk_projection(row)
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
    trend = list(
        ResourceInspectionSummary.objects.filter(
            resource_type=resource_type,
            inspection_run__environment_id=run.environment_id,
            inspection_run__run_date__gte=run.run_date - timedelta(days=6),
            inspection_run__run_date__lte=run.run_date,
        )
        .select_related("inspection_run")
        .order_by("inspection_run__run_date", "inspection_run__created_at", "pk")[:7]
    )
    risk_ids_by_item_run = _risk_ids_by_item_run(run, item_run_ids)
    return _fit_context(
        InvestigationContext(
            {
                "context_type": "RESOURCE_RUN",
                "environment_id": str(run.environment_id),
                "resource_type_code": resource_type.code,
                "inspection_run_id": str(run.id),
                "current_summary": _summary_projection(summary),
                "previous_run": _summary_projection(previous) if previous else None,
                "trend_7d": [_summary_projection(row) for row in trend],
                "major_risks": risks,
                "findings": findings,
                "evidence": evidence,
                "changes": changes,
                "inspection_item_results": [
                    _item_run_projection(row) for row in item_runs
                ],
                "asset_context": _asset_context(run, resource_type, item_runs),
                "missing_claim": _missing_claim(item_runs),
                "risk_ids_by_item_run": risk_ids_by_item_run,
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
        _risk_projection(row)
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
                "trend_7d": [_summary_projection(row) for row in summaries[-7:]],
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
        "health_score": float(summary.health_score) if summary.health_score is not None else None,
        "assets_total": summary.assets_total,
        "assets_covered": summary.assets_covered,
        "finding_count": summary.finding_count,
        "risk_count": summary.risk_count,
        "p1_count": summary.p1_count,
        "p2_count": summary.p2_count,
        "ai_dependent_cases": summary.ai_dependent_cases,
        "ai_investigation_count": summary.ai_investigation_count,
    }


def _item_run_projection(item_run):
    return {
        "id": str(item_run.pk),
        "inspection_item_id": str(item_run.inspection_item_id),
        "code": item_run.inspection_item.code,
        "name": item_run.inspection_item.name,
        "status": item_run.status,
        "ai_admission_status": item_run.ai_admission_status,
        "asset_scope": {
            "asset_ids": [str(value) for value in (item_run.asset_scope or {}).get("asset_ids") or []],
            "asset_keys": list((item_run.asset_scope or {}).get("asset_keys") or [])[:MAX_REFERENCE_ITEMS],
        },
        "summary": _compact_mapping(item_run.summary or {}, 512),
    }


def _finding_projection(finding):
    return {
        "id": str(finding.pk),
        "code": finding.finding_code,
        "title": finding.title[:256],
        "category": finding.category,
        "severity": finding.severity,
        "status": finding.status,
        "asset_id": str(finding.asset_id) if finding.asset_id else None,
        "observed_at": finding.observed_at.isoformat() if finding.observed_at else None,
        "source_type": finding.source_type,
        "value": _compact_mapping(finding.value or {}, 512),
    }


def _evidence_projection(evidence, item_run_ids):
    related_finding_ids = [
        str(value)
        for value in Finding.objects.filter(
            inspection_item_run_id=evidence.inspection_item_run_id,
        ).values_list("id", flat=True)[:MAX_REFERENCE_ITEMS]
    ]
    related_risk_ids = [
        str(value)
        for value in RiskObservation.objects.filter(
            inspection_run_id=evidence.inspection_run_id,
            inspection_item_run_id=evidence.inspection_item_run_id,
            detected=True,
        ).values_list("risk_id", flat=True)[:MAX_REFERENCE_ITEMS]
    ]
    payload = evidence.payload if isinstance(evidence.payload, dict) else {}
    return {
        "id": str(evidence.pk),
        "evidence_key": evidence.evidence_key,
        "evidence_type": evidence.evidence_type,
        "source": evidence.source,
        "window_start": evidence.window_start.isoformat() if evidence.window_start else None,
        "window_end": evidence.window_end.isoformat() if evidence.window_end else None,
        "observed_at": evidence.created_at.isoformat() if evidence.created_at else None,
        "value": _compact_mapping(payload, 512),
        "summary": evidence.summary[:256],
        "confidence": float(evidence.confidence),
        "materiality": float(evidence.materiality),
        "related_finding_ids": related_finding_ids,
        "related_risk_ids": related_risk_ids,
    }


def _risk_projection(risk):
    return {
        "id": str(risk.pk),
        "title": risk.title[:256],
        "severity": risk.severity,
        "status": risk.status,
        "asset_id": str(risk.primary_asset_id) if risk.primary_asset_id else None,
        "last_seen_at": risk.last_seen_at.isoformat() if risk.last_seen_at else None,
        "occurrence_count": risk.occurrence_count,
        "ai_involved": risk.llm_involved_last,
    }


def _risk_ids_by_item_run(run, item_run_ids):
    return {
        str(item_run_id): [
            str(risk_id)
            for risk_id in RiskObservation.objects.filter(
                inspection_run=run,
                inspection_item_run_id=item_run_id,
                detected=True,
            ).values_list("risk_id", flat=True)
        ]
        for item_run_id in item_run_ids
    }


def _asset_context(run, resource_type, item_runs):
    asset_ids = {
        str(value)
        for item_run in item_runs
        for value in (item_run.asset_scope or {}).get("asset_ids") or []
    }
    asset_keys = {
        value
        for item_run in item_runs
        for value in (item_run.asset_scope or {}).get("asset_keys") or []
        if isinstance(value, str)
    }
    resolved = (run.config_snapshot or {}).get("resolved_scope") or {}
    if not asset_ids and not asset_keys:
        asset_ids.update(str(value) for value in resolved.get("asset_ids") or [])
    query = Asset.objects.filter(environment_id=run.environment_id, status=Asset.Status.ACTIVE)
    if asset_ids:
        query = query.filter(id__in=asset_ids)
    elif asset_keys:
        query = query.filter(external_key__in=asset_keys)
    else:
        asset_types = (resource_type.asset_selector or {}).get("asset_types") or []
        query = query.filter(asset_type__in=asset_types)
    return [
        {
            "id": str(asset.pk),
            "external_key": asset.external_key,
            "asset_type": asset.asset_type,
            "name": asset.name,
        }
        for asset in query.order_by("external_key", "pk")[:MAX_REFERENCE_ITEMS]
    ]


def _missing_claim(item_runs):
    for item_run in item_runs:
        summary = item_run.summary or {}
        gaps = summary.get("material_claim_gaps") or summary.get("unresolved_claims") or []
        if gaps and isinstance(gaps[0], str):
            return gaps[0]
    return ""


def _compact_mapping(value, max_bytes):
    if not isinstance(value, dict):
        return {}
    raw = json.dumps(value, ensure_ascii=False, default=str)
    if len(raw.encode()) <= max_bytes:
        return value
    return {"truncated": True}


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
        for key in (
            "evidence",
            "findings",
            "inspection_item_results",
            "asset_context",
            "trend_7d",
            "major_risks",
            "active_risks",
            "changes",
            "summaries",
        ):
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
