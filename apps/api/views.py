"""Anonymous health/product endpoints and shared API fallbacks."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection
from django.http import JsonResponse

from .auth import require_session
from .http import api_error


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


__all__ = ["authenticated_not_found", "health", "product_info"]
