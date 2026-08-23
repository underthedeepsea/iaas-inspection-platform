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


def _valid_item_runs(inspection_run, *, allow_nonterminal=False, as_of=None):
    if allow_nonterminal:
        if inspection_run.status not in {
            InspectionRun.Status.PENDING,
            InspectionRun.Status.RUNNING,
            InspectionRun.Status.SUCCEEDED,
            InspectionRun.Status.PARTIAL,
            InspectionRun.Status.FAILED,
        }:
            return {}
        boundary = as_of or inspection_run.finished_at or timezone.now()
        if timezone.is_naive(boundary):
            raise ValueError("reverification as_of must be timezone-aware")
    elif (
        inspection_run.status != InspectionRun.Status.SUCCEEDED
        or inspection_run.finished_at is None
    ):
        return {}
    else:
        boundary = inspection_run.finished_at
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
        and item_run.finished_at <= boundary
        and (item_run.summary or {}).get("data_valid") is True
    }


def _has_post_handle_completion(risk, inspection_run, item_run, *, as_of=None):
    pending_history = RiskStatusHistory.objects.filter(
        risk=risk,
        to_status=Risk.Status.PENDING_REVERIFY,
    ).order_by("-created_at").first()
    boundary = inspection_run.finished_at or as_of
    return bool(
        pending_history
        and boundary
        and item_run.finished_at
        and item_run.finished_at <= boundary
        and (as_of is None or item_run.finished_at <= as_of)
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


def reverify_pending_risks(inspection_run, *, allow_nonterminal=False, as_of=None):
    """Reverify pending risks using a later, successful, valid item run.

    Active Findings from an eligible item run are correlated first.  A pending
    risk is recovered only when its same InspectionItem completed validly and
    emitted no matching Finding at all.
    """

    if allow_nonterminal:
        as_of = as_of or timezone.now()
        if timezone.is_naive(as_of):
            raise ValueError("reverification as_of must be timezone-aware")
    recovered = []
    with transaction.atomic():
        locked_run = (
            InspectionRun.objects.select_for_update()
            .select_related("environment")
            .get(pk=inspection_run.pk)
        )
        item_runs = _valid_item_runs(
            locked_run,
            allow_nonterminal=allow_nonterminal,
            as_of=as_of,
        )
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
        pending_reverify_cutoffs = {}
        pending_risks = Risk.objects.filter(pk__in=pending_risk_ids).only(
            "environment_id",
            "fingerprint",
        )
        for risk in pending_risks:
            pending_history = RiskStatusHistory.objects.filter(
                risk_id=risk.pk,
                to_status=Risk.Status.PENDING_REVERIFY,
            ).order_by("-created_at", "-pk").first()
            if pending_history is not None:
                pending_reverify_cutoffs[
                    (risk.environment_id, risk.fingerprint)
                ] = pending_history.created_at

        # Active Findings are correlated only when their item run completed
        # after the latest pending-handling history for the matching risk.
        # This also handles a failed reverification: a valid, later active
        # Finding moves PENDING_REVERIFY to PERSISTING/WORSENED before missing
        # findings are evaluated below.
        _correlate_run_in_transaction(
            locked_run,
            inspection_item_ids=item_runs.keys(),
            pending_reverify_cutoffs=pending_reverify_cutoffs,
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
                as_of=as_of if allow_nonterminal else None,
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
