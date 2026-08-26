from collections import Counter
from decimal import Decimal

from apps.assets.models import Asset
from apps.inspections.models import (
    Finding,
    InspectionItemResourceType,
    InspectionItemRun,
    InspectionRun,
    ResourceInspectionSummary,
    ResourceType,
)
from apps.investigations.models import Investigation
from apps.risks.models import RiskObservation


def build_resource_summaries(run_id):
    run = run_id if isinstance(run_id, InspectionRun) else InspectionRun.objects.get(pk=run_id)
    resource_types = _resource_types_for_run(run)
    results = []
    for resource_type in resource_types:
        results.append(_build_summary(run, resource_type))
    return results


def _resource_types_for_run(run):
    resolved = (run.config_snapshot or {}).get("resolved_scope") or {}
    codes = resolved.get("resource_types")
    if codes:
        return list(
            ResourceType.objects.filter(enabled=True, code__in=codes).order_by("sort_order", "code", "pk")
        )
    return list(
        ResourceType.objects.filter(
            enabled=True,
            inspection_items__enabled=True,
            inspection_items__inspection_item__item_runs__inspection_run=run,
        )
        .distinct()
        .order_by("sort_order", "code", "pk")
    )


def _build_summary(run, resource_type):
    item_ids = InspectionItemResourceType.objects.filter(
        resource_type=resource_type,
        enabled=True,
    ).values_list("inspection_item_id", flat=True)
    item_runs = list(
        InspectionItemRun.objects.filter(
            inspection_run=run,
            inspection_item_id__in=item_ids,
        ).order_by("inspection_item__code", "pk")
    )
    total_asset_ids = _asset_ids_for_type(run, resource_type)
    covered_asset_ids = _covered_asset_ids(run, item_runs)
    covered_asset_ids &= total_asset_ids
    findings = Finding.objects.filter(inspection_item_run_id__in=[row.pk for row in item_runs])
    observations = RiskObservation.objects.filter(
        inspection_run=run,
        inspection_item_run_id__in=[row.pk for row in item_runs],
        detected=True,
    ).order_by("risk_id", "pk")
    risk_severities = {
        str(row.risk_id): row.severity for row in observations
    }
    severity_counts = Counter(risk_severities.values())
    risk_ids = set(risk_severities)
    ai_cases = sum(
        row.ai_admission_status
        in {
            InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE,
            InspectionItemRun.AIAdmissionStatus.AI_DEFERRED,
        }
        for row in item_runs
    )
    investigation_count = Investigation.objects.filter(
        inspection_item_run_id__in=[row.pk for row in item_runs]
    ).count()
    assets_total = len(total_asset_ids)
    assets_covered = len(covered_asset_ids)
    coverage_rate = assets_covered / assets_total if assets_total else 1.0
    penalty = (
        severity_counts["P1"] * 25
        + severity_counts["P2"] * 12
        + severity_counts["P3"] * 4
        + severity_counts["P4"] * 1
    )
    coverage_penalty = round(max(0.0, 1.0 - coverage_rate) * 20)
    health_score = max(0, min(100, 100 - penalty - coverage_penalty))
    breakdown = {
        "penalty": penalty,
        "coverage_penalty": coverage_penalty,
        "coverage_rate": coverage_rate,
    }
    values = {
        "assets_total": assets_total,
        "assets_covered": assets_covered,
        "inspection_item_count": len(item_runs),
        "success_item_count": sum(
            row.status == InspectionItemRun.Status.SUCCEEDED for row in item_runs
        ),
        "failed_item_count": sum(
            row.status == InspectionItemRun.Status.FAILED for row in item_runs
        ),
        "finding_count": findings.count(),
        "risk_count": len(risk_ids),
        "p1_count": severity_counts["P1"],
        "p2_count": severity_counts["P2"],
        "p3_count": severity_counts["P3"],
        "p4_count": severity_counts["P4"],
        "ai_dependent_cases": ai_cases,
        "ai_investigation_count": investigation_count,
        "health_score": Decimal(str(health_score)),
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "summary": {
            "resource_type": resource_type.code,
            "coverage_rate": coverage_rate,
            "severity_counts": dict(severity_counts),
            "health_score_breakdown": breakdown,
        },
    }
    summary, _ = ResourceInspectionSummary.objects.update_or_create(
        inspection_run=run,
        resource_type=resource_type,
        defaults=values,
    )
    return summary


def _asset_ids_for_type(run, resource_type):
    selector = resource_type.asset_selector or {}
    asset_types = selector.get("asset_types", [])
    resolved = (run.config_snapshot or {}).get("resolved_scope") or {}
    frozen_ids = resolved.get("asset_ids")
    query = Asset.objects.filter(
        environment_id=run.environment_id,
        status=Asset.Status.ACTIVE,
        asset_type__in=asset_types,
    )
    if frozen_ids is not None:
        query = query.filter(id__in=frozen_ids)
    return {str(value) for value in query.values_list("id", flat=True)}


def _covered_asset_ids(run, item_runs):
    ids = set()
    keys = set()
    for item_run in item_runs:
        scope = item_run.asset_scope or {}
        ids.update(str(value) for value in scope.get("asset_ids") or [])
        keys.update(value for value in scope.get("asset_keys") or [] if isinstance(value, str))
    if keys:
        ids.update(
            str(value)
            for value in Asset.objects.filter(
                environment_id=run.environment_id,
                external_key__in=keys,
            ).values_list("id", flat=True)
        )
    return {value for value in ids}


__all__ = ["build_resource_summaries"]
