"""Automatic reverification for handled risks."""

from django.db import transaction
from django.utils import timezone

from apps.inspections.models import Finding, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory
from apps.risks.services.correlation import (
    _update_run_risk_count,
    correlate_run,
    fingerprint_for_finding,
)
from apps.risks.services.lifecycle import record_observation


def _valid_item_runs(inspection_run):
    # Task 6 marks completion on InspectionItemRun; the aggregate run can
    # remain PENDING while callers execute one item at a time.
    if inspection_run.status == InspectionRun.Status.FAILED:
        return {}
    item_runs = (
        InspectionItemRun.objects.filter(
            inspection_run=inspection_run,
            status=InspectionItemRun.Status.SUCCEEDED,
        )
        .select_related("inspection_item")
    )
    return {
        item_run.inspection_item_id: item_run
        for item_run in item_runs
        if (item_run.summary or {}).get("data_valid", True)
    }


def _has_prior_observation(risk, inspection_run):
    return RiskObservation.objects.filter(
        risk=risk,
        detected=True,
        inspection_run__run_date__lt=inspection_run.run_date,
    ).exists()


def _matching_non_active_finding(risk, item_run, environment, inspection_item):
    findings = (
        Finding.objects.filter(inspection_item_run=item_run)
        .select_related("asset")
        .order_by("pk")
    )
    for finding in findings:
        if fingerprint_for_finding(
            finding,
            environment=environment,
            inspection_item=inspection_item,
        ) == risk.fingerprint:
            return finding
    return None


def reverify_pending_risks(inspection_run):
    """Reverify pending risks using a later, successful, valid item run.

    Active Findings are correlated first.  A pending risk is recovered only
    when its same InspectionItem completed validly and emitted no matching
    Finding at all.
    """

    item_runs = _valid_item_runs(inspection_run)
    if not item_runs:
        return []

    # This also handles a failed reverification: an active matching Finding
    # moves PENDING_REVERIFY to PERSISTING/WORSENED before missing findings
    # are evaluated below.
    correlate_run(inspection_run)

    recovered = []
    with transaction.atomic():
        pending = (
            Risk.objects.select_for_update()
            .filter(
                environment_id=inspection_run.environment_id,
                status=Risk.Status.PENDING_REVERIFY,
                inspection_item_id__in=item_runs.keys(),
            )
            .select_related("inspection_item")
        )
        for risk in pending:
            item_run = item_runs[risk.inspection_item_id]
            if not _has_prior_observation(risk, inspection_run):
                continue
            matching_finding = _matching_non_active_finding(
                risk,
                item_run,
                inspection_run.environment,
                risk.inspection_item,
            )
            if matching_finding is not None:
                # Invalid/resolved evidence is not proof of recovery.
                continue

            observed_at = item_run.finished_at or inspection_run.finished_at or timezone.now()
            _observation, created = record_observation(
                risk=risk,
                inspection_run=inspection_run,
                inspection_item_run=item_run,
                observed_at=observed_at,
                detected=False,
                severity=risk.severity,
                status_after=Risk.Status.RECOVERED,
                snapshot={
                    "fingerprint": risk.fingerprint,
                    "reason": "no active matching finding in later valid run",
                },
            )
            if not created:
                continue
            from_status = risk.status
            risk.status = Risk.Status.RECOVERED
            risk.recovered_at = timezone.now()
            risk.save(update_fields=["status", "recovered_at", "updated_at"])
            RiskStatusHistory.objects.create(
                risk=risk,
                from_status=from_status,
                to_status=Risk.Status.RECOVERED,
                reason="Reverification found no active matching finding",
                source=RiskStatusHistory.Source.REVERIFY,
                inspection_run=inspection_run,
            )
            recovered.append(risk)

        _update_run_risk_count(inspection_run)
    return recovered


reverify_run = reverify_pending_risks
reverify_risks = reverify_pending_risks
automatic_reverify = reverify_pending_risks


__all__ = [
    "automatic_reverify",
    "reverify_pending_risks",
    "reverify_risks",
    "reverify_run",
]
