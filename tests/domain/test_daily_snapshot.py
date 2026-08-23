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
from apps.risks.models import Risk, RiskStatusHistory


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


def make_run(environment, *, run_date=SNAPSHOT_DATE, finished=True):
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
        status=InspectionRun.Status.SUCCEEDED if finished else InspectionRun.Status.RUNNING,
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
):
    inspection_item = inspection_item or make_item()
    return InspectionItemRun.objects.create(
        inspection_run=inspection_run,
        inspection_item=inspection_item,
        status=(
            InspectionItemRun.Status.SUCCEEDED
            if finished
            else InspectionItemRun.Status.RUNNING
        ),
        ai_admission_status=admission_status,
        summary={
            "data_valid": data_valid,
            "required_claims": list(required_claims or []),
            "resolved_claims": list(resolved_claims or []),
        },
        asset_scope={"asset_keys": list(asset_keys)},
        finished_at=inspection_run.finished_at if finished else None,
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
