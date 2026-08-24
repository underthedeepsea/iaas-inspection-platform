"""Public feedback endpoints backed by the feedback domain service."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from django.db import transaction
from django.http import JsonResponse

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_bool, parse_json_object
from apps.api.pagination import paginate
from apps.audits.services import record_event
from apps.core.models import Environment
from apps.investigations.models import (
    Conversation,
    ConversationMessage,
    HumanFeedback,
    Investigation,
)
from apps.learning.models import Experience
from apps.risks.models import Risk
from apps.experiences.services import ExperienceError

from . import services


_ALLOWED_CREATE_FIELDS = {
    "environment_id",
    "risk_id",
    "investigation_id",
    "conversation_id",
    "message_id",
    "feedback_type",
    "rating",
    "comment",
    "confirmed_conclusion",
    "correction",
    "create_experience",
}


def collection(request):
    if request.method == "GET":
        return _list(request)
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "feedback only accepts GET or POST", 405)
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    try:
        payload = parse_json_object(request)
        _reject_unknown(payload, _ALLOWED_CREATE_FIELDS)
        context = _context(request.user, payload)
        values = _create_values(payload)
        feedback = services.create_feedback(
            actor=request.user,
            **context,
            **values,
        )
    except APIRequestError as error:
        return _error(error.code, error.message, _request_error_status(error), error.details)
    except (services.FeedbackError, ExperienceError, ValueError) as error:
        return _error("VALIDATION_ERROR", str(error), 400)
    experience = _experience_for(feedback)
    return JsonResponse(
        {
            "feedback_id": str(feedback.pk),
            "experience_created": experience is not None,
            "experience_id": str(experience.pk) if experience is not None else None,
        },
        status=201,
    )


def convert(request, feedback_id):
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _error("METHOD_NOT_ALLOWED", "conversion only accepts POST", 405)
    try:
        payload = parse_json_object(request)
        if payload:
            raise APIRequestError(
                "VALIDATION_ERROR", "feedback conversion does not accept a request body"
            )
        parsed = _uuid(feedback_id)
        if parsed is None:
            raise APIRequestError("VALIDATION_ERROR", "feedback_id must be a UUID")
        with transaction.atomic():
            feedback = HumanFeedback.objects.select_for_update().get(pk=parsed)
            if feedback.user_id != request.user.pk and not _is_platform_admin(request.user):
                return _not_found("feedback does not exist")
            if feedback.feedback_type != HumanFeedback.FeedbackType.CONFIRMED_ROOT_CAUSE:
                return _error(
                    "VALIDATION_ERROR",
                    "only confirmed root-cause feedback can create an experience",
                    400,
                )
            if not feedback.create_experience:
                feedback.create_experience = True
                feedback.save(update_fields=["create_experience"])
                record_event(
                    actor=request.user,
                    environment=feedback.environment,
                    event_type="feedback.converted",
                    object_type="HumanFeedback",
                    object_id=feedback.pk,
                    payload={
                        "feedback_type": feedback.feedback_type,
                        "create_experience": True,
                    },
                )
            from apps.experiences.services import create_experience_from_feedback

            experience = create_experience_from_feedback(feedback, actor=request.user)
    except HumanFeedback.DoesNotExist:
        return _not_found("feedback does not exist")
    except APIRequestError as error:
        return _error(error.code, error.message, 400, error.details)
    except (services.FeedbackError, ExperienceError, ValueError) as error:
        return _error("VALIDATION_ERROR", str(error), 400)
    return JsonResponse(
        {
            "feedback_id": str(feedback.pk),
            "experience_created": True,
            "experience_id": str(experience.pk),
        },
        status=201,
    )


def _list(request):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    queryset = HumanFeedback.objects.select_related(
        "risk", "investigation", "conversation", "message"
    ).order_by("-created_at", "-pk")
    for key, field in (
        ("risk_id", "risk_id"),
        ("investigation_id", "investigation_id"),
        ("conversation_id", "conversation_id"),
    ):
        value = request.GET.get(key)
        if value:
            parsed = _uuid(value)
            if parsed is None:
                return _error("VALIDATION_ERROR", f"{key} must be a UUID", 400)
            queryset = queryset.filter(**{field: parsed})
    feedback_type = request.GET.get("feedback_type")
    if feedback_type:
        feedback_type = feedback_type.strip().upper()
        if feedback_type not in HumanFeedback.FeedbackType.values:
            return _error("VALIDATION_ERROR", "invalid feedback_type", 400)
        queryset = queryset.filter(feedback_type=feedback_type)
    return paginate(queryset, request, _serialize_feedback)


def _context(user, payload):
    values = {
        "environment": _lookup(Environment, payload.get("environment_id"), "environment_id"),
        "risk": _lookup(Risk, payload.get("risk_id"), "risk_id"),
        "investigation": _lookup(
            Investigation, payload.get("investigation_id"), "investigation_id"
        ),
        "conversation": _lookup(
            Conversation, payload.get("conversation_id"), "conversation_id"
        ),
        "message": _lookup(
            ConversationMessage, payload.get("message_id"), "message_id"
        ),
    }
    conversation = values["conversation"]
    if conversation is not None and conversation.user_id != user.pk and not _is_platform_admin(user):
        raise services.FeedbackError("conversation does not belong to the authenticated user")
    message = values["message"]
    if message is not None and message.conversation.user_id != user.pk and not _is_platform_admin(user):
        raise services.FeedbackError("message does not belong to the authenticated user")
    return values


def _create_values(payload):
    feedback_type = payload.get("feedback_type")
    if not isinstance(feedback_type, str) or feedback_type.strip().upper() not in HumanFeedback.FeedbackType.values:
        raise APIRequestError("VALIDATION_ERROR", "invalid feedback_type")
    rating = payload.get("rating")
    if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
        raise APIRequestError("VALIDATION_ERROR", "rating must be an integer from 1 to 5")
    comment = payload.get("comment", "")
    confirmed_conclusion = payload.get("confirmed_conclusion", "")
    if not isinstance(comment, str) or len(comment) > 4000:
        raise APIRequestError("VALIDATION_ERROR", "comment must be a string of at most 4000 characters")
    if not isinstance(confirmed_conclusion, str) or len(confirmed_conclusion) > 4000:
        raise APIRequestError(
            "VALIDATION_ERROR",
            "confirmed_conclusion must be a string of at most 4000 characters",
        )
    correction = payload.get("correction", {})
    if not isinstance(correction, Mapping):
        raise APIRequestError("VALIDATION_ERROR", "correction must be an object")
    if len(json.dumps(correction, ensure_ascii=True).encode()) > 8192:
        raise APIRequestError("VALIDATION_ERROR", "correction is too large")
    create_experience = payload.get("create_experience", False)
    parse_bool(create_experience)
    return {
        "feedback_type": feedback_type.strip().upper(),
        "rating": rating,
        "comment": comment,
        "confirmed_conclusion": confirmed_conclusion,
        "correction": dict(correction),
        "create_experience": create_experience,
    }


def _lookup(model, value, label):
    if value is None or value == "":
        return None
    parsed = _uuid(value)
    if parsed is None:
        raise APIRequestError("VALIDATION_ERROR", f"{label} must be a UUID")
    try:
        return model.objects.get(pk=parsed)
    except model.DoesNotExist:
        raise APIRequestError("NOT_FOUND", f"{label} does not exist") from None


def _experience_for(feedback):
    return Experience.objects.filter(experience_key=f"feedback:{feedback.pk}").first()


def _serialize_feedback(feedback):
    return {
        "feedback_id": str(feedback.pk),
        "risk_id": str(feedback.risk_id) if feedback.risk_id else None,
        "investigation_id": str(feedback.investigation_id) if feedback.investigation_id else None,
        "conversation_id": str(feedback.conversation_id) if feedback.conversation_id else None,
        "message_id": str(feedback.message_id) if feedback.message_id else None,
        "feedback_type": feedback.feedback_type,
        "rating": feedback.rating,
        "comment": _safe_text(feedback.comment, 4000),
        "confirmed_conclusion": _safe_text(feedback.confirmed_conclusion, 4000),
        "create_experience": feedback.create_experience,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def _safe_text(value, limit):
    if not isinstance(value, str):
        return ""
    return value[:limit]


def _reject_unknown(payload, allowed):
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise APIRequestError(
            "VALIDATION_ERROR",
            "request contains unsupported fields",
            details={"fields": unknown},
        )


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _not_found(message):
    return _error("NOT_FOUND", message, 404)


def _error(code, message, status, details=None):
    return api_error(code, message, status=status, details=details)


def _request_error_status(error):
    return 404 if error.code == "NOT_FOUND" else 400


def _is_platform_admin(user):
    if getattr(user, "is_superuser", False):
        return True
    groups = getattr(user, "groups", None)
    if groups is None:
        return False
    names = groups.values_list("name", flat=True) if hasattr(groups, "values_list") else groups
    return "platform_admin" in names


__all__ = ["collection", "convert"]
