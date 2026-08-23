"""Correlate Task 6's persisted active findings into stable risks."""

from collections import defaultdict
import hashlib

from django.db import transaction
from django.utils import timezone

from apps.inspections.models import Finding, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory
from apps.risks.services.lifecycle import (
    TERMINAL_RISK_STATUSES,
    observation_status,
    record_observation,
    severity_rank,
)


def fingerprint_for_finding(finding, *, environment=None, inspection_item=None):
    """Build a cross-run fingerprint from canonical, non-database identities."""

    item_run = getattr(finding, "inspection_item_run", None)
    inspection_item = inspection_item or getattr(item_run, "inspection_item", None)
    inspection_run = getattr(item_run, "inspection_run", None)
    environment = environment or getattr(inspection_run, "environment", None)
    asset = getattr(finding, "asset", None)

    environment_key = getattr(environment, "slug", None) or getattr(environment, "name", "")
    item_key = getattr(inspection_item, "code", "")
    finding_key = getattr(finding, "finding_code", "")
    asset_key = getattr(asset, "external_key", None)
    if not asset_key:
        value = getattr(finding, "value", {}) or {}
        asset_key = value.get("asset_key") or value.get("asset") or "<environment>"

    canonical = "\x1f".join(
        str(part).strip()
        for part in (environment_key, item_key, finding_key, asset_key)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_fingerprint(environment, inspection_item, finding):
    """Compatibility-shaped helper for callers that already have context."""

    return fingerprint_for_finding(
        finding,
        environment=environment,
        inspection_item=inspection_item,
    )


def _observed_at(inspection_run, item_run, findings):
    timestamps = [finding.observed_at for finding in findings if finding.observed_at]
    return max(timestamps or [item_run.finished_at, inspection_run.finished_at, timezone.now()])


def _risk_key(inspection_item, representative):
    asset_key = getattr(representative.asset, "external_key", None) or "environment"
    return f"{inspection_item.code}:{representative.finding_code}:{asset_key}"[:192]


def _snapshot(fingerprint, findings):
    return {
        "fingerprint": fingerprint,
        "finding_codes": sorted({finding.finding_code for finding in findings}),
        "asset_keys": sorted(
            {
                finding.asset.external_key
                for finding in findings
                if finding.asset is not None
            }
        ),
        "titles": sorted({finding.title for finding in findings}),
    }


def _get_or_create_risk(environment, inspection_item, representative, fingerprint, observed_at):
    defaults = {
        "inspection_item": inspection_item,
        "primary_asset": representative.asset,
        "risk_key": _risk_key(inspection_item, representative),
        "title": representative.title,
        "domain": inspection_item.domain,
        "severity": representative.severity,
        "status": Risk.Status.NEW,
        "current_conclusion": "",
        "impact_summary": "",
        "recommendation": "",
        "first_seen_at": observed_at,
        "last_seen_at": observed_at,
        "occurrence_count": 1,
        "duration_days": 1,
    }
    risk, created = Risk.objects.get_or_create(
        environment=environment,
        fingerprint=fingerprint,
        defaults=defaults,
    )
    if not created:
        risk = Risk.objects.select_for_update().get(pk=risk.pk)
    return risk, created


def _update_existing_risk(risk, representative, inspection_item, status_after, observed_at, run_date):
    previous_severity = risk.severity
    risk.severity = (
        representative.severity
        if severity_rank(representative.severity) < severity_rank(previous_severity)
        else previous_severity
    )
    risk.status = status_after
    risk.primary_asset = representative.asset or risk.primary_asset
    risk.title = representative.title
    risk.domain = inspection_item.domain
    risk.last_seen_at = max(risk.last_seen_at, observed_at)
    risk.occurrence_count += 1
    risk.duration_days = max(1, (run_date - risk.first_seen_at.date()).days + 1)
    risk.recovered_at = None
    risk.save(
        update_fields=[
            "primary_asset",
            "title",
            "domain",
            "severity",
            "status",
            "last_seen_at",
            "recovered_at",
            "occurrence_count",
            "duration_days",
            "updated_at",
        ]
    )


def _history_reason(from_status, status_after, representative):
    if status_after == Risk.Status.WORSENED:
        return f"Active finding severity worsened to {representative.severity}"
    if from_status == Risk.Status.NEW:
        return "Initial active finding correlated"
    return "Active finding persisted"


def _update_run_risk_count(inspection_run):
    count = (
        Risk.objects.filter(environment_id=inspection_run.environment_id)
        .exclude(status__in=TERMINAL_RISK_STATUSES)
        .count()
    )
    InspectionRun.objects.filter(pk=inspection_run.pk).update(risk_count=count)
    inspection_run.risk_count = count
    return count


def correlate_run(inspection_run):
    """Correlate all active Findings from successful item runs in one run."""

    correlated = []
    with transaction.atomic():
        item_runs = (
            InspectionItemRun.objects.filter(
                inspection_run=inspection_run,
                status=InspectionItemRun.Status.SUCCEEDED,
            )
            .select_related("inspection_item", "inspection_run__environment")
            .order_by("inspection_item__code", "pk")
        )
        for item_run in item_runs:
            findings = list(
                Finding.objects.filter(
                    inspection_item_run=item_run,
                    status=Finding.Status.ACTIVE,
                )
                .select_related("asset")
                .order_by("finding_code", "pk")
            )
            grouped = defaultdict(list)
            for finding in findings:
                fingerprint = fingerprint_for_finding(
                    finding,
                    environment=inspection_run.environment,
                    inspection_item=item_run.inspection_item,
                )
                grouped[fingerprint].append(finding)

            for fingerprint, risk_findings in grouped.items():
                representative = min(
                    risk_findings,
                    key=lambda finding: severity_rank(finding.severity),
                )
                observed_at = _observed_at(inspection_run, item_run, risk_findings)
                risk, created = _get_or_create_risk(
                    inspection_run.environment,
                    item_run.inspection_item,
                    representative,
                    fingerprint,
                    observed_at,
                )
                if not created and RiskObservation.objects.filter(
                    risk=risk,
                    inspection_run=inspection_run,
                ).exists():
                    correlated.append(risk)
                    continue

                from_status = None if created else risk.status
                status_after = (
                    Risk.Status.NEW
                    if created
                    else observation_status(risk, representative.severity)
                )
                if not created:
                    _update_existing_risk(
                        risk,
                        representative,
                        item_run.inspection_item,
                        status_after,
                        observed_at,
                        inspection_run.run_date,
                    )
                _observation, observation_created = record_observation(
                    risk=risk,
                    inspection_run=inspection_run,
                    inspection_item_run=item_run,
                    observed_at=observed_at,
                    detected=True,
                    severity=representative.severity,
                    status_after=status_after,
                    finding_count=len(risk_findings),
                    snapshot=_snapshot(fingerprint, risk_findings),
                )
                if observation_created:
                    RiskStatusHistory.objects.create(
                        risk=risk,
                        from_status=from_status,
                        to_status=status_after,
                        reason=(
                            "Initial active finding correlated"
                            if created
                            else _history_reason(from_status, status_after, representative)
                        ),
                        source=RiskStatusHistory.Source.SYSTEM,
                        inspection_run=inspection_run,
                    )
                correlated.append(risk)

        _update_run_risk_count(inspection_run)
    return correlated


# Names used by batch callers in earlier design drafts.
correlate_findings = correlate_run
correlate_inspection_run = correlate_run
correlate_risks = correlate_run


__all__ = [
    "build_fingerprint",
    "correlate_findings",
    "correlate_inspection_run",
    "correlate_risks",
    "correlate_run",
    "fingerprint_for_finding",
]
