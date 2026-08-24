"""Ollama HTTP model provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .base import (
    LLMUnavailableError,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    StructuredOutputInvalidError,
    coerce_request,
    configured_model,
    configured_timeout,
    configured_value,
    extract_ollama_content,
    normalize_base_url,
    parse_action,
    usage_from_payload,
)


class OllamaProvider(ModelGateway):
    """Call Ollama's application-level JSON chat protocol.

    The endpoint and model are resolved once from configuration.  Request
    fields with similarly named compatibility attributes are deliberately
    ignored, preventing per-request routing changes.
    """

    provider_name = "ollama"

    def __init__(self, *, http_client: Any = None, client: Any = None):
        self._http = http_client or client or httpx
        self.base_url = normalize_base_url(configured_value("OLLAMA_BASE_URL"))
        self.model = configured_model("OLLAMA_MODEL")
        self.timeout = configured_timeout()

    def invoke(self, request: ModelRequest) -> ModelResponse:
        request = coerce_request(request)
        payload = {
            "model": self.model,
            "stream": False,
            "messages": request.as_messages(),
            "format": "json",
        }
        response = self._send("post", f"{self.base_url}/api/chat", json=payload)
        body = self._response_json(response)
        content = extract_ollama_content(body)
        action = parse_action(content)
        usage, token_source = usage_from_payload(body, provider=self.provider_name)
        return ModelResponse(
            action=action,
            model=str(body.get("model") or self.model),
            provider=self.provider_name,
            usage=usage,
            metadata={"token_source": token_source},
        )

    def health_check(self) -> bool:
        self._send("get", f"{self.base_url}/api/tags")
        return True

    # Alias kept for callers that use the noun form from health APIs.
    check_health = health_check

    def _send(self, method: str, url: str, **kwargs: Any):
        try:
            response = getattr(self._http, method)(url, timeout=self.timeout, **kwargs)
            self._raise_for_status(response)
            return response
        except LLMUnavailableError:
            raise
        except (
            httpx.HTTPError,
            httpx.InvalidURL,
            OSError,
            TimeoutError,
        ):
            # Keep provider URLs, credentials, and network diagnostics out of
            # the stable error exposed to API clients and Agent State.
            raise LLMUnavailableError() from None

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        raise_for_status = getattr(response, "raise_for_status", None)
        if raise_for_status is None:
            return
        try:
            raise_for_status()
        except (
            httpx.HTTPError,
            httpx.InvalidURL,
            OSError,
            TimeoutError,
        ):
            raise LLMUnavailableError() from None

    @staticmethod
    def _response_json(response: Any) -> Mapping[str, Any]:
        try:
            body = response.json()
        except (TypeError, ValueError):
            raise StructuredOutputInvalidError(
                "structured model output is invalid: provider response is not JSON"
            ) from None
        if not isinstance(body, Mapping):
            raise StructuredOutputInvalidError(
                "structured model output is invalid: provider response must be an object"
            )
        return body
