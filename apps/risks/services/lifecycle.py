"""Small, transactional primitives shared by risk correlation and reverification."""

from django.db import transaction
from django.utils import timezone

from apps.risks.models import Risk, RiskObservation, RiskStatusHistory


SEVERITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}

ACTIVE_RISK_STATUSES = frozenset(
    {
        Risk.Status.NEW,
        Risk.Status.PERSISTING,
        Risk.Status.WORSENED,
        Risk.Status.INVESTIGATING,
        Risk.Status.LOCATED,
        Risk.Status.PENDING_ACTION,
        Risk.Status.IN_PROGRESS,
    }
)
EXPLICIT_LIFECYCLE_STATUSES = frozenset(
    {
        Risk.Status.INVESTIGATING,
        Risk.Status.LOCATED,
        Risk.Status.PENDING_ACTION,
        Risk.Status.IN_PROGRESS,
    }
)
TERMINAL_RISK_STATUSES = frozenset(
    {
        Risk.Status.RECOVERED,
        Risk.Status.IGNORED,
        Risk.Status.FALSE_POSITIVE,
    }
)


def severity_rank(severity):
    """Return the numeric rank for a known finding severity."""

    try:
        return SEVERITY_RANK[severity]
    except (KeyError, TypeError):
        raise ValueError(f"unknown severity: {severity!r}") from None


def observation_status(risk, observed_severity):
    """Choose the status for an active observation on an existing risk."""

    if severity_rank(observed_severity) < severity_rank(risk.severity):
        return Risk.Status.WORSENED
    if risk.status in EXPLICIT_LIFECYCLE_STATUSES:
        return risk.status
    return Risk.Status.PERSISTING


def record_observation(
    *,
    risk,
    inspection_run,
    inspection_item_run,
    observed_at,
    detected,
    severity,
    status_after,
    finding_count=0,
    evidence_count=0,
    snapshot=None,
):
    """Persist one idempotent observation and report whether it was new."""

    observation, created = RiskObservation.objects.get_or_create(
        risk=risk,
        inspection_run=inspection_run,
        defaults={
            "inspection_item_run": inspection_item_run,
            "observed_at": observed_at,
            "detected": detected,
            "severity": severity,
            "status_after": status_after,
            "finding_count": finding_count,
            "evidence_count": evidence_count,
            "snapshot": snapshot or {},
        },
    )
    if not created:
        changed = []
        values = {
            "inspection_item_run": inspection_item_run,
            "observed_at": observed_at,
            "detected": detected,
            "severity": severity,
            "status_after": status_after,
            "finding_count": finding_count,
            "evidence_count": evidence_count,
            "snapshot": snapshot or {},
        }
        for field, value in values.items():
            if getattr(observation, field) != value:
                setattr(observation, field, value)
                changed.append(field)
        if changed:
            observation.save(update_fields=changed)
    return observation, created


def _locked_risk(risk):
    return Risk.objects.select_for_update().get(pk=risk.pk)


def _apply_transition(
    risk,
    to_status,
    *,
    reason,
    source,
    inspection_run=None,
    actor_user=None,
):
    from_status = risk.status
    risk.status = to_status
    if to_status == Risk.Status.RECOVERED:
        risk.recovered_at = timezone.now()
    else:
        risk.recovered_at = None
    risk.save(update_fields=["status", "recovered_at", "updated_at"])
    RiskStatusHistory.objects.create(
        risk=risk,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        source=source,
        actor_user=actor_user,
        inspection_run=inspection_run,
    )
    return risk


def transition_risk(
    risk,
    to_status,
    *,
    reason,
    source=RiskStatusHistory.Source.SYSTEM,
    inspection_run=None,
    actor_user=None,
):
    """Lock a risk, apply a lifecycle status, and write its history."""

    if to_status == Risk.Status.RECOVERED:
        raise ValueError("only verified reverification may transition a risk to RECOVERED")
    with transaction.atomic():
        return _apply_transition(
            _locked_risk(risk),
            to_status,
            reason=reason,
            source=source,
            inspection_run=inspection_run,
            actor_user=actor_user,
        )


def mark_handled(
    risk,
    *,
    actor_user=None,
    actor=None,
    reason="Risk marked handled; awaiting reverification",
    inspection_run=None,
):
    """Move an active risk to PENDING_REVERIFY, never directly to RECOVERED."""

    actor_user = actor_user or actor
    with transaction.atomic():
        locked = _locked_risk(risk)
        if locked.status not in ACTIVE_RISK_STATUSES:
            raise ValueError("only an active risk can be marked handled")
        return _apply_transition(
            locked,
            Risk.Status.PENDING_REVERIFY,
            reason=reason,
            source=RiskStatusHistory.Source.HUMAN,
            inspection_run=inspection_run,
            actor_user=actor_user,
        )


__all__ = [
    "ACTIVE_RISK_STATUSES",
    "EXPLICIT_LIFECYCLE_STATUSES",
    "SEVERITY_RANK",
    "TERMINAL_RISK_STATUSES",
    "mark_handled",
    "observation_status",
    "record_observation",
    "severity_rank",
    "transition_risk",
]
