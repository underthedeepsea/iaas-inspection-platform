from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
import uuid

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import (
    DailySnapshot,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
)
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory


SNAPSHOT_DATE = date(2026, 8, 23)


def make_environment():
    return Environment.objects.create(
        name="Daily snapshot test",
        slug=f"daily-snapshot-{uuid.uuid4().hex}",
    )


def make_item(*, code=None):
    code = code or f"snapshot.item.{uuid.uuid4().hex}"
    return InspectionItem.objects.create(
        code=code,
        name=code,
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


def make_run(
    environment,
    *,
    run_date=SNAPSHOT_DATE,
    finished=True,
    status=None,
):
    finished_at = (
        timezone.make_aware(
            datetime.combine(run_date, datetime.min.time()),
            dt_timezone.utc,
        )
        if finished
        else None
    )
    return InspectionRun.objects.create(
        environment=environment,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=status
        or (InspectionRun.Status.SUCCEEDED if finished else InspectionRun.Status.RUNNING),
        finished_at=finished_at,
    )


def make_item_run(
    inspection_run,
    inspection_item=None,
    *,
    admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
    data_valid=True,
    required_claims=None,
    resolved_claims=None,
    asset_keys=(),
    finished=True,
    status=None,
):
    inspection_item = inspection_item or make_item()
    return InspectionItemRun.objects.create(
        inspection_run=inspection_run,
        inspection_item=inspection_item,
        status=status
        or (InspectionItemRun.Status.SUCCEEDED if finished else InspectionItemRun.Status.RUNNING),
        ai_admission_status=admission_status,
        summary={
            "data_valid": data_valid,
            "required_claims": list(required_claims or []),
            "resolved_claims": list(resolved_claims or []),
        },
        asset_scope={"asset_keys": list(asset_keys)},
        finished_at=inspection_run.finished_at if finished else None,
    )


def make_observation(
    inspection_run,
    inspection_item_run,
    risk,
    *,
    status_after,
    severity,
    detected=True,
):
    return RiskObservation.objects.create(
        risk=risk,
        inspection_run=inspection_run,
        inspection_item_run=inspection_item_run,
        observed_at=inspection_run.finished_at,
        detected=detected,
        severity=severity,
        status_after=status_after,
    )


def make_risk(inspection_run, item, *, status, severity, code):
    observed_at = inspection_run.finished_at
    return Risk.objects.create(
        environment=inspection_run.environment,
        inspection_item=item,
        risk_key=code,
        fingerprint=f"{code}-{uuid.uuid4().hex}",
        title=code,
        domain="TEST",
        severity=severity,
        status=status,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )


@pytest.mark.django_db
def test_daily_snapshot_counts_literal_risks_and_run_scoped_status_transitions():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    item = make_item()
    run = make_run(environment)
    make_item_run(run, item)
    other_run = make_run(environment, run_date=date(2026, 8, 24))
    make_item_run(other_run, make_item())

    risks = {
        "new": make_risk(run, item, status=Risk.Status.NEW, severity="P1", code="new"),
        "worsened": make_risk(
            run,
            item,
            status=Risk.Status.WORSENED,
            severity="P1",
            code="worsened",
        ),
        "pending_action": make_risk(
            run,
            item,
            status=Risk.Status.PENDING_ACTION,
            severity="P2",
            code="pending-action",
        ),
        "pending_reverify": make_risk(
            run,
            item,
            status=Risk.Status.PENDING_REVERIFY,
            severity="P3",
            code="pending-reverify",
        ),
        "persisting": make_risk(
            run,
            item,
            status=Risk.Status.PERSISTING,
            severity="P1",
            code="persisting",
        ),
        "recovered": make_risk(
            run,
            item,
            status=Risk.Status.RECOVERED,
            severity="P1",
            code="recovered",
        ),
        "ignored": make_risk(
            run,
            item,
            status=Risk.Status.IGNORED,
            severity="P2",
            code="ignored",
        ),
        "false_positive": make_risk(
            run,
            item,
            status=Risk.Status.FALSE_POSITIVE,
            severity="P2",
            code="false-positive",
        ),
    }
    RiskStatusHistory.objects.create(
        risk=risks["new"],
        from_status=None,
        to_status=Risk.Status.NEW,
        source=RiskStatusHistory.Source.SYSTEM,
        inspection_run=run,
    )
    RiskStatusHistory.objects.create(
        risk=risks["worsened"],
        from_status=Risk.Status.PERSISTING,
        to_status=Risk.Status.WORSENED,
        source=RiskStatusHistory.Source.SYSTEM,
        inspection_run=run,
    )
    RiskStatusHistory.objects.create(
        risk=risks["recovered"],
        from_status=Risk.Status.PENDING_REVERIFY,
        to_status=Risk.Status.RECOVERED,
        source=RiskStatusHistory.Source.REVERIFY,
        inspection_run=run,
    )
    # This transition belongs to another run and must not leak into the target.
    RiskStatusHistory.objects.create(
        risk=risks["new"],
        from_status=Risk.Status.PERSISTING,
        to_status=Risk.Status.NEW,
        source=RiskStatusHistory.Source.SYSTEM,
        inspection_run=other_run,
    )

    snapshot = build_daily_snapshot(run)

    assert snapshot.environment_id == environment.id
    assert snapshot.snapshot_date == SNAPSHOT_DATE
    assert snapshot.inspection_run_id == run.id
    assert snapshot.risk_total == 5
    assert snapshot.p1_count == 3
    assert snapshot.p2_count == 1
    assert snapshot.new_count == 1
    assert snapshot.worsened_count == 1
    assert snapshot.recovered_count == 1
    assert snapshot.pending_action_count == 1
    assert snapshot.pending_reverify_count == 1


@pytest.mark.django_db
def test_daily_snapshot_counts_valid_code_ai_cases_and_decimal_rates():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    for key in ("asset-a", "asset-b", "asset-c", "asset-d", "asset-e", "asset-f", "asset-g", "asset-h"):
        Asset.objects.create(
            environment=environment,
            external_key=key,
            asset_type=Asset.AssetType.HOST,
            name=key,
        )
    run = make_run(environment)
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
        required_claims=("claim.a", "claim.b"),
        resolved_claims=("claim.a",),
        asset_keys=("asset-a", "asset-b"),
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
        required_claims=("claim.c",),
        resolved_claims=("claim.c",),
        asset_keys=("asset-b", "asset-c"),
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE,
        required_claims=("claim.d", "claim.e", "claim.f"),
        resolved_claims=("claim.d", "claim.e"),
        asset_keys=("asset-c", "asset-d"),
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.DATA_INVALID,
        data_valid=False,
        required_claims=("claim.g", "claim.h"),
        asset_keys=("asset-e",),
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.AI_DEFERRED,
        required_claims=("claim.i", "claim.j"),
        resolved_claims=("claim.i", "claim.j"),
        asset_keys=("asset-f",),
    )
    # A different run must not affect the target's denominator or cases.
    other_run = make_run(environment, run_date=date(2026, 8, 24))
    make_item_run(
        other_run,
        admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
        required_claims=("other.claim",),
        resolved_claims=("other.claim",),
        asset_keys=("asset-g",),
    )

    snapshot = build_daily_snapshot(run)
    snapshot.refresh_from_db()

    assert snapshot.assets_total == 8
    assert snapshot.assets_covered == 6
    assert snapshot.inspection_item_count == 5
    assert snapshot.code_only_cases == 2
    assert snapshot.ai_dependent_cases == 1
    assert snapshot.code_coverage_rate == Decimal("75.000")
    assert snapshot.deterministic_deflection_rate == Decimal("40.000")
    assert snapshot.ai_displacement_rate == Decimal("66.667")
    assert snapshot.data_completeness_rate == Decimal("80.000")


