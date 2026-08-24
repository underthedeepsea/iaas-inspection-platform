"""Public Experience and codeization task API projections."""

from __future__ import annotations

import uuid
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.api.pagination import paginate
from apps.audits.services import record_event
from apps.inspections.models import InspectionItem
from apps.investigations.models import HumanFeedback
from apps.learning.models import CodeizationTask, Experience, ExperienceEvidence

from . import codeization
from . import services


_CONFIRM_FIELDS = {"human_summary", "target_claim"}
_TASK_CREATE_FIELDS = {
    "inspection_item_id",
    "target_capability_id",
    "task_type",
    "implementation_type",
    "target_claim",
    "title",
    "specification",
    "owner",
}
_TASK_PATCH_FIELDS = {
    "owner",
    "status",
    "shadow_cases",
    "precision",
    "critical_false_positive",
    "capability_version_id",
    "version",
}
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[\W_]*key|access[\W_]*key|token|secret|password|passwd|credential|authorization|cookie|private[\W_]*key|raw|provider|model|endpoint|url|uri|payload)"
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:[A-Za-z][A-Za-z0-9+.-]*://|\b(?:api[_ -]?key|password|passwd|token|secret|authorization)\s*=|bearer\s+)"
)


def collection(request):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "experiences only accepts GET", 405)
    queryset = Experience.objects.select_related(
        "source_risk", "source_investigation"
    ).order_by("-created_at", "-pk")
    for key in ("status", "code_status"):
        value = request.GET.get(key)
        if value:
            value = value.strip().upper()
            enum = Experience.Status if key == "status" else Experience.CodeStatus
            if value not in enum.values:
                return _error("VALIDATION_ERROR", f"invalid {key}", 400)
            queryset = queryset.filter(**{key: value})
    for key in ("domain", "target_claim"):
        value = request.GET.get(key)
        if value:
            if not isinstance(value, str) or len(value) > 192:
                return _error("VALIDATION_ERROR", f"invalid {key}", 400)
            if key == "target_claim":
                try:
                    value = services.canonical_claim(value)
                except services.ExperienceError as error:
                    return _error("VALIDATION_ERROR", str(error), 400)
            queryset = queryset.filter(**{key: value.strip().lower() if key == "target_claim" else value.strip()})
    return paginate(queryset, request, _serialize_experience)


def detail(request, experience_id):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "experience only accepts GET", 405)
    experience = _get(Experience, experience_id)
    if experience is None:
        return _not_found("experience does not exist")
    return JsonResponse(_serialize_experience_detail(experience))


def confirm(request, experience_id):
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "confirm only accepts POST", 405)
    experience = _get(Experience, experience_id)
    if experience is None:
        return _not_found("experience does not exist")
    try:
        payload = parse_json_object(request)
        _reject_unknown(payload, _CONFIRM_FIELDS)
        human_summary = payload.get("human_summary")
        target_claim = payload.get("target_claim")
        if not isinstance(human_summary, str) or not human_summary.strip() or len(human_summary.strip()) > 4000:
            raise APIRequestError("VALIDATION_ERROR", "human_summary must be non-empty and at most 4000 characters")
        if not isinstance(target_claim, str) or len(target_claim.strip()) > 192:
            raise APIRequestError("VALIDATION_ERROR", "target_claim is required")
        result = services.confirm_experience(
            request.user,
            experience,
            human_summary=human_summary,
            target_claim=target_claim,
        )
    except APIRequestError as error:
        return _error(error.code, error.message, 400, error.details)
    except (services.ExperienceError, ValueError) as error:
        return _error("VALIDATION_ERROR", str(error), 400)
    return JsonResponse(_serialize_experience(result))


