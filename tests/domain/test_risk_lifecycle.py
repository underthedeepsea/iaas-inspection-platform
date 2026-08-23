from datetime import date, datetime, timedelta, timezone as dt_timezone
import importlib
import uuid

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import Finding, InspectionItem, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory


DAY_ONE = date(2026, 8, 23)
UNSET = object()


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


def make_run(
    environment,
    item,
    run_date,
    *,
    summary=None,
    run_status=None,
    item_status=None,
    run_finished_at=UNSET,
    item_finished_at=UNSET,
):
    if run_finished_at is UNSET:
        run_finished_at = timezone.make_aware(
            datetime.combine(run_date, datetime.min.time()),
            dt_timezone.utc,
        )
    if item_finished_at is UNSET:
        item_finished_at = run_finished_at
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=run_status or InspectionRun.Status.SUCCEEDED,
        finished_at=run_finished_at,
    )
    item_run = InspectionItemRun.objects.create(
        inspection_run=run,
        inspection_item=item,
        status=item_status or InspectionItemRun.Status.SUCCEEDED,
        summary={"data_valid": True} if summary is None else summary,
        finished_at=item_finished_at,
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


def make_post_handle_run(environment, item, pending_history, *, run_date=None, **kwargs):
    completion = pending_history.created_at + timedelta(minutes=1)
    return make_run(
        environment,
        item,
        run_date or completion.date(),
        run_finished_at=completion,
        item_finished_at=completion,
        **kwargs,
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
    correlate_run(first_run)

    first_observation = RiskObservation.objects.get(risk=first_risk, inspection_run=first_run)
    first_history = RiskStatusHistory.objects.get(risk=first_risk, inspection_run=first_run)
    assert first_risk.occurrence_count == 1
    assert first_observation.inspection_item_run_id == first_item_run.id
    assert first_observation.detected is True
    assert first_observation.severity == "P2"
    assert first_observation.status_after == Risk.Status.NEW
    assert first_observation.finding_count == 1
    assert first_observation.snapshot["fingerprint"] == first_risk.fingerprint
    assert first_history.from_status is None
    assert first_history.to_status == Risk.Status.NEW
    assert first_history.source == RiskStatusHistory.Source.SYSTEM
    assert first_history.reason == "Initial active finding correlated"

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
def test_correlation_counts_only_distinct_risks_observed_in_this_run():
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
    correlate_run(first_run)
    stale_risk = Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key="stale-risk",
        fingerprint="stale-fingerprint",
        title="Stale risk",
        domain="PLATFORM",
        severity="P2",
        status=Risk.Status.PERSISTING,
        first_seen_at=first_run.finished_at,
        last_seen_at=first_run.finished_at,
    )

    second_run, second_item_run = make_run(environment, item, date(2026, 8, 24))
    make_finding(second_item_run, asset)
    correlate_run(second_run)

    assert Risk.objects.filter(environment=environment).count() == 2
    assert stale_risk.id != RiskObservation.objects.get(inspection_run=second_run).risk_id
    assert second_run.risk_count == 1


@pytest.mark.django_db
def test_fingerprint_uses_typed_asset_identity_and_ignores_ids_or_value_dicts():
    from apps.risks.services.correlation import (
        ENVIRONMENT_ASSET_SENTINEL,
        canonical_fingerprint,
        fingerprint_for_finding,
    )

    environment = make_environment()
    item = make_item()
    asset = Asset.objects.create(
        environment=environment,
        external_key="worker-0",
        asset_type=Asset.AssetType.HOST,
        name="worker-0",
    )
    run, item_run = make_run(environment, item, DAY_ONE)
    finding = make_finding(item_run, asset)

    equivalent = canonical_fingerprint(environment.slug, item.code, "QUEUE_PRESSURE", "worker-0")
    assert fingerprint_for_finding(finding) == equivalent
    assert canonical_fingerprint(environment.slug, item.code, "QUEUE_PRESSURE", "worker-0") == equivalent
    assert canonical_fingerprint(environment.slug, item.code, "QUEUE_PRESSURE", "worker-0") != canonical_fingerprint(
        environment.slug, item.code, "QUEUE_PRESSURE", "worker-1"
    )

    finding.asset = None
    finding.value = {"asset_key": "worker-0"}
    sentinel_fingerprint = fingerprint_for_finding(
        finding,
        environment=environment,
        inspection_item=item,
    )
    finding.value = {"asset_key": "worker-1"}
    assert sentinel_fingerprint == fingerprint_for_finding(
        finding,
        environment=environment,
        inspection_item=item,
    )
    assert sentinel_fingerprint == canonical_fingerprint(
        environment.slug,
        item.code,
        "QUEUE_PRESSURE",
        ENVIRONMENT_ASSET_SENTINEL,
    )


@pytest.mark.django_db
def test_public_transition_api_cannot_recover_a_risk():
    from apps.risks.services.correlation import correlate_run
    from apps.risks.services.lifecycle import transition_risk

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

    with pytest.raises(ValueError, match="verified reverification"):
        transition_risk(risk, Risk.Status.RECOVERED, reason="manual recovery")

    risk.refresh_from_db()
    assert risk.status == Risk.Status.NEW
    assert not RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.RECOVERED,
    ).exists()


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

    pending_history = RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.PENDING_REVERIFY,
    ).latest("created_at")
    second_run, second_item_run = make_post_handle_run(environment, item, pending_history)
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
    observation_history = RiskStatusHistory.objects.get(
        risk=risk,
        source=RiskStatusHistory.Source.REVERIFY,
        inspection_run=second_run,
    )
    assert observation_history.from_status == Risk.Status.PENDING_REVERIFY
    assert observation_history.reason == "Reverification found no active matching finding"
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

    pending_history = RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.PENDING_REVERIFY,
    ).latest("created_at")
    second_run, second_item_run = make_post_handle_run(environment, item, pending_history)
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
def test_failed_reverify_with_same_severity_returns_to_persisting():
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

    pending_history = RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.PENDING_REVERIFY,
    ).latest("created_at")
    second_run, second_item_run = make_post_handle_run(environment, item, pending_history)
    make_finding(second_item_run, asset, severity="P2")
    reverify_pending_risks(second_run)

    risk.refresh_from_db()
    assert risk.status == Risk.Status.PERSISTING
    observation = RiskObservation.objects.get(risk=risk, inspection_run=second_run)
    assert observation.detected is True
    assert observation.status_after == Risk.Status.PERSISTING
    history = RiskStatusHistory.objects.get(risk=risk, inspection_run=second_run)
    assert history.from_status == Risk.Status.PENDING_REVERIFY
    assert history.to_status == Risk.Status.PERSISTING
    assert history.reason == "Active finding persisted"


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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_case",
    [
        "missing_validity",
        "partial_run",
        "failed_run",
        "unexecuted_item",
        "missing_item_finished_at",
        "missing_run_finished_at",
        "before_handle",
        "item_before_handle",
    ],
)
def test_reverify_requires_explicit_valid_completed_run_after_handling(invalid_case):
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
    pending_history = RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.PENDING_REVERIFY,
    ).latest("created_at")

    kwargs = {}
    if invalid_case == "missing_validity":
        kwargs["summary"] = {}
    elif invalid_case == "partial_run":
        kwargs["run_status"] = InspectionRun.Status.PARTIAL
    elif invalid_case == "failed_run":
        kwargs["run_status"] = InspectionRun.Status.FAILED
    elif invalid_case == "unexecuted_item":
        kwargs["item_status"] = InspectionItemRun.Status.PENDING
    elif invalid_case == "missing_item_finished_at":
        kwargs["item_finished_at"] = None
    elif invalid_case == "missing_run_finished_at":
        kwargs["run_finished_at"] = None
    elif invalid_case == "before_handle":
        kwargs["run_finished_at"] = pending_history.created_at - timedelta(seconds=1)
        kwargs["item_finished_at"] = kwargs["run_finished_at"]
    elif invalid_case == "item_before_handle":
        kwargs["run_finished_at"] = pending_history.created_at + timedelta(seconds=1)
        kwargs["item_finished_at"] = pending_history.created_at - timedelta(seconds=1)

    second_run, _ = make_run(
        environment,
        item,
        pending_history.created_at.date(),
        **kwargs,
    )
    reverify_pending_risks(second_run)

    risk.refresh_from_db()
    assert risk.status == Risk.Status.PENDING_REVERIFY
    assert not RiskObservation.objects.filter(risk=risk, inspection_run=second_run).exists()


