from urllib.parse import urlparse

import httpx
from django.conf import settings


class RestExecutionError(RuntimeError):
    pass


class RestExecutor:
    def __init__(self, allowed_prefixes=None):
        self.allowed_prefixes = allowed_prefixes or getattr(
            settings,
            "PLUGIN_REST_ALLOWED_PREFIXES",
            ("http://127.0.0.1", "http://localhost", "http://internal/"),
        )

    def execute(self, capability_version, payload):
        endpoint = capability_version.endpoint or ""
        if not any(self._is_allowed(endpoint, prefix) for prefix in self.allowed_prefixes):
            raise RestExecutionError("REST endpoint is outside the allowed internal prefixes")
        try:
            response = httpx.post(endpoint, json=payload, timeout=capability_version.timeout_seconds)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise RestExecutionError("REST plugin request failed") from exc
        except ValueError as exc:
            raise RestExecutionError("REST plugin response must be JSON") from exc

    @staticmethod
    def _is_allowed(endpoint, prefix):
        target, allowed = urlparse(endpoint), urlparse(prefix)
        if (target.scheme, target.hostname) != (allowed.scheme, allowed.hostname):
            return False
        if allowed.port is not None and target.port != allowed.port:
            return False
        allowed_path = allowed.path.rstrip("/")
        return not allowed_path or target.path == allowed_path or target.path.startswith(allowed_path + "/")