def create_task(request, experience_id):
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "codeization task creation only accepts POST", 405)
    experience = _get(Experience, experience_id)
    if experience is None:
        return _not_found("experience does not exist")
    try:
        payload = parse_json_object(request)
        _reject_unknown(payload, _TASK_CREATE_FIELDS)
        required = ("inspection_item_id", "target_capability_id", "task_type", "implementation_type")
        if any(field not in payload for field in required):
            raise APIRequestError("VALIDATION_ERROR", "inspection_item_id, target_capability_id, task_type, and implementation_type are required")
        item = _lookup_item(payload["inspection_item_id"])
        task_type = _enum(payload["task_type"], CodeizationTask.TaskType, "task_type")
        implementation_type = _enum(
            payload["implementation_type"],
            CodeizationTask.ImplementationType,
            "implementation_type",
        )
        target_capability_id = payload["target_capability_id"]
        if not isinstance(target_capability_id, str) or not target_capability_id.strip():
            raise APIRequestError("VALIDATION_ERROR", "target_capability_id is required")
        specification = payload.get("specification", {})
        if not isinstance(specification, Mapping):
            raise APIRequestError("VALIDATION_ERROR", "specification must be an object")
        owner = payload.get("owner", "")
        if not isinstance(owner, str) or len(owner) > 128:
            raise APIRequestError("VALIDATION_ERROR", "owner must be a string of at most 128 characters")
        target_claim = payload.get("target_claim")
        if target_claim is not None and not isinstance(target_claim, str):
            raise APIRequestError("VALIDATION_ERROR", "target_claim must be a string")
        task = services.create_codeization_task(
            request.user,
            experience,
            inspection_item=item,
            target_capability_id=target_capability_id.strip(),
            task_type=task_type,
            implementation_type=implementation_type,
            target_claim=target_claim,
            title=payload.get("title"),
            specification=dict(specification),
            owner=owner,
        )
    except APIRequestError as error:
        return _error(error.code, error.message, 404 if error.code == "NOT_FOUND" else 400, error.details)
    except (services.ExperienceError, ValueError) as error:
        return _error("VALIDATION_ERROR", str(error), 400)
    return JsonResponse(_serialize_task(task), status=201)


def task_collection(request):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _error("METHOD_NOT_ALLOWED", "codeization-tasks only accepts GET", 405)
    queryset = CodeizationTask.objects.select_related(
        "experience", "inspection_item", "capability_version__capability"
    ).order_by("-created_at", "-pk")
    status = request.GET.get("status")
    if status:
        status = status.strip().upper()
        if status not in CodeizationTask.Status.values:
            return _error("VALIDATION_ERROR", "invalid status", 400)
        queryset = queryset.filter(status=status)
    for key in ("owner", "target_claim"):
        value = request.GET.get(key)
        if value:
            if len(value) > 192:
                return _error("VALIDATION_ERROR", f"invalid {key}", 400)
            if key == "target_claim":
                try:
                    value = services.canonical_claim(value)
                except services.ExperienceError as error:
                    return _error("VALIDATION_ERROR", str(error), 400)
            queryset = queryset.filter(**{key: value.strip().lower() if key == "target_claim" else value.strip()})
    return paginate(queryset, request, _serialize_task)