def test_known_severity_order_and_unknown_severity_rejection():
    from apps.risks.services.lifecycle import severity_rank

    assert [severity_rank(value) for value in ("P1", "P2", "P3", "P4")] == [1, 2, 3, 4]
    with pytest.raises(ValueError, match="unknown severity"):
        severity_rank("P0")


def test_legacy_status_migration_has_documented_semantic_mappings():
    migration = importlib.import_module("apps.risks.migrations.0002_risk_lifecycle_statuses")

    assert migration.LEGACY_STATUS_MAPPING == {
        "ACTIVE": "PERSISTING",
        "ACKNOWLEDGED": "INVESTIGATING",
        "MITIGATING": "IN_PROGRESS",
        "CLOSED": "RECOVERED",
        "INVALID": "FALSE_POSITIVE",
    }


def test_legacy_status_migration_forward_and_reverse_transforms_historical_rows():
    migration = importlib.import_module("apps.risks.migrations.0002_risk_lifecycle_statuses")

    class FakeQuerySet:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, **conditions):
            return FakeQuerySet(
                [
                    row
                    for row in self.rows
                    if all(row.get(field) == value for field, value in conditions.items())
                ]
            )

        def update(self, **values):
            for row in self.rows:
                row.update(values)

    class FakeManager:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, **conditions):
            return FakeQuerySet(
                [
                    row
                    for row in self.rows
                    if all(row.get(field) == value for field, value in conditions.items())
                ]
            )

    class FakeModel:
        def __init__(self, rows):
            self.objects = FakeManager(rows)

    class FakeApps:
        def __init__(self, models):
            self.models = models

        def get_model(self, app_label, model_name):
            return self.models[model_name]

    risk_rows = [{"status": value} for value in ("ACTIVE", "CLOSED", "RECOVERED")]
    observation_rows = [
        {"status_after": value}
        for value in ("ACTIVE", "CLOSED", "RECOVERED")
    ]
    history_rows = [
        {"from_status": "ACTIVE", "to_status": "CLOSED"},
        {"from_status": None, "to_status": "INVALID"},
    ]
    apps = FakeApps(
        {
            "Risk": FakeModel(risk_rows),
            "RiskObservation": FakeModel(observation_rows),
            "RiskStatusHistory": FakeModel(history_rows),
        }
    )

    migration._migrate_legacy_statuses(apps, None)
    assert [row["status"] for row in risk_rows] == ["PERSISTING", "RECOVERED", "RECOVERED"]
    assert [row["status_after"] for row in observation_rows] == [
        "PERSISTING",
        "RECOVERED",
        "RECOVERED",
    ]
    assert history_rows == [
        {"from_status": "PERSISTING", "to_status": "RECOVERED"},
        {"from_status": None, "to_status": "FALSE_POSITIVE"},
    ]

    reverse_risk_rows = [
        {"status": value}
        for value in (
            "PERSISTING",
            "WORSENED",
            "INVESTIGATING",
            "LOCATED",
            "PENDING_ACTION",
            "IN_PROGRESS",
            "PENDING_REVERIFY",
            "RECOVERED",
            "IGNORED",
            "FALSE_POSITIVE",
        )
    ]
    reverse_observation_rows = [
        {"status_after": value}
        for value in (
            "PERSISTING",
            "WORSENED",
            "INVESTIGATING",
            "LOCATED",
            "PENDING_ACTION",
            "IN_PROGRESS",
            "PENDING_REVERIFY",
            "RECOVERED",
            "IGNORED",
            "FALSE_POSITIVE",
        )
    ]
    reverse_history_rows = [{"from_status": "WORSENED", "to_status": "RECOVERED"}]
    reverse_apps = FakeApps(
        {
            "Risk": FakeModel(reverse_risk_rows),
            "RiskObservation": FakeModel(reverse_observation_rows),
            "RiskStatusHistory": FakeModel(reverse_history_rows),
        }
    )

    migration._restore_legacy_statuses(reverse_apps, None)
    assert [row["status"] for row in reverse_risk_rows] == [
        "ACTIVE",
        "ACTIVE",
        "ACKNOWLEDGED",
        "ACKNOWLEDGED",
        "MITIGATING",
        "MITIGATING",
        "MITIGATING",
        "RECOVERED",
        "INVALID",
        "INVALID",
    ]
    assert [row["status_after"] for row in reverse_observation_rows] == [
        "ACTIVE",
        "ACTIVE",
        "ACKNOWLEDGED",
        "ACKNOWLEDGED",
        "MITIGATING",
        "MITIGATING",
        "MITIGATING",
        "RECOVERED",
        "INVALID",
        "INVALID",
    ]
    assert reverse_history_rows == [{"from_status": "ACTIVE", "to_status": "RECOVERED"}]
