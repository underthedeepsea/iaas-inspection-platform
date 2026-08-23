"""Persist one deterministic daily snapshot from a completed inspection run."""

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from apps.assets.models import Asset
from apps.inspections.models import DailySnapshot, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskStatusHistory
from apps.risks.services.lifecycle import TERMINAL_RISK_STATUSES


RATE_QUANTUM = Decimal("0.001")
HUNDRED = Decimal("100")


def build_daily_snapshot(inspection_run, snapshot_date=None):
    """Create or refresh the snapshot for one completed ``InspectionRun``."""

    with transaction.atomic():
        run = (
            InspectionRun.objects.select_for_update()
            .select_related("environment")
            .get(pk=inspection_run.pk)
        )
        if (
            run.status != InspectionRun.Status.SUCCEEDED
            or run.finished_at is None
        ):
            raise ValueError("daily snapshots require a completed inspection run")

        snapshot_date = snapshot_date or run.run_date
        item_runs = list(
            InspectionItemRun.objects.filter(
                inspection_run=run,
                status=InspectionItemRun.Status.SUCCEEDED,
                finished_at__isnull=False,
            ).only("summary", "asset_scope", "ai_admission_status")
        )
        stats = _snapshot_stats(run, item_runs)

        snapshot = (
            DailySnapshot.objects.select_for_update()
            .filter(environment_id=run.environment_id, snapshot_date=snapshot_date)
            .first()
        )
        values = {
            "environment_id": run.environment_id,
            "snapshot_date": snapshot_date,
            "inspection_run_id": run.pk,
            **stats,
        }
        if snapshot is None:
            snapshot = DailySnapshot.objects.create(**values)
        else:
            for field, value in values.items():
                if field not in {"environment_id", "snapshot_date"}:
                    setattr(snapshot, field, value)
            snapshot.save(update_fields=[field for field in values if field not in {"environment_id", "snapshot_date"}])
    return snapshot


def _snapshot_stats(run, item_runs):
    valid_item_runs = [
        item_run
        for item_run in item_runs
        if (item_run.summary or {}).get("data_valid") is True
    ]
    code_only_cases = sum(
        item_run.ai_admission_status == InspectionItemRun.AIAdmissionStatus.NO_AI
        for item_run in valid_item_runs
    )
    ai_dependent_cases = sum(
        item_run.ai_admission_status
        == InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE
        for item_run in valid_item_runs
    )
    required_claim_count = sum(
        len(_summary_claims(item_run, "required_claims"))
        for item_run in valid_item_runs
    )
    resolved_claim_count = sum(
        len(_summary_claims(item_run, "resolved_claims"))
        for item_run in valid_item_runs
    )
    covered_asset_keys = _covered_asset_keys(item_runs)
    risks = _risks_at_boundary(run)

    return {
        "assets_total": Asset.objects.filter(environment_id=run.environment_id).count(),
        "assets_covered": len(covered_asset_keys),
        "inspection_item_count": len(item_runs),
        "risk_total": risks.count(),
        "p1_count": risks.filter(severity="P1").count(),
        "p2_count": risks.filter(severity="P2").count(),
        "new_count": _history_count(run, Risk.Status.NEW),
        "worsened_count": _history_count(run, Risk.Status.WORSENED),
        "recovered_count": _history_count(run, Risk.Status.RECOVERED),
        "pending_action_count": risks.filter(status=Risk.Status.PENDING_ACTION).count(),
        "pending_reverify_count": risks.filter(status=Risk.Status.PENDING_REVERIFY).count(),
        "code_only_cases": code_only_cases,
        "ai_dependent_cases": ai_dependent_cases,
        "code_coverage_rate": _rate(resolved_claim_count, required_claim_count),
        "deterministic_deflection_rate": _rate(code_only_cases, len(item_runs)),
        "ai_displacement_rate": _rate(
            code_only_cases,
            code_only_cases + ai_dependent_cases,
        ),
        "data_completeness_rate": _rate(len(valid_item_runs), len(item_runs)),
        "summary": {},
    }


def _risks_at_boundary(run):
    return Risk.objects.filter(environment_id=run.environment_id).exclude(
        status__in=TERMINAL_RISK_STATUSES,
    )


def _history_count(run, status):
    return (
        RiskStatusHistory.objects.filter(
            inspection_run=run,
            to_status=status,
        )
        .values("risk_id")
        .distinct()
        .count()
    )


def _summary_claims(item_run, field):
    claims = (item_run.summary or {}).get(field, ())
    return claims if isinstance(claims, (list, tuple)) else ()


def _covered_asset_keys(item_runs):
    keys = set()
    for item_run in item_runs:
        asset_keys = (item_run.asset_scope or {}).get("asset_keys", ())
        if not isinstance(asset_keys, (list, tuple, set)):
            continue
        keys.update(key for key in asset_keys if isinstance(key, str) and key)
    return keys


def _rate(numerator, denominator):
    if not denominator:
        return Decimal("0.000")
    return (
        (Decimal(numerator) * HUNDRED) / Decimal(denominator)
    ).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)


create_daily_snapshot = build_daily_snapshot


__all__ = [
    "build_daily_snapshot",
    "create_daily_snapshot",
]