def task_detail(request, task_id):
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    if request.method != "PATCH":
        return _error("METHOD_NOT_ALLOWED", "codeization task only accepts PATCH", 405)
    task = _get(CodeizationTask, task_id)
    if task is None:
        return _not_found("codeization task does not exist")
    try:
        payload = parse_json_object(request)
        _reject_unknown(payload, _TASK_PATCH_FIELDS)
        if not payload:
            raise APIRequestError("VALIDATION_ERROR", "at least one task field is required")
        target_status = payload.get("status")
        if target_status is None and (
            "version" in payload or "capability_version_id" in payload
        ):
            raise APIRequestError(
                "VALIDATION_ERROR",
                "capability version identity requires a status transition",
            )
        if target_status is not None:
            role_error = require_role(request, "platform_admin")
            if role_error is not None:
                return role_error
            target_status = _enum(target_status, CodeizationTask.Status, "status")
            if target_status not in {
                CodeizationTask.Status.SHADOW,
                CodeizationTask.Status.CODE_ACTIVE,
            }:
                raise APIRequestError(
                    "VALIDATION_ERROR",
                    "only SHADOW and CODE_ACTIVE are legal public transitions",
                )
        changes = _task_changes(payload)
        with transaction.atomic():
            locked = CodeizationTask.objects.select_for_update().get(pk=task.pk)
            before_status = locked.status
            if changes:
                for field, value in changes.items():
                    setattr(locked, field, value)
                locked.save(update_fields=[*changes, "updated_at"])
            if target_status is not None:
                capability_version = _transition_version(locked, payload)
                if target_status == CodeizationTask.Status.SHADOW:
                    locked = codeization.move_to_shadow(
                        request.user,
                        locked,
                        capability_version=capability_version,
                    )
                else:
                    locked = codeization.activate_codeization_task(
                        request.user,
                        locked,
                        capability_version=capability_version,
                    )
            if changes:
                record_event(
                    actor=request.user,
                    environment=_task_environment(locked),
                    event_type="codeization_task.updated",
                    object_type="CodeizationTask",
                    object_id=locked.pk,
                    payload={
                        "from_status": before_status,
                        "to_status": locked.status,
                        **{
                            key: value
                            for key, value in changes.items()
                            if key in {"shadow_cases", "precision", "critical_false_positive"}
                        },
                    },
                )
        return JsonResponse(_serialize_task(locked))
    except APIRequestError as error:
        return _error(error.code, error.message, 400, error.details)
    except (services.ExperienceError, ValueError, InvalidOperation) as error:
        return _error("VALIDATION_ERROR", str(error), 400)


def _serialize_experience(experience):
    return {
        "experience_id": str(experience.pk),
        "id": str(experience.pk),
        "experience_key": experience.experience_key,
        "title": _text(experience.title, 255),
        "domain": experience.domain,
        "status": experience.status,
        "source_type": experience.source_type,
        "source_risk_id": str(experience.source_risk_id) if experience.source_risk_id else None,
        "source_investigation_id": str(experience.source_investigation_id) if experience.source_investigation_id else None,
        "conclusion": _text(experience.conclusion, 4000),
        "human_summary": _text(experience.human_summary, 4000),
        "support_count": experience.support_count,
        "precision": float(experience.precision) if experience.precision is not None else None,
        "code_status": experience.code_status,
        "target_claim": experience.target_claim,
        "confirmed_at": _iso(experience.confirmed_at),
    }


def _serialize_experience_detail(experience):
    result = _serialize_experience(experience)
    result["hypothesis"] = _text(experience.hypothesis, 4000)
    result["applicable_scope"] = _safe_object(experience.applicable_scope)
    result["trigger_conditions"] = _safe_object(experience.trigger_conditions)
    result["required_evidence"] = _safe_object(experience.required_evidence)
    result["tool_sequence"] = _safe_object(experience.tool_sequence)
    result["source"] = {
        "risk_id": result["source_risk_id"],
        "investigation_id": result["source_investigation_id"],
    }
    result["feedback_id"] = _feedback_id(experience)
    result["evidence"] = [
        {
            "evidence_id": str(row.evidence_id),
            "relation": row.relation,
            "evidence_type": row.evidence.evidence_type,
            "evidence_key": row.evidence.evidence_key,
            "summary": _text(row.evidence.summary, 2000),
            "confidence": float(row.evidence.confidence),
            "materiality": float(row.evidence.materiality),
        }
        for row in ExperienceEvidence.objects.filter(experience=experience)
        .select_related("evidence")
        .order_by("created_at", "pk")[:64]
    ]
    return result


def _serialize_task(task):
    return {
        "task_id": str(task.pk),
        "id": str(task.pk),
        "experience_id": str(task.experience_id),
        "inspection_item_id": str(task.inspection_item_id),
        "target_capability_id": task.target_capability_id,
        "capability_version_id": str(task.capability_version_id) if task.capability_version_id else None,
        "task_type": task.task_type,
        "status": task.status,
        "title": _text(task.title, 255),
        "target_claim": task.target_claim,
        "implementation_type": task.implementation_type,
        "owner": _text(task.owner, 128),
        "historical_support": task.historical_support,
        "precision": float(task.precision) if task.precision is not None else None,
        "shadow_cases": task.shadow_cases,
        "critical_false_positive": task.critical_false_positive,
        "started_at": _iso(task.started_at),
        "completed_at": _iso(task.completed_at),
    }


