"""Ollama HTTP model provider."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import json
import time
from typing import Any

import httpx

from .base import (
    LLMUnavailableError,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    ModelStreamProgress,
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

    def _direct_inspection_chat(self, request):
        return (self.base_url == "http://127.0.0.1:11434"
                and request.metadata.get("purpose") in {"dashboard_explanation", "inspection_explanation"})

    @contextmanager
    def _chat_client(self, request):
        # Only this exact authorized inspection destination bypasses environment
        # proxies. Injected clients retain ownership and the existing test contract.
        if self._direct_inspection_chat(request) and self._http is httpx:
            with httpx.Client(trust_env=False, follow_redirects=False) as client:
                yield client
        else:
            yield self._http

    def invoke(self, request: ModelRequest) -> ModelResponse:
        request = coerce_request(request)
        payload = {
            "model": self.model,
            "stream": False,
            "messages": request.as_messages(),
            "format": "json",
        }
        if request.metadata.get("purpose") in {"dashboard_explanation", "inspection_explanation"}:
            payload["think"] = False
            payload["options"] = {"num_predict": 1536}
        redirects = {"follow_redirects": False} if self._direct_inspection_chat(request) else {}
        with self._chat_client(request) as client:
            response = self._send("post", f"{self.base_url}/api/chat", _client=client, json=payload, **redirects)
        body = self._response_json(response)
        content = extract_ollama_content(body).strip()
        # Some Ollama-compatible runtimes wrap JSON despite format="json".
        lines = content.splitlines()
        if len(lines) >= 3 and lines[0] in {"```json", "```"} and lines[-1] == "```":
            content = "\n".join(lines[1:-1])
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
        self._send("get", f"{self.base_url}/api/tags")
        return True

    # Alias kept for callers that use the noun form from health APIs.
    check_health = health_check

    def stream_events(self, request: ModelRequest):
        """Consume actual NDJSON while keeping all model text private.

        A read may block for the configured timeout; the absolute deadline is
        checked at every transport chunk. Closing this generator closes HTTP.
        """
        request = coerce_request(request)
        payload = {"model": self.model, "stream": True,
                   "messages": request.as_messages(), "format": "json"}
        if request.metadata.get("purpose") in {"dashboard_explanation", "inspection_explanation"}:
            payload["think"] = False
            payload["options"] = {"num_predict": 1536}
        timeout = min(self.timeout, 120.0)
        deadline = time.monotonic() + timeout
        pending = b""
        parts = []
        wire_bytes = content_bytes = fragments = 0
        terminal = None
        try:
            redirects = {"follow_redirects": False} if self._direct_inspection_chat(request) else {}
            with self._chat_client(request) as client, client.stream("POST", f"{self.base_url}/api/chat",
                                   json=payload, timeout=timeout, **redirects) as response:
                self._raise_for_status(response)
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise LLMUnavailableError()
                    wire_bytes += len(chunk)
                    if wire_bytes > 256 * 1024:
                        raise StructuredOutputInvalidError()
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        if not line.strip():
                            continue
                        if terminal is not None:
                            raise StructuredOutputInvalidError()
                        body = self._stream_json(line)
                        text = extract_ollama_content(body)
                        content_bytes += len(text.encode("utf-8"))
                        if content_bytes > 64 * 1024:
                            raise StructuredOutputInvalidError()
                        parts.append(text)
                        if text:
                            fragments += 1
                            yield ModelStreamProgress(fragments, content_bytes)
                        if body["done"]:
                            terminal = body
                if time.monotonic() > deadline:
                    raise LLMUnavailableError()
                if pending.strip():
                    if terminal is not None:
                        raise StructuredOutputInvalidError()
                    body = self._stream_json(pending)
                    text = extract_ollama_content(body)
                    content_bytes += len(text.encode("utf-8"))
                    if content_bytes > 64 * 1024:
                        raise StructuredOutputInvalidError()
                    parts.append(text)
                    if text:
                        fragments += 1
                        yield ModelStreamProgress(fragments, content_bytes)
                    if body["done"]:
                        terminal = body
                if terminal is None:
                    raise StructuredOutputInvalidError()
            content = "".join(parts).strip()
            lines = content.splitlines()
            if len(lines) >= 3 and lines[0] in {"```json", "```"} and lines[-1] == "```":
                content = "\n".join(lines[1:-1])
            usage, token_source = usage_from_payload(terminal, provider=self.provider_name)
            yield ModelResponse(action=parse_action(content), model=self.model,
                                provider=self.provider_name, usage=usage,
                                metadata={"token_source": token_source})
        except (httpx.HTTPError, httpx.InvalidURL, OSError, TimeoutError):
            raise LLMUnavailableError() from None

    @staticmethod
    def _stream_json(line):
        try:
            body = json.loads(line)
        except (ValueError, UnicodeError):
            raise StructuredOutputInvalidError() from None
        if not isinstance(body, Mapping) or type(body.get("done")) is not bool or "error" in body:
            raise StructuredOutputInvalidError()
        return body

    def _send(self, method: str, url: str, *, _client=None, **kwargs: Any):
        try:
            response = getattr(_client if _client is not None else self._http, method)(url, timeout=self.timeout, **kwargs)
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
