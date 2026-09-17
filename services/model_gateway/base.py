"""Shared contract and structured-action validation for model providers.

The gateway deliberately keeps provider transport details out of the action
schema.  Providers return one of the two actions defined by the product
protocol, while callers only depend on :class:`ModelGateway`.
"""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse


class ModelGatewayError(RuntimeError):
    """Base class for errors exposed by a model gateway."""

    code = "MODEL_GATEWAY_ERROR"

    def __init__(self, message: str | None = None):
        self.code = type(self).code
        super().__init__(message or self.code)


class LLMUnavailableError(ModelGatewayError):
    """The configured model service cannot be reached or is unhealthy."""

    code = "LLM_UNAVAILABLE"


class StructuredOutputInvalidError(ModelGatewayError):
    """A provider response does not satisfy the structured action protocol."""

    code = "STRUCTURED_OUTPUT_INVALID"


class ModelGatewayConfigurationError(ModelGatewayError):
    """The provider has no usable configuration."""

    code = "MODEL_GATEWAY_CONFIGURATION_INVALID"


@dataclass(frozen=True)
class ModelRequest:
    """Input accepted by every provider.

    ``model`` and ``base_url`` are retained as ignored compatibility fields so
    callers cannot accidentally change provider routing per request.  The
    provider always reads those values from Django/environment configuration.
    """

    messages: Sequence[Mapping[str, Any]]
    model: str | None = None
    base_url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_messages(self) -> list[dict[str, Any]]:
        """Return a JSON-serialisable copy of the message list."""

        return [dict(message) for message in self.messages]


@dataclass(frozen=True, eq=False)
class FinalAction(Mapping[str, Any]):
    """The terminal answer action from the application-level protocol."""

    summary: str
    confidence: float
    action: str = "FINAL"

    @property
    def answer(self) -> dict[str, Any]:
        return {"summary": self.summary, "confidence": self.confidence}

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "answer": self.answer}

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return 2

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        if not isinstance(other, FinalAction):
            return NotImplemented
        return self.to_dict() == other.to_dict()


@dataclass(frozen=True, eq=False)
class CallToolAction(Mapping[str, Any]):
    """A read-only capability invocation action."""

    capability_id: str
    arguments: dict[str, Any]
    reason: str
    action: str = "CALL_TOOL"

    @property
    def tool(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "arguments": dict(self.arguments),
            "reason": self.reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "tool": self.tool}

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return 2

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        if not isinstance(other, CallToolAction):
            return NotImplemented
        return self.to_dict() == other.to_dict()


Action = FinalAction | CallToolAction


def _invalid(reason: str) -> StructuredOutputInvalidError:
    # Do not include provider output in the exception: the output can contain
    # credentials or raw infrastructure data and is not safe for API clients.
    return StructuredOutputInvalidError(f"structured model output is invalid: {reason}")


def parse_action(payload: Any) -> Action:
    """Parse and strictly validate one documented structured action.

    Both a decoded JSON object and a JSON string are accepted because Ollama
    returns the action in ``message.content`` as text.
    """

    if isinstance(payload, (str, bytes, bytearray)):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise _invalid("output is not valid JSON") from None

    if not isinstance(payload, Mapping):
        raise _invalid("top-level output must be an object")

    action = payload.get("action")
    if action == "FINAL":
        if set(payload) != {"action", "answer"} or not isinstance(payload.get("answer"), Mapping):
            raise _invalid("FINAL must contain only an answer object")
        answer = payload["answer"]
        if set(answer) != {"summary", "confidence"}:
            raise _invalid("FINAL answer must contain summary and confidence")
        summary = answer.get("summary")
        confidence = answer.get("confidence")
        if not isinstance(summary, str) or not summary.strip():
            raise _invalid("FINAL summary must be a non-empty string")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise _invalid("FINAL confidence must be a number")
        if not 0 <= float(confidence) <= 1:
            raise _invalid("FINAL confidence must be between 0 and 1")
        return FinalAction(summary=summary, confidence=float(confidence))

    if action == "CALL_TOOL":
        if set(payload) != {"action", "tool"} or not isinstance(payload.get("tool"), Mapping):
            raise _invalid("CALL_TOOL must contain only a tool object")
        tool = payload["tool"]
        if set(tool) != {"capability_id", "arguments", "reason"}:
            raise _invalid("CALL_TOOL tool must contain capability_id, arguments, and reason")
        capability_id = tool.get("capability_id")
        arguments = tool.get("arguments")
        reason = tool.get("reason")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise _invalid("CALL_TOOL capability_id must be a non-empty string")
        if not isinstance(arguments, Mapping):
            raise _invalid("CALL_TOOL arguments must be an object")
        if not isinstance(reason, str) or not reason.strip():
            raise _invalid("CALL_TOOL reason must be a non-empty string")
        return CallToolAction(
            capability_id=capability_id,
            arguments=dict(arguments),
            reason=reason,
        )

    raise _invalid("action must be FINAL or CALL_TOOL")