def _task_changes(payload):
    changes = {}
    if "owner" in payload:
        owner = payload["owner"]
        if not isinstance(owner, str) or len(owner) > 128:
            raise APIRequestError("VALIDATION_ERROR", "owner must be a string of at most 128 characters")
        changes["owner"] = owner.strip()
    for field in ("shadow_cases", "critical_false_positive"):
        if field in payload:
            value = payload[field]
            if type(value) is not int or value < 0:
                raise APIRequestError("VALIDATION_ERROR", f"{field} must be a non-negative integer")
            changes[field] = value
    if "precision" in payload:
        value = payload["precision"]
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise APIRequestError("VALIDATION_ERROR", "precision must be between 0 and 1")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise APIRequestError("VALIDATION_ERROR", "precision must be between 0 and 1") from None
        if decimal_value < 0 or decimal_value > 1:
            raise APIRequestError("VALIDATION_ERROR", "precision must be between 0 and 1")
        changes["precision"] = decimal_value
    return changes


def _transition_version(task, payload):
    supplied = payload.get("capability_version_id")
    if supplied is None:
        supplied = payload.get("version")
    if supplied is None:
        supplied = task.capability_version_id
    if supplied is None:
        raise APIRequestError(
            "VALIDATION_ERROR",
            "capability_version_id or version is required for status progression",
        )
    return supplied


def _task_environment(task):
    experience = task.experience
    if experience.source_risk_id and experience.source_risk is not None:
        return experience.source_risk.environment
    scope = experience.applicable_scope or {}
    from apps.core.models import Environment

    return Environment.objects.filter(pk=scope.get("environment_id")).first()


def _feedback_id(experience):
    prefix = "feedback:"
    if not experience.experience_key.startswith(prefix):
        return None
    value = experience.experience_key[len(prefix) :]
    return value if _get(HumanFeedback, value) is not None else None


def _lookup_item(value):
    parsed = _uuid(value)
    if parsed is None:
        raise APIRequestError("VALIDATION_ERROR", "inspection_item_id must be a UUID")
    try:
        return InspectionItem.objects.get(pk=parsed)
    except InspectionItem.DoesNotExist:
        raise APIRequestError("NOT_FOUND", "inspection item does not exist") from None


def _enum(value, enum, label):
    value = value.value if hasattr(value, "value") else value
    if not isinstance(value, str) or value.strip().upper() not in enum.values:
        raise APIRequestError("VALIDATION_ERROR", f"invalid {label}")
    return value.strip().upper()


def _get(model, value):
    parsed = _uuid(value)
    if parsed is None:
        return None
    try:
        return model.objects.select_related("source_risk").get(pk=parsed) if model is Experience else model.objects.get(pk=parsed)
    except model.DoesNotExist:
        return None


def _reject_unknown(payload, allowed):
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise APIRequestError(
            "VALIDATION_ERROR",
            "request contains unsupported fields",
            details={"fields": unknown},
        )


def _safe_object(value, depth=0):
    if depth > 3:
        return {}
    if isinstance(value, Mapping):
        result = {}
        for key, item in list(value.items())[:64]:
            key = str(key)[:128]
            if _SENSITIVE_KEY_RE.search(key):
                continue
            result[key] = _safe_object(item, depth + 1)
        return result
    if isinstance(value, list):
        return [_safe_object(item, depth + 1) for item in value[:64]]
    if isinstance(value, str):
        return "[redacted]" if _SENSITIVE_TEXT_RE.search(value) else value[:1000]
    return value if isinstance(value, (int, float, bool)) or value is None else None


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else ""


def _iso(value):
    return value.isoformat() if value is not None else None


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _not_found(message):
    return _error("NOT_FOUND", message, 404)


def _error(code, message, status, details=None):
    return api_error(code, message, status=status, details=details)


__all__ = [
    "collection",
    "confirm",
    "create_task",
    "detail",
    "task_collection",
    "task_detail",
]