@pytest.mark.django_db
def test_daily_snapshot_retry_updates_same_persisted_row_from_item_scope():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(environment)
    item_run = make_item_run(run, asset_keys=("asset-before",))

    first = build_daily_snapshot(run)
    item_run.asset_scope = {"asset_keys": ["asset-after", "asset-before"]}
    item_run.save(update_fields=["asset_scope"])
    second = build_daily_snapshot(run)

    assert second.pk == first.pk
    assert DailySnapshot.objects.filter(
        environment=environment,
        snapshot_date=SNAPSHOT_DATE,
    ).count() == 1
    assert second.inspection_run_id == run.id
    assert second.assets_covered == 2


@pytest.mark.django_db
def test_daily_snapshot_zero_denominators_are_stored_as_decimal_zero():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(environment)

    snapshot = build_daily_snapshot(run)

    assert snapshot.code_coverage_rate == Decimal("0.000")
    assert snapshot.deterministic_deflection_rate == Decimal("0.000")
    assert snapshot.ai_displacement_rate == Decimal("0.000")
    assert snapshot.data_completeness_rate == Decimal("0.000")


@pytest.mark.django_db
def test_nonterminal_snapshot_opt_in_uses_as_of_without_finishing_run():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(environment, finished=False)
    as_of = timezone.now()
    item_run = make_item_run(run, finished=False)
    item_run.status = InspectionItemRun.Status.SUCCEEDED
    item_run.finished_at = as_of
    item_run.save(update_fields=["status", "finished_at"])
    run.started_at = as_of
    run.total_items = 1
    run.success_items = 1
    run.save(update_fields=["started_at", "total_items", "success_items"])

    snapshot = build_daily_snapshot(run, allow_nonterminal=True, as_of=as_of)

    assert snapshot.inspection_run_id == run.pk
    run.refresh_from_db()
    assert run.status == InspectionRun.Status.RUNNING
    assert run.finished_at is None