@dataclass(frozen=True)
class ModelResponse:
    """Provider-neutral result returned to the investigation graph."""

    action: Action | None
    model: str
    provider: str
    usage: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))

    @property
    def content(self) -> dict[str, Any] | None:
        return self.action.to_dict() if self.action is not None else None

    @property
    def safe_metadata(self) -> dict[str, Any]:
        return dict(self.metadata)

    @property
    def token_source(self) -> str:
        return str(self.safe_metadata.get("token_source", "unknown"))


class ModelGateway(ABC):
    """Provider-neutral model interface consumed by later graph tasks."""

    @abstractmethod
    def invoke(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    def stream(self, request: ModelRequest):
        """Yield one complete response for providers without streaming yet."""

        yield self.invoke(request)


def configured_value(name: str, default: Any = None) -> Any:
    """Read a setting first, then the process environment.

    Importing Django lazily keeps provider schema tests usable without a Django
    runtime while still honoring ``override_settings`` in web tests.
    """

    try:
        from django.conf import settings

        if settings.configured and hasattr(settings, name):
            value = getattr(settings, name)
            if value is not None:
                return value
    except (ImportError, RuntimeError):
        pass
    return os.getenv(name, default)


def configured_timeout() -> float:
    raw = configured_value("LLM_TIMEOUT_SECONDS")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ModelGatewayConfigurationError("LLM timeout configuration is invalid")
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        raise ModelGatewayConfigurationError("LLM timeout configuration is invalid") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ModelGatewayConfigurationError("LLM timeout configuration is invalid")
    return timeout


def normalize_base_url(value: Any) -> str:
    base_url = value
    if not isinstance(base_url, str) or not base_url.strip():
        raise ModelGatewayConfigurationError("model base URL configuration is invalid")
    if _has_forbidden_url_characters(base_url):
        raise ModelGatewayConfigurationError("model base URL configuration is invalid")
    base_url = base_url.rstrip("/")
    try:
        parsed = urlparse(base_url)
        port = parsed.port
    except ValueError:
        raise ModelGatewayConfigurationError("model base URL configuration is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is None and parsed.netloc.endswith(":")
        or port is not None and not 1 <= port <= 65535
        or parsed.query
        or parsed.fragment
    ):
        raise ModelGatewayConfigurationError("model base URL configuration is invalid")
    return base_url


def _has_forbidden_url_characters(value: str) -> bool:
    try:
        decoded = unquote(value)
    except (TypeError, ValueError):
        return True
    return any(
        character == "\\"
        or character.isspace()
        or ord(character) < 0x20
        or ord(character) == 0x7F
        for character in f"{value}{decoded}"
    )


def configured_model(name: str) -> str:
    model = configured_value(name)
    if not isinstance(model, str) or not model.strip():
        raise ModelGatewayConfigurationError("model name configuration is invalid")
    return model.strip()


def coerce_request(request: ModelRequest | Mapping[str, Any]) -> ModelRequest:
    if isinstance(request, ModelRequest):
        return request
    if isinstance(request, Mapping) and "messages" in request:
        return ModelRequest(messages=request["messages"], metadata=request.get("metadata", {}))
    raise TypeError("model request must be a ModelRequest")


def usage_from_payload(payload: Mapping[str, Any], *, provider: str) -> tuple[dict[str, int], str]:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        usage = payload

    prompt = _nonnegative_int(usage.get("prompt_tokens", usage.get("prompt_eval_count")))
    completion = _nonnegative_int(
        usage.get("completion_tokens", usage.get("eval_count"))
    )
    total = _nonnegative_int(usage.get("total_tokens"))
    if total == 0 and (prompt or completion):
        total = prompt + completion
    source = "provider" if any((prompt, completion, total)) else "unavailable"
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }, source


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


_SAFE_METADATA_KEYS = {
    "token_source",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
}
_SAFE_TOKEN_SOURCES = {"provider", "estimated", "unavailable"}


def _safe_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only non-sensitive accounting metadata in the public response."""

    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, Any] = {}
    source = value.get("token_source")
    if source in _SAFE_TOKEN_SOURCES:
        safe["token_source"] = source
    for key in _SAFE_METADATA_KEYS - {"token_source"}:
        if key in value:
            safe[key] = _nonnegative_int(value[key])
    return safe


def extract_ollama_content(payload: Mapping[str, Any]) -> str:
    message = payload.get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise _invalid("Ollama response has no message content")
    return message["content"]


def extract_openai_content(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise _invalid("OpenAI-compatible response has no choices")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise _invalid("OpenAI-compatible response choice is invalid")
    message = choice.get("message")
    if not isinstance(message, Mapping) or not isinstance(message.get("content"), str):
        raise _invalid("OpenAI-compatible response has no message content")
    return message["content"]
