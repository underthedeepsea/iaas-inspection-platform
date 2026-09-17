"""Bounded JSON serializers for capability registry responses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import islice


def serialize_version(version):
    if version is None:
        return None
    return {
        "id": str(version.pk),
        "capability_version_id": str(version.pk),
        "capability_id": version.capability.capability_id,
        "version": version.version,
        "implementation_type": version.implementation_type,
        "status": version.status,
        "semantic_tags": list(version.semantic_tags or [])[:100],
        "subjects": list(version.subjects or [])[:100],
        "resolves": list(version.resolves or [])[:100],
        "input_schema": _schema(version.input_schema),
        "output_schema": _schema(version.output_schema),
        "timeout_seconds": version.timeout_seconds,
        "retry_count": version.retry_count,
        "health_status": version.health_status,
        "activated_at": version.activated_at.isoformat() if version.activated_at else None,
        "retired_at": version.retired_at.isoformat() if version.retired_at else None,
    }


def serialize_capability(capability, *, versions: Iterable | None = None, bindings=None):
    current = getattr(capability, "current_version", None)
    result = {
        "id": str(capability.pk),
        "capability_id": capability.capability_id,
        "name": capability.name,
        "description": capability.description,
        "domain": capability.domain,
        "status": capability.status,
        "owner": capability.owner,
        "read_only": bool(capability.read_only),
        "current_version": serialize_version(current),
    }
    if versions is not None:
        result["versions"] = [serialize_version(value) for value in islice(versions, 100)]
    if bindings is not None:
        result["bindings"] = [serialize_binding(value) for value in islice(bindings, 64)]
    return result


def serialize_binding(binding):
    item = getattr(binding, "inspection_item", None)
    return {
        "id": str(binding.pk),
        "inspection_item_id": str(binding.inspection_item_id),
        "inspection_item_code": getattr(item, "code", None),
        "inspection_item_name": getattr(item, "name", None),
        "role": binding.role,
        "claim": binding.claim,
        "priority": binding.priority,
        "required": bool(binding.required),
        "enabled": bool(binding.enabled),
    }


def serialize_candidate(version):
    return {
        "capability_id": version.capability.capability_id,
        "capability_version_id": str(version.pk),
        "version": version.version,
        "implementation_type": version.implementation_type,
        "status": version.status,
        "read_only": bool(version.capability.read_only),
        "semantic_tags": list(version.semantic_tags or [])[:100],
        "subjects": list(version.subjects or [])[:100],
        "resolves": list(version.resolves or [])[:100],
    }


def _schema(value):
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "serialize_binding",
    "serialize_candidate",
    "serialize_capability",
    "serialize_version",
]
