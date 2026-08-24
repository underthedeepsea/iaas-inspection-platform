"""Small, dependency-free HTTP boundary primitives for the public API."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from typing import Any

from django.http import JsonResponse


class APIRequestError(ValueError):
    """A safe, client-facing request validation failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.status = 400


_INTEGER_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def api_error(code: str, message: str, *, status: int, details: Any = None) -> JsonResponse:
    """Return the stable error envelope used by every public API slice."""

    return JsonResponse(
        {
            "error": {
                "code": str(code),
                "message": str(message),
                "details": dict(details) if isinstance(details, Mapping) else {},
                "trace_id": f"tr_{secrets.token_hex(16)}",
            }
        },
        status=status,
    )


def parse_json_object(request) -> dict[str, Any]:
    """Decode a request body and reject every JSON value except an object."""

    raw = request.body
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        value = json.loads(text, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        raise APIRequestError(
            "VALIDATION_ERROR",
            "request body must be valid JSON",
        ) from None
    if not isinstance(value, dict):
        raise APIRequestError(
            "VALIDATION_ERROR",
            "request body must be a JSON object",
        )
    return value


def _reject_json_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def parse_bool(value: Any) -> bool:
    """Accept JSON booleans only; string and numeric look-alikes are invalid."""

    if not isinstance(value, bool):
        raise APIRequestError("VALIDATION_ERROR", "value must be a boolean")
    return value


def parse_positive_int(
    value: Any,
    *,
    default: int = 1,
    maximum: int | None = None,
    minimum: int = 1,
) -> int:
    """Parse a canonical positive integer, optionally bounded above."""

    if value is None:
        value = default
    if isinstance(value, bool):
        raise APIRequestError("VALIDATION_ERROR", "value must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and _INTEGER_RE.fullmatch(value):
        parsed = int(value)
    else:
        raise APIRequestError("VALIDATION_ERROR", "value must be a positive integer")
    if parsed < minimum or maximum is not None and parsed > maximum:
        raise APIRequestError("VALIDATION_ERROR", "value is outside the allowed range")
    return parsed


__all__ = [
    "APIRequestError",
    "api_error",
    "parse_bool",
    "parse_json_object",
    "parse_positive_int",
]
