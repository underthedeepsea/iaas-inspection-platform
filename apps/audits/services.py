"""Small audit write boundary shared by domain services."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from apps.audits.models import AuditEvent


_SAFE_PAYLOAD_KEYS = frozenset(
    {
        "feedback_type",
        "create_experience",
        "from_status",
        "to_status",
        "target_claim",
        "target_capability_id",
        "capability_id",
        "capability_version_id",
        "version",
        "implementation_type",
        "task_type",
        "shadow_cases",
        "precision",
        "critical_false_positive",
    }
)


def record_event(*, actor, environment, event_type, object_type, object_id, payload=None):
    """Write a bounded, non-sensitive audit row inside the caller's transaction."""

    if actor is None or not getattr(actor, "pk", None):
        raise ValueError("an explicit actor is required for audit events")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("audit event_type is required")
    if not isinstance(object_type, str) or not object_type.strip():
        raise ValueError("audit object_type is required")
    safe_payload = _safe_payload(payload)
    return AuditEvent.objects.create(
        environment=environment,
        user=actor,
        event_type=event_type.strip()[:64],
        object_type=object_type.strip()[:64],
        object_id=str(object_id),
        payload=safe_payload,
    )


def _safe_payload(payload):
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise ValueError("audit payload must be an object")
    result = {}
    for key, value in payload.items():
        if key not in _SAFE_PAYLOAD_KEYS:
            continue
        if isinstance(value, Decimal):
            value = str(value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


__all__ = ["record_event"]
