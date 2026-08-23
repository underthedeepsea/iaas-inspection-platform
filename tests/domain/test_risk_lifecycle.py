from datetime import date, datetime, timezone as dt_timezone
import uuid

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import Finding, InspectionItem, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory


DAY_ONE = date(2026, 8, 23)


def make_environment():
    return Environment.objects.create(
        name="Risk lifecycle test",
        slug=f"risk-lifecycle-{uuid.uuid4().hex}",
    )


def make_item():
    return InspectionItem.objects.create(
        code=f"risk.lifecycle.{uuid.uuid4().hex}",
        name="Risk lifecycle",
        domain="PLATFORM",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


def make_run(environment, item, run_date, *, summary=None, run_status=None):
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=run_status or InspectionRun.Status.SUCCEEDED,
        finished_at=timezone.make_aware(
            datetime.combine(run_date, datetime.min.time()),
            dt_timezone.utc,
        ),
    )
    item_run = InspectionItemRun.objects.create(
        inspection_run=run,
        inspection_item=item,
        status=InspectionItemRun.Status.SUCCEEDED,
        summary=summary or {"data_valid": True},
        finished_at=run.finished_at,
    )
    return run, item_run


def make_finding(item_run, asset, *, severity="P2", status=Finding.Status.ACTIVE):
    return Finding.objects.create(
        inspection_item_run=item_run,
        asset=asset,
        finding_code="QUEUE_PRESSURE",
        title="Queue pressure",
        category="performance",
        severity=severity,
        status=status,
        value={"queue_depth": 10},
        source_type=Finding.SourceType.METRIC,
        observed_at=item_run.finished_at,
    )


@pytest.mark.django_db
def test_same_fingerprint_across_days_keeps_uuid_and_persists_history_and_actual_count():
    from apps.risks.services.correlation import correlate_run

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    first_run, first_item_run = make_run(environment, item, DAY_ONE)
    make_finding(first_item_run, asset)

    first_risk = correlate_run(first_run)[0]

    second_run, second_item_run = make_run(environment, item, date(2026, 8, 24))
    make_finding(second_item_run, asset)
    second_risk = correlate_run(second_run)[0]

    assert second_risk.id == first_risk.id
    assert second_risk.occurrence_count == 2
    assert second_risk.status == Risk.Status.PERSISTING
    assert RiskObservation.objects.filter(risk=first_risk).count() == 2
    assert RiskStatusHistory.objects.filter(risk=first_risk).count() == 2
    assert second_run.risk_count == 1


@pytest.mark.django_db
def test_more_severe_observation_moves_a_persisting_risk_to_worsened():
    from apps.risks.services.correlation import correlate_run

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    first_run, first_item_run = make_run(environment, item, DAY_ONE)
    make_finding(first_item_run, asset, severity="P3")
    risk = correlate_run(first_run)[0]

    second_run, second_item_run = make_run(environment, item, date(2026, 8, 24))
    make_finding(second_item_run, asset, severity="P1")
    correlate_run(second_run)

    risk.refresh_from_db()
    assert risk.status == Risk.Status.WORSENED
    assert risk.severity == "P1"
    assert RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.WORSENED,
        inspection_run=second_run,
    ).exists()


@pytest.mark.django_db
def test_mark_handled_only_enters_pending_reverify_and_never_recovered():
    from apps.risks.services.correlation import correlate_run
    from apps.risks.services.lifecycle import mark_handled

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    run, item_run = make_run(environment, item, DAY_ONE)
    make_finding(item_run, asset)
    risk = correlate_run(run)[0]

    mark_handled(risk, reason="Operator applied the remediation")

    risk.refresh_from_db()
    assert risk.status == Risk.Status.PENDING_REVERIFY
    assert not RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.RECOVERED,
    ).exists()
    history = RiskStatusHistory.objects.filter(risk=risk).latest("created_at")
    assert history.source == RiskStatusHistory.Source.HUMAN
    assert history.to_status == Risk.Status.PENDING_REVERIFY


@pytest.mark.django_db
def test_successful_reverify_requires_later_valid_completed_item_run_and_recovers():
    from apps.risks.services.correlation import correlate_run
    from apps.risks.services.lifecycle import mark_handled
    from apps.risks.services.reverify import reverify_pending_risks

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    first_run, first_item_run = make_run(environment, item, DAY_ONE)
    make_finding(first_item_run, asset)
    risk = correlate_run(first_run)[0]
    mark_handled(risk)

    second_run, second_item_run = make_run(environment, item, date(2026, 8, 24))
    reverify_pending_risks(second_run)

    risk.refresh_from_db()
    assert risk.status == Risk.Status.RECOVERED
    observation = RiskObservation.objects.get(risk=risk, inspection_run=second_run)
    assert observation.detected is False
    assert observation.status_after == Risk.Status.RECOVERED
    assert RiskStatusHistory.objects.filter(
        risk=risk,
        source=RiskStatusHistory.Source.REVERIFY,
        to_status=Risk.Status.RECOVERED,
        inspection_run=second_run,
    ).exists()
    second_run.refresh_from_db()
    assert second_run.risk_count == 0


@pytest.mark.django_db
def test_failed_reverify_with_a_matching_finding_stays_active_and_can_worsen():
    from apps.risks.services.correlation import correlate_run
    from apps.risks.services.lifecycle import mark_handled
    from apps.risks.services.reverify import reverify_pending_risks

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    first_run, first_item_run = make_run(environment, item, DAY_ONE)
    make_finding(first_item_run, asset, severity="P2")
    risk = correlate_run(first_run)[0]
    mark_handled(risk)

    second_run, second_item_run = make_run(environment, item, date(2026, 8, 24))
    make_finding(second_item_run, asset, severity="P1")
    reverify_pending_risks(second_run)

    risk.refresh_from_db()
    assert risk.status == Risk.Status.WORSENED
    observation = RiskObservation.objects.get(risk=risk, inspection_run=second_run)
    assert observation.detected is True
    assert observation.status_after == Risk.Status.WORSENED
    assert RiskStatusHistory.objects.filter(
        risk=risk,
        source=RiskStatusHistory.Source.SYSTEM,
        to_status=Risk.Status.WORSENED,
        inspection_run=second_run,
    ).exists()


@pytest.mark.django_db
def test_reverify_does_not_recover_from_invalid_or_unexecuted_evidence():
    from apps.risks.services.correlation import correlate_run
    from apps.risks.services.lifecycle import mark_handled
    from apps.risks.services.reverify import reverify_pending_risks

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    first_run, first_item_run = make_run(environment, item, DAY_ONE)
    make_finding(first_item_run, asset)
    risk = correlate_run(first_run)[0]
    mark_handled(risk)

    second_run, _ = make_run(
        environment,
        item,
        date(2026, 8, 24),
        summary={"data_valid": False},
        run_status=InspectionRun.Status.PARTIAL,
    )
    reverify_pending_risks(second_run)

    risk.refresh_from_db()
    assert risk.status == Risk.Status.PENDING_REVERIFY
    assert not RiskObservation.objects.filter(risk=risk, inspection_run=second_run).exists()
