from collections import Counter, defaultdict
from decimal import Decimal

from apps.assets.models import Asset
from apps.inspections.models import (
    CheckResult,
    Finding,
    InspectionItemResourceType,
    InspectionItemRun,
    InspectionRun,
    ResourceInspectionSummary,
    ResourceType,
)
from apps.investigations.models import Investigation
from apps.risks.models import RiskObservation
from apps.inspections.services.scope import asset_ids_for_selectors


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
    total_asset_ids = {str(value) for value in _asset_ids_for_type(run, resource_type)}
    covered_asset_ids = _covered_asset_ids(run, item_runs)
    covered_asset_ids &= total_asset_ids
    checks = CheckResult.objects.filter(inspection_run=run, inspection_item_run__in=item_runs, asset_id__in=total_asset_ids)
    statuses = defaultdict(set)
    counts = Counter()
    for asset_id, status in checks.values_list('asset_id', 'status'):
        statuses[str(asset_id)].add(status)
        counts[status] += 1
    confidence = {
        'conclusive_assets': sum(bool(values & {'PASS','FAIL'}) for values in statuses.values()),
        'unknown_assets': sum(values == {'UNKNOWN'} for values in statuses.values()),
        'error_assets': sum('ERROR' in values for values in statuses.values()),
        'pass_count': counts['PASS'], 'fail_count': counts['FAIL'],
    }
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
    if assets_total:
        coverage_rate = assets_covered / assets_total
        penalty = (
            severity_counts["P1"] * 25
            + severity_counts["P2"] * 12
            + severity_counts["P3"] * 4
            + severity_counts["P4"] * 1
        )
        coverage_penalty = round(max(0.0, 1.0 - coverage_rate) * 20)
        health_score = max(0, min(100, 100 - penalty - coverage_penalty))
        data_state = "READY"
    else:
        coverage_rate = None
        penalty = None
        coverage_penalty = None
        health_score = None
        data_state = "NO_DATA"
    if assets_total and confidence['conclusive_assets'] == 0:
        health_score = None
        data_state = 'UNKNOWN'
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
        "health_score": Decimal(str(health_score)) if health_score is not None else None,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "summary": {
            **confidence,
            "assets_total": assets_total,
            "assets_covered": assets_covered,
            "resource_type": resource_type.code,
            "coverage_rate": coverage_rate,
            "data_state": data_state,
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
    resolved = (run.config_snapshot or {}).get("resolved_scope") or {}
    frozen_ids = resolved.get("asset_ids")
    return asset_ids_for_selectors(
        run.environment_id,
        [selector],
        frozen_ids=frozen_ids,
    )


def _covered_asset_ids(run, item_runs):
    return {str(value) for value in CheckResult.objects.filter(inspection_run=run, inspection_item_run__in=item_runs).values_list('asset_id', flat=True)}


__all__ = ["build_resource_summaries"]
