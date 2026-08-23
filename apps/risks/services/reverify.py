"""Automatic reverification for handled risks."""

from django.db import transaction
from django.utils import timezone

from apps.inspections.models import Finding, InspectionItemRun, InspectionRun
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory
from apps.risks.services.correlation import (
    _correlate_run_in_transaction,
    _update_run_risk_count,
    fingerprint_for_finding,
)
from apps.risks.services.lifecycle import record_observation


def _valid_item_runs(inspection_run):
    if (
        inspection_run.status != InspectionRun.Status.SUCCEEDED
        or inspection_run.finished_at is None
    ):
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
        if item_run.finished_at is not None
        and (item_run.summary or {}).get("data_valid") is True
    }


def _has_post_handle_completion(risk, inspection_run, item_run):
    pending_history = RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.PENDING_REVERIFY,
    ).order_by("-created_at").first()
    return bool(
        pending_history
        and inspection_run.finished_at
        and item_run.finished_at
        and item_run.finished_at > pending_history.created_at
    )


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

    recovered = []
    with transaction.atomic():
        locked_run = (
            InspectionRun.objects.select_for_update()
            .select_related("environment")
            .get(pk=inspection_run.pk)
        )
        item_runs = _valid_item_runs(locked_run)
        if not item_runs:
            _update_run_risk_count(locked_run)
            return []

        # Lock every risk for the candidate items before correlation.  A
        # concurrent mark_handled therefore either lands before this run is
        # evaluated or waits until it has been fully evaluated.
        locked_risk_ids = list(
            Risk.objects.select_for_update()
            .filter(
                environment_id=locked_run.environment_id,
                inspection_item_id__in=item_runs.keys(),
            )
            .values_list("pk", flat=True)
        )
        pending_risk_ids = list(
            Risk.objects.filter(
                pk__in=locked_risk_ids,
                status=Risk.Status.PENDING_REVERIFY,
            ).values_list("pk", flat=True)
        )

        # This also handles a failed reverification: an active matching
        # Finding moves PENDING_REVERIFY to PERSISTING/WORSENED before
        # missing findings are evaluated below.
        _correlate_run_in_transaction(
            locked_run,
            inspection_item_ids=item_runs.keys(),
        )

        pending = (
            Risk.objects.select_for_update()
            .filter(
                pk__in=pending_risk_ids,
                status=Risk.Status.PENDING_REVERIFY,
            )
            .select_related("inspection_item")
        )
        for risk in pending:
            item_run = item_runs.get(risk.inspection_item_id)
            if item_run is None or not _has_post_handle_completion(
                risk,
                locked_run,
                item_run,
            ):
                continue
            matching_finding = _matching_non_active_finding(
                risk,
                item_run,
                locked_run.environment,
                risk.inspection_item,
            )
            if matching_finding is not None:
                # Invalid/resolved evidence is not proof of recovery.
                continue

            observed_at = item_run.finished_at
            _observation, created = record_observation(
                risk=risk,
                inspection_run=locked_run,
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
                inspection_run=locked_run,
            )
            recovered.append(risk)

        _update_run_risk_count(locked_run)
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