@pytest.mark.django_db
def test_nonterminal_snapshot_allows_zero_item_run_with_execution_evidence():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    as_of = timezone.now()
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=SNAPSHOT_DATE,
        trigger_type=InspectionRun.TriggerType.AIRFLOW,
        status=InspectionRun.Status.RUNNING,
        started_at=as_of,
        total_items=0,
        success_items=0,
        failed_items=0,
        config_snapshot={"batch": {"stages": {"execute": True}}},
    )

    snapshot = build_daily_snapshot(run, allow_nonterminal=True, as_of=as_of)

    assert snapshot.inspection_run_id == run.pk
    assert snapshot.inspection_item_count == 0
    run.refresh_from_db()
    assert run.status == InspectionRun.Status.RUNNING
    assert run.finished_at is None


@pytest.mark.django_db
def test_nonterminal_snapshot_rejects_zero_item_run_without_execution_evidence():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    as_of = timezone.now()
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=SNAPSHOT_DATE,
        trigger_type=InspectionRun.TriggerType.AIRFLOW,
        status=InspectionRun.Status.RUNNING,
        started_at=as_of,
        total_items=0,
        success_items=0,
        failed_items=0,
    )

    with pytest.raises(ValueError, match="completed execution"):
        build_daily_snapshot(run, allow_nonterminal=True, as_of=as_of)

    assert DailySnapshot.objects.count() == 0
    run.refresh_from_db()
    assert run.status == InspectionRun.Status.RUNNING
    assert run.finished_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [InspectionRun.Status.PENDING, InspectionRun.Status.RUNNING],
)
def test_nonterminal_snapshot_rejects_pending_or_incomplete_execution(status):
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(environment, finished=False, status=status)
    as_of = timezone.now()

    with pytest.raises(ValueError, match="completed execution"):
        build_daily_snapshot(run, allow_nonterminal=True, as_of=as_of)

    assert DailySnapshot.objects.count() == 0
    run.refresh_from_db()
    assert run.status == status
    assert run.finished_at is None


@pytest.mark.django_db
def test_nonterminal_snapshot_requires_explicit_as_of():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(environment, finished=False)

    with pytest.raises(ValueError, match="explicit as_of"):
        build_daily_snapshot(run, allow_nonterminal=True)

    assert DailySnapshot.objects.count() == 0


@pytest.mark.django_db
def test_daily_snapshot_rejects_different_source_run_for_existing_environment_date():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    first_run = make_run(environment)
    make_item_run(first_run)
    first = build_daily_snapshot(first_run)

    conflicting_run = make_run(environment)
    make_item_run(conflicting_run)

    with pytest.raises(ValueError, match="different inspection run"):
        build_daily_snapshot(conflicting_run)

    persisted = DailySnapshot.objects.get(pk=first.pk)
    assert persisted.inspection_run_id == first_run.id


