import re
from urllib.parse import urlparse

import httpx
from django.conf import settings


class RestExecutionError(RuntimeError):
    pass


_DEFAULT_PORTS = {"http": 80, "https": 443}
_PATH_ESCAPE = re.compile(r"%(?:25|2e|2f|5c)", re.IGNORECASE)


class RestExecutor:
    def __init__(self, allowed_prefixes=None):
        if allowed_prefixes is None:
            allowed_prefixes = getattr(
                settings,
                "PLUGIN_REST_ALLOWED_PREFIXES",
                ("http://127.0.0.1", "http://localhost", "http://internal/"),
            )
        if isinstance(allowed_prefixes, str):
            allowed_prefixes = (allowed_prefixes,)
        self.allowed_prefixes = tuple(allowed_prefixes)

    def execute(self, capability_version, payload):
        endpoint = capability_version.endpoint or ""
        if not any(self._is_allowed(endpoint, prefix) for prefix in self.allowed_prefixes):
            raise RestExecutionError("REST endpoint is outside the allowed internal prefixes")
        try:
            response = httpx.post(endpoint, json=payload, timeout=capability_version.timeout_seconds)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise RestExecutionError("REST plugin request failed") from exc
        except ValueError as exc:
            raise RestExecutionError("REST plugin response must be JSON") from exc

    @staticmethod
    def _is_allowed(endpoint, prefix):
        try:
            target, allowed = urlparse(endpoint), urlparse(prefix)
            target_host, allowed_host = target.hostname, allowed.hostname
            target_port = target.port
            allowed_port = allowed.port
        except (TypeError, ValueError):
            return False
        if not target_host or not allowed_host:
            return False
        if target.scheme not in _DEFAULT_PORTS or allowed.scheme not in _DEFAULT_PORTS:
            return False
        if (
            target.username is not None
            or target.password is not None
            or allowed.username is not None
            or allowed.password is not None
        ):
            return False
        target_port = target_port if target_port is not None else _DEFAULT_PORTS[target.scheme]
        allowed_port = allowed_port if allowed_port is not None else _DEFAULT_PORTS[allowed.scheme]
        if (target.scheme, target_host, target_port) != (allowed.scheme, allowed_host, allowed_port):
            return False
        if RestExecutor._has_path_escape(target.path) or RestExecutor._has_path_escape(allowed.path):
            return False
        allowed_path = allowed.path.rstrip("/")
        return not allowed_path or target.path == allowed_path or target.path.startswith(allowed_path + "/")

    @staticmethod
    def _has_path_escape(path):
        if "\\" in path or _PATH_ESCAPE.search(path):
            return True
        return any(segment in {".", ".."} for segment in path.split("/"))
