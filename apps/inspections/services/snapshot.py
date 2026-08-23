"""Persist one deterministic daily snapshot from a completed inspection run."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from apps.assets.models import Asset
from apps.inspections.models import DailySnapshot, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory
from apps.risks.services.lifecycle import TERMINAL_RISK_STATUSES


RATE_QUANTUM = Decimal("0.001")
HUNDRED = Decimal("100")
COMPLETED_RUN_STATUSES = frozenset(
    {
        InspectionRun.Status.SUCCEEDED,
        InspectionRun.Status.PARTIAL,
        InspectionRun.Status.FAILED,
    }
)
COMPLETED_ITEM_STATUSES = frozenset(
    {
        InspectionItemRun.Status.SUCCEEDED,
        InspectionItemRun.Status.FAILED,
    }
)


def build_daily_snapshot(inspection_run, snapshot_date=None):
    """Create or refresh the snapshot for one completed ``InspectionRun``."""

    with transaction.atomic():
        run = (
            InspectionRun.objects.select_for_update()
            .select_related("environment")
            .get(pk=inspection_run.pk)
        )
        if run.status not in COMPLETED_RUN_STATUSES or run.finished_at is None:
            raise ValueError("daily snapshots require a completed inspection run")

        snapshot_date = snapshot_date or run.run_date
        snapshot = (
            DailySnapshot.objects.select_for_update()
            .filter(environment_id=run.environment_id, snapshot_date=snapshot_date)
            .first()
        )
        if snapshot is not None and snapshot.inspection_run_id != run.pk:
            raise ValueError(
                "daily snapshot already exists for this date with a different inspection run"
            )

        item_runs = list(
            InspectionItemRun.objects.filter(
                inspection_run=run,
                status__in=COMPLETED_ITEM_STATUSES,
                finished_at__isnull=False,
            ).only("status", "summary", "asset_scope", "ai_admission_status")
        )
        stats = _snapshot_stats(run, item_runs)

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
        if (
            item_run.status == InspectionItemRun.Status.SUCCEEDED
            and (item_run.summary or {}).get("data_valid") is True
        )
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
    risk_counts = _risk_counts_at_boundary(run)

    return {
        "assets_total": Asset.objects.filter(environment_id=run.environment_id).count(),
        "assets_covered": len(covered_asset_keys),
        "inspection_item_count": len(item_runs),
        "risk_total": risk_counts["risk_total"],
        "p1_count": risk_counts["p1_count"],
        "p2_count": risk_counts["p2_count"],
        "new_count": _history_count(run, Risk.Status.NEW),
        "worsened_count": _history_count(run, Risk.Status.WORSENED),
        "recovered_count": _history_count(run, Risk.Status.RECOVERED),
        "pending_action_count": risk_counts["pending_action_count"],
        "pending_reverify_count": risk_counts["pending_reverify_count"],
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


def _risk_counts_at_boundary(run):
    boundary = run.finished_at
    risks = list(Risk.objects.filter(environment_id=run.environment_id))
    histories_by_risk = defaultdict(list)
    for history in (
        RiskStatusHistory.objects.filter(risk__environment_id=run.environment_id)
        .select_related("inspection_run")
        .order_by("created_at", "pk")
    ):
        event_time = _lifecycle_event_time(history.inspection_run, history.created_at)
        if event_time <= boundary:
            histories_by_risk[history.risk_id].append(history)

    observations_by_risk = defaultdict(list)
    for observation in (
        RiskObservation.objects.filter(risk__environment_id=run.environment_id)
        .select_related("inspection_run")
        .order_by("created_at", "pk")
    ):
        event_time = _lifecycle_event_time(
            observation.inspection_run,
            observation.observed_at,
        )
        if event_time <= boundary:
            observations_by_risk[observation.risk_id].append(observation)

    states = []
    for risk in risks:
        histories = histories_by_risk.get(risk.pk, ())
        observations = observations_by_risk.get(risk.pk, ())
        if not histories and not observations and risk.first_seen_at > boundary:
            continue

        status = _status_at_boundary(risk, histories, observations)
        if status in TERMINAL_RISK_STATUSES:
            continue
        severity = _severity_at_boundary(risk, observations)
        states.append((status, severity))

    return {
        "risk_total": len(states),
        "p1_count": sum(severity == "P1" for _status, severity in states),
        "p2_count": sum(severity == "P2" for _status, severity in states),
        "pending_action_count": sum(
            status == Risk.Status.PENDING_ACTION for status, _severity in states
        ),
        "pending_reverify_count": sum(
            status == Risk.Status.PENDING_REVERIFY for status, _severity in states
        ),
    }


def _lifecycle_event_time(inspection_run, fallback):
    return getattr(inspection_run, "finished_at", None) or fallback


def _status_at_boundary(risk, histories, observations):
    events = [
        (
            _lifecycle_event_time(history.inspection_run, history.created_at),
            2,
            history.pk,
            history.to_status,
        )
        for history in histories
    ]
    events.extend(
        (
            _lifecycle_event_time(observation.inspection_run, observation.observed_at),
            1,
            observation.pk,
            observation.status_after,
        )
        for observation in observations
    )
    if not events:
        return risk.status
    return max(events, key=lambda event: (event[0], event[1], event[2]))[3]


def _severity_at_boundary(risk, observations):
    if not observations:
        return risk.severity
    return max(
        observations,
        key=lambda observation: (
            _lifecycle_event_time(observation.inspection_run, observation.observed_at),
            observation.pk,
        ),
    ).severity


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