@pytest.mark.django_db
def test_daily_snapshot_reconstructs_risk_metrics_at_source_run_boundary():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    item = make_item()
    source_run = make_run(environment)
    source_item_run = make_item_run(source_run, item)
    risk = make_risk(
        source_run,
        item,
        status=Risk.Status.NEW,
        severity="P1",
        code="boundary-risk",
    )
    RiskStatusHistory.objects.create(
        risk=risk,
        from_status=None,
        to_status=Risk.Status.NEW,
        source=RiskStatusHistory.Source.SYSTEM,
        inspection_run=source_run,
    )
    make_observation(
        source_run,
        source_item_run,
        risk,
        status_after=Risk.Status.NEW,
        severity="P1",
    )
    prior_run = make_run(environment, run_date=date(2026, 8, 22))
    prior_item_run = make_item_run(prior_run, item)
    # Insert an older event after the source event; ordering must use the
    # persisted run boundary, not history/observation primary-key order.
    RiskStatusHistory.objects.create(
        risk=risk,
        from_status=None,
        to_status=Risk.Status.PENDING_ACTION,
        source=RiskStatusHistory.Source.SYSTEM,
        inspection_run=prior_run,
    )
    make_observation(
        prior_run,
        prior_item_run,
        risk,
        status_after=Risk.Status.PENDING_ACTION,
        severity="P2",
    )

    later_run = make_run(environment, run_date=date(2026, 8, 24))
    later_item_run = make_item_run(later_run, item)
    later_only_risk = make_risk(
        later_run,
        item,
        status=Risk.Status.PENDING_REVERIFY,
        severity="P2",
        code="later-only-risk",
    )
    RiskStatusHistory.objects.create(
        risk=risk,
        from_status=Risk.Status.NEW,
        to_status=Risk.Status.PENDING_ACTION,
        source=RiskStatusHistory.Source.HUMAN,
        inspection_run=later_run,
    )
    make_observation(
        later_run,
        later_item_run,
        risk,
        status_after=Risk.Status.PENDING_ACTION,
        severity="P2",
    )
    RiskStatusHistory.objects.create(
        risk=later_only_risk,
        from_status=None,
        to_status=Risk.Status.PENDING_REVERIFY,
        source=RiskStatusHistory.Source.SYSTEM,
        inspection_run=later_run,
    )
    make_observation(
        later_run,
        later_item_run,
        later_only_risk,
        status_after=Risk.Status.PENDING_REVERIFY,
        severity="P2",
    )
    risk.status = Risk.Status.PENDING_ACTION
    risk.severity = "P2"
    risk.save(update_fields=["status", "severity", "updated_at"])

    snapshot = build_daily_snapshot(source_run)

    assert snapshot.risk_total == 1
    assert snapshot.p1_count == 1
    assert snapshot.p2_count == 0
    assert snapshot.pending_action_count == 0
    assert snapshot.pending_reverify_count == 0


@pytest.mark.django_db
def test_daily_snapshot_accepts_partial_run_and_counts_failed_terminal_items_in_denominators():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(
        environment,
        status=InspectionRun.Status.PARTIAL,
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
        required_claims=("claim.ok",),
        resolved_claims=("claim.ok",),
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE,
        required_claims=("claim.failed", "claim.failed.2"),
        resolved_claims=("claim.failed", "claim.failed.2"),
        status=InspectionItemRun.Status.FAILED,
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
        data_valid=False,
        status=InspectionItemRun.Status.FAILED,
    )

    snapshot = build_daily_snapshot(run)

    assert snapshot.inspection_item_count == 3
    assert snapshot.code_only_cases == 1
    assert snapshot.ai_dependent_cases == 0
    assert snapshot.code_coverage_rate == Decimal("100.000")
    assert snapshot.deterministic_deflection_rate == Decimal("33.333")
    assert snapshot.data_completeness_rate == Decimal("33.333")
    assert snapshot.ai_displacement_rate == Decimal("100.000")


@pytest.mark.django_db
def test_daily_snapshot_invalid_data_is_neither_code_only_nor_ai_dependent():
    from apps.inspections.services.snapshot import build_daily_snapshot

    environment = make_environment()
    run = make_run(environment)
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.NO_AI,
        data_valid=False,
        required_claims=("claim.code",),
        resolved_claims=("claim.code",),
    )
    make_item_run(
        run,
        admission_status=InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE,
        data_valid=False,
        required_claims=("claim.ai",),
        resolved_claims=("claim.ai",),
    )

    snapshot = build_daily_snapshot(run)

    assert snapshot.inspection_item_count == 2
    assert snapshot.code_only_cases == 0
    assert snapshot.ai_dependent_cases == 0
    assert snapshot.code_coverage_rate == Decimal("0.000")
    assert snapshot.deterministic_deflection_rate == Decimal("0.000")
    assert snapshot.ai_displacement_rate == Decimal("0.000")
    assert snapshot.data_completeness_rate == Decimal("0.000")
