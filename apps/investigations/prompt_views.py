"""Fixed-key prompt read and protected writes."""

import secrets
from urllib.parse import urlparse

from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt

from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.audits.services import record_event
from services.model_gateway.base import configured_value

from .services.prompts import (
    KEY, PromptRevisionConflict, load_explanation_prompt, reset_explanation_prompt,
    serialize_prompt, update_explanation_prompt,
)


def _response(record):
    data = serialize_prompt(record)
    data["model"] = str(configured_value("OLLAMA_MODEL", "未配置"))
    data["provider"] = str(configured_value("LLM_PROVIDER", "ollama"))
    return JsonResponse(data)


def _authorized(request):
    configured = configured_value("PROMPT_ADMIN_TOKEN")
    supplied = request.headers.get("X-Prompt-Admin-Token", "")
    return bool(configured and supplied) and secrets.compare_digest(str(configured), supplied)


def _same_origin(request):
    origin = request.headers.get("Origin")
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme == ("https" if request.is_secure() else "http") and parsed.netloc == request.get_host()


def _revision(payload):
    value = payload.get("expected_revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected_revision must be a positive integer")
    return value


@csrf_exempt
def explanation_prompt(request, key):
    if key != KEY:
        return api_error("NOT_FOUND", "prompt does not exist", status=404)
    if request.method == "GET":
        return _response(load_explanation_prompt())
    if request.method != "PATCH":
        return api_error("METHOD_NOT_ALLOWED", "method is not supported", status=405)
    return _write(request, reset=False)


@csrf_exempt
def reset_prompt(request, key):
    if key != KEY:
        return api_error("NOT_FOUND", "prompt does not exist", status=404)
    if request.method != "POST":
        return api_error("METHOD_NOT_ALLOWED", "method is not supported", status=405)
    return _write(request, reset=True)


@transaction.atomic
def _write(request, *, reset):
    # Authenticate before parsing the body, so anonymous requests cannot probe validation.
    if not _authorized(request):
        return api_error("PROMPT_ADMIN_REQUIRED", "prompt administrator credential required", status=403)
    if not _same_origin(request):
        return api_error("ORIGIN_NOT_ALLOWED", "origin is not allowed", status=403)
    try:
        payload = parse_json_object(request)
        allowed = {"expected_revision"} if reset else {"expected_revision", "body"}
        if set(payload) != allowed:
            raise ValueError("request fields are invalid")
        expected_revision = _revision(payload)
        record, before = (
            reset_explanation_prompt(expected_revision=expected_revision) if reset else
            update_explanation_prompt(body=payload["body"], expected_revision=expected_revision)
        )
    except APIRequestError as error:
        return api_error(error.code, error.message, status=400)
    except PromptRevisionConflict:
        return api_error("PROMPT_REVISION_CONFLICT", "prompt changed; reload before editing", status=409)
    except ValueError as error:
        return api_error("VALIDATION_ERROR", str(error), status=400)
    trace_id = f"tr_{secrets.token_hex(16)}"
    record_event(
        environment=None, event_type="prompt.reset" if reset else "prompt.updated",
        object_type="ExplanationPrompt", object_id=KEY, trace_id=trace_id,
        payload={
            "prompt_key": KEY, "before_revision": before["revision"],
            "after_revision": record.revision, "before_body": before["body"],
            "after_body": record.body, "before_hash": before["hash"],
            "after_hash": serialize_prompt(record)["hash"],
            "credential_identity": "prompt-admin-token", "guard_version": "1",
        },
    )
    return _response(record)
