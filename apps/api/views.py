"""Anonymous health/product endpoints and shared API fallbacks."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import connection
from django.http import JsonResponse

from .auth import require_session
from .http import APIRequestError, api_error, parse_json_object


_NUMERIC_VERSION = re.compile(r"\A\d+\.\d+\.\d+\Z")


def health(request):
    if request.method != "GET":
        return api_error("METHOD_NOT_ALLOWED", "health only accepts GET", status=405)
    database = _database_health()
    ollama = _external_health("ollama")
    airflow = _external_health("airflow")
    statuses = {database, ollama, airflow}
    return JsonResponse(
        {
            "status": "ok" if statuses <= {"ok", "unknown"} else "degraded",
            "database": database,
            "ollama": ollama,
            "airflow": airflow,
            "version": _project_version(),
        }
    )


def product_info(request):
    if request.method != "GET":
        return api_error("METHOD_NOT_ALLOWED", "product-info only accepts GET", status=405)
    return JsonResponse(
        {
            "product_name": "IaaS 智能巡检",
            "data_mode": str(getattr(settings, "DATA_MODE", os.getenv("DATA_MODE", "MOCK"))),
            "llm_provider": str(
                getattr(settings, "LLM_PROVIDER", os.getenv("LLM_PROVIDER", "ollama"))
            ),
            "security_mode": "READ_ONLY_TOOLS",
            "versions": {
                "django": "4.2.16",
                "airflow": "2.3.2",
                "langgraph": "1.2.10",
                "langchain": "1.3.14",
            },
        }
    )


def auth_login(request):
    if request.method != "POST":
        return api_error("METHOD_NOT_ALLOWED", "login only accepts POST", status=405)
    try:
        payload = parse_json_object(request)
        unknown = sorted(set(payload) - {"username", "password"})
        if unknown:
            raise APIRequestError(
                "VALIDATION_ERROR",
                "request contains unsupported fields",
                details={"fields": unknown},
            )
        username = payload.get("username")
        password = payload.get("password")
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            raise APIRequestError(
                "VALIDATION_ERROR",
                "username and password are required",
                details={"fields": ["username", "password"]},
            )
    except APIRequestError as error:
        return api_error(error.code, error.message, status=400, details=error.details)
    user = authenticate(request, username=username.strip(), password=password)
    if user is None or not user.is_active:
        return api_error("AUTH_INVALID_CREDENTIALS", "username or password is incorrect", status=401)
    login(request, user)
    return JsonResponse(_session_user(user))


def auth_me(request):
    session_error = require_session(request)
    if session_error is not None:
        return session_error
    return JsonResponse(_session_user(request.user))


def auth_logout(request):
    if request.method != "POST":
        return api_error("METHOD_NOT_ALLOWED", "logout only accepts POST", status=405)
    logout(request)
    return JsonResponse({}, status=204)


def _session_user(user):
    return {
        "user_id": str(user.pk),
        "username": user.get_username(),
        "roles": sorted(user.groups.values_list("name", flat=True)),
    }


def authenticated_not_found(request, resource=""):
    """Keep unknown public API paths behind the same session boundary."""

    session_error = require_session(request)
    if session_error is not None:
        return session_error
    return api_error("NOT_FOUND", "the requested resource does not exist", status=404)


def _database_health() -> str:
    override = getattr(settings, "API_HEALTH_DATABASE_CHECK", None)
    try:
        if callable(override):
            return "ok" if bool(override()) else "error"
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return "error"
    return "ok"


def _external_health(name: str) -> str:
    checks = getattr(settings, "API_HEALTH_CHECKS", None)
    check = checks.get(name) if isinstance(checks, Mapping) else None
    if check is None:
        return "unknown"
    try:
        result = check() if callable(check) else check
    except Exception:
        return "error"
    if isinstance(result, bool):
        return "ok" if result else "error"
    return str(result)


def _project_version() -> str:
    configured = getattr(settings, "PROJECT_VERSION", None)
    if configured is None:
        configured = os.getenv("PROJECT_VERSION")
    if configured is None:
        base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
        try:
            configured = (base_dir / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            configured = "0.1.0"
    value = str(configured).strip()
    return value if _NUMERIC_VERSION.fullmatch(value) else "0.1.0"


__all__ = [
    "auth_login",
    "auth_logout",
    "auth_me",
    "authenticated_not_found",
    "health",
    "product_info",
]
