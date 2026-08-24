"""Minimal OpenAI-compatible chat-completions provider.

This module intentionally uses the existing ``httpx`` dependency instead of
introducing an SDK.  It implements only the JSON chat contract needed by the
investigation graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .base import (
    LLMUnavailableError,
    ModelGatewayConfigurationError,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    StructuredOutputInvalidError,
    coerce_request,
    configured_model,
    configured_timeout,
    configured_value,
    extract_openai_content,
    normalize_base_url,
    parse_action,
    usage_from_payload,
)


class OpenAICompatibleProvider(ModelGateway):
    """Use an OpenAI-compatible ``/chat/completions`` HTTP endpoint."""

    provider_name = "openai_compatible"

    def __init__(self, *, http_client: Any = None, client: Any = None):
        self._http = http_client or client or httpx
        configured_url = configured_value("OPENAI_COMPATIBLE_BASE_URL")
        if configured_url is None:
            configured_url = configured_value("OPENAI_BASE_URL")
        self.base_url = normalize_base_url(configured_url)
        configured_model_name = configured_value("OPENAI_COMPATIBLE_MODEL")
        if configured_model_name is None:
            configured_model_name = configured_value("OPENAI_MODEL")
        if configured_model_name is None:
            self.model = configured_model("OPENAI_COMPATIBLE_MODEL")
        elif not isinstance(configured_model_name, str) or not configured_model_name.strip():
            raise ModelGatewayConfigurationError("model name configuration is invalid")
        else:
            self.model = configured_model_name.strip()
        self.api_key = str(configured_value("OPENAI_API_KEY", ""))
        self.timeout = configured_timeout()

    def invoke(self, request: ModelRequest) -> ModelResponse:
        request = coerce_request(request)
        payload = {
            "model": self.model,
            "messages": request.as_messages(),
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self._send(
            "post",
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        body = self._response_json(response)
        content = extract_openai_content(body)
        action = parse_action(content)
        usage, token_source = usage_from_payload(body, provider=self.provider_name)
        return ModelResponse(
            action=action,
            model=self.model,
            provider=self.provider_name,
            usage=usage,
            metadata={"token_source": token_source},
        )

    def health_check(self) -> bool:
        self._send("get", f"{self.base_url}/models")
        return True

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
