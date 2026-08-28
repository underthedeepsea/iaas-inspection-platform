import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest


def _final_payload():
    return {
        "action": "FINAL",
        "answer": {"summary": "queue is healthy", "confidence": 0.8},
    }


def test_parse_action_accepts_documented_final_payload():
    from services.model_gateway.base import FinalAction, parse_action

    action = parse_action(_final_payload())

    assert isinstance(action, FinalAction)
    assert action.action == "FINAL"
    assert action.summary == "queue is healthy"
    assert action.confidence == 0.8


def test_parse_action_accepts_documented_call_tool_payload():
    from services.model_gateway.base import CallToolAction, parse_action

    action = parse_action(
        {
            "action": "CALL_TOOL",
            "tool": {
                "capability_id": "llm.scheduler.pressure",
                "arguments": {"asset_id": "llm-0"},
                "reason": "need scheduler queue ratio",
            },
        }
    )

    assert isinstance(action, CallToolAction)
    assert action.action == "CALL_TOOL"
    assert action.capability_id == "llm.scheduler.pressure"
    assert action.arguments == {"asset_id": "llm-0"}
    assert action.reason == "need scheduler queue ratio"


def test_parse_action_rejects_unknown_action_with_stable_code():
    from services.model_gateway.base import StructuredOutputInvalidError, parse_action

    with pytest.raises(StructuredOutputInvalidError) as raised:
        parse_action({"action": "WRITE_DATABASE", "payload": {}})

    assert raised.value.code == "STRUCTURED_OUTPUT_INVALID"


def test_fake_provider_calls_one_configured_tool_then_finishes(monkeypatch):
    monkeypatch.setenv("FAKE_CAPABILITY_ID", "e2e.llm.scheduler.pressure")
    monkeypatch.setenv("FAKE_ASSET_ID", "llm-0")

    from services.model_gateway.base import ModelRequest
    from services.model_gateway.fake import FakeProvider

    provider = FakeProvider()
    first = provider.invoke(
        ModelRequest(
            messages=[
                {"role": "user", "content": json.dumps({"context": {"missing_claim": "llm.performance.root_cause"}, "evidence": []})}
            ]
        )
    )
    second = provider.invoke(
        ModelRequest(
            messages=[
                {"role": "user", "content": json.dumps({"context": {"missing_claim": "llm.performance.root_cause"}, "evidence": [{"evidence_key": "tool:1"}]})}
            ]
        )
    )

    assert first.action.action == "CALL_TOOL"
    assert first.action.capability_id == "e2e.llm.scheduler.pressure"
    assert first.action.arguments == {"asset_id": "llm-0"}
    assert second.action.action == "FINAL"


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "FINAL", "answer": {"summary": "missing confidence"}},
        {
            "action": "CALL_TOOL",
            "tool": {
                "capability_id": "capability.id",
                "arguments": [],
                "reason": "not an object",
            },
        },
    ],
)
def test_parse_action_rejects_malformed_documented_actions(payload):
    from services.model_gateway.base import StructuredOutputInvalidError, parse_action

    with pytest.raises(StructuredOutputInvalidError) as raised:
        parse_action(payload)

    assert raised.value.code == "STRUCTURED_OUTPUT_INVALID"


def test_ollama_invoke_posts_json_chat_request_from_configuration(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434/")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "response-model",
        "credential_url": "https://user:secret@attacker.internal/v1",
        "message": {"content": json.dumps(_final_payload())},
        "prompt_eval_count": 12,
        "eval_count": 6,
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("httpx.post", post)

    from services.model_gateway.base import ModelRequest
    from services.model_gateway.ollama import OllamaProvider

    result = OllamaProvider().invoke(
        ModelRequest(messages=[{"role": "user", "content": "status?"}])
    )

    assert result.action.summary == "queue is healthy"
    assert result.model == "qwen3:8b"
    assert result.usage["prompt_tokens"] == 12
    assert result.usage["completion_tokens"] == 6
    assert not hasattr(result, "raw")
    post.assert_called_once_with(
        "http://ollama.internal:11434/api/chat",
        json={
            "model": "qwen3:8b",
            "stream": False,
            "messages": [{"role": "user", "content": "status?"}],
            "format": "json",
        },
        timeout=17.0,
    )
    assert "attacker.internal" not in repr(result)
    assert "secret" not in repr(result)


def test_ollama_response_model_is_always_the_configured_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "configured-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "response-model",
        "credential_url": "https://user:secret@attacker.internal/v1",
        "message": {"content": json.dumps(_final_payload())},
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("httpx.post", post)

    from services.model_gateway.base import ModelRequest
    from services.model_gateway.ollama import OllamaProvider

    result = OllamaProvider().invoke(ModelRequest(messages=[]))

    assert result.model == "configured-model"
    assert "attacker.internal" not in repr(result)
    assert "secret" not in repr(result)


def test_ollama_request_cannot_override_configured_model_or_base_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "message": {"content": json.dumps(_final_payload())},
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("httpx.post", post)

    from services.model_gateway.base import ModelRequest
    from services.model_gateway.ollama import OllamaProvider

    request = ModelRequest(
        messages=[{"role": "user", "content": "status?"}],
        model="attacker-model",
        base_url="http://attacker.invalid",
    )
    OllamaProvider().invoke(request)

    assert post.call_args.args[0] == "http://ollama.internal:11434/api/chat"
    assert post.call_args.kwargs["json"]["model"] == "qwen3:8b"


@pytest.mark.parametrize("missing", ["OLLAMA_BASE_URL", "OLLAMA_MODEL", "LLM_TIMEOUT_SECONDS"])
def test_ollama_missing_configuration_fails_closed_before_http(monkeypatch, missing):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    monkeypatch.delenv(missing, raising=False)
    http_client = Mock()

    from services.model_gateway.base import ModelGatewayConfigurationError
    from services.model_gateway.ollama import OllamaProvider

    with pytest.raises(ModelGatewayConfigurationError) as raised:
        OllamaProvider(http_client=http_client)

    assert raised.value.code == "MODEL_GATEWAY_CONFIGURATION_INVALID"
    assert http_client.mock_calls == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OLLAMA_BASE_URL", "not-a-url"),
        ("OLLAMA_BASE_URL", "http://"),
        ("OLLAMA_BASE_URL", "http://user:secret@ollama.internal:11434"),
        ("OLLAMA_BASE_URL", "http://ollama.internal:0"),
        ("OLLAMA_BASE_URL", "http://ollama.internal?secret=1"),
        ("OLLAMA_MODEL", "   "),
        ("LLM_TIMEOUT_SECONDS", "not-a-number"),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_TIMEOUT_SECONDS", "nan"),
    ],
)
def test_ollama_invalid_configuration_fails_closed_before_http(monkeypatch, name, value):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv(name, value)
    http_client = Mock()

    from services.model_gateway.base import ModelGatewayConfigurationError
    from services.model_gateway.ollama import OllamaProvider

    with pytest.raises(ModelGatewayConfigurationError) as raised:
        OllamaProvider(http_client=http_client)

    assert raised.value.code == "MODEL_GATEWAY_CONFIGURATION_INVALID"
    assert http_client.mock_calls == []


def test_ollama_health_failure_is_llm_unavailable_without_endpoint_leak(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    get = Mock(side_effect=httpx.ConnectError("cannot connect to http://user:secret@ollama.internal"))
    monkeypatch.setattr("httpx.get", get)

    from services.model_gateway.base import LLMUnavailableError
    from services.model_gateway.ollama import OllamaProvider

    with pytest.raises(LLMUnavailableError) as raised:
        OllamaProvider().health_check()

    assert raised.value.code == "LLM_UNAVAILABLE"
    assert "secret" not in str(raised.value)
    assert "ollama.internal" not in str(raised.value)


def test_ollama_health_http_failure_is_llm_unavailable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    response = Mock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=Mock(), response=Mock()
    )
    get = Mock(return_value=response)
    monkeypatch.setattr("httpx.get", get)

    from services.model_gateway.base import LLMUnavailableError
    from services.model_gateway.ollama import OllamaProvider

    with pytest.raises(LLMUnavailableError):
        OllamaProvider().health_check()

    response.raise_for_status.assert_called_once_with()


def test_ollama_health_success_checks_status_once(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    response = Mock()
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr("httpx.get", get)

    from services.model_gateway.ollama import OllamaProvider

    assert OllamaProvider().health_check() is True

    response.raise_for_status.assert_called_once_with()


def test_ollama_invalid_provider_json_is_structured_output_invalid(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"message": {"content": "not json"}}
    monkeypatch.setattr("httpx.post", Mock(return_value=response))

    from services.model_gateway.base import StructuredOutputInvalidError, ModelRequest
    from services.model_gateway.ollama import OllamaProvider

    with pytest.raises(StructuredOutputInvalidError) as raised:
        OllamaProvider().invoke(ModelRequest(messages=[]))

    assert raised.value.code == "STRUCTURED_OUTPUT_INVALID"


def test_openai_compatible_provider_uses_configured_chat_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://model.internal/v1/")
    monkeypatch.setenv("OPENAI_MODEL", "company-model")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "120")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "response-model",
        "credential_url": "https://user:secret@attacker.internal/v1",
        "choices": [{"message": {"content": json.dumps(_final_payload())}}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("httpx.post", post)

    from services.model_gateway.base import ModelRequest
    from services.model_gateway.openai_compatible import OpenAICompatibleProvider

    result = OpenAICompatibleProvider().invoke(
        ModelRequest(messages=[{"role": "user", "content": "status?"}])
    )

    assert result.action.action == "FINAL"
    assert result.model == "company-model"
    assert result.usage["total_tokens"] == 5
    assert "attacker.internal" not in repr(result)
    assert "secret" not in repr(result)
    post.assert_called_once_with(
        "https://model.internal/v1/chat/completions",
        headers={"Authorization": "Bearer secret-key"},
        json={
            "model": "company-model",
            "messages": [{"role": "user", "content": "status?"}],
            "response_format": {"type": "json_object"},
        },
        timeout=120.0,
    )


@pytest.mark.parametrize(
    ("provider", "base_url_env", "model_env", "model"),
    [
        ("ollama", "OLLAMA_BASE_URL", "OLLAMA_MODEL", "ollama-model"),
        ("openai", "OPENAI_BASE_URL", "OPENAI_MODEL", "openai-model"),
    ],
)
@pytest.mark.parametrize(
    "base_url",
    [
        "http://bad host.internal:11434",
        "http://bad\thost.internal:11434",
        "http://bad\nhost.internal:11434",
        "http://bad\\host.internal:11434",
        "http://bad%20host.internal:11434",
        "http://bad%5Chost.internal:11434",
    ],
)
def test_provider_rejects_invalid_authority_characters_before_http(
    monkeypatch, provider, base_url_env, model_env, model, base_url
):
    monkeypatch.setenv(base_url_env, base_url)
    monkeypatch.setenv(model_env, model)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "17")
    if provider == "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    http_client = Mock()

    from services.model_gateway.base import ModelGatewayConfigurationError
    from services.model_gateway.ollama import OllamaProvider
    from services.model_gateway.openai_compatible import OpenAICompatibleProvider

    provider_class = OllamaProvider if provider == "ollama" else OpenAICompatibleProvider
    with pytest.raises(ModelGatewayConfigurationError) as raised:
        provider_class(http_client=http_client)

    assert raised.value.code == "MODEL_GATEWAY_CONFIGURATION_INVALID"
    assert http_client.mock_calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:1",
        "http://127.0.0.1:65535",
        "http://[::1]:1",
        "http://[2001:db8::1]:65535",
    ],
)
def test_normalize_base_url_accepts_valid_ip_and_port_boundaries(base_url):
    from services.model_gateway.base import normalize_base_url

    assert normalize_base_url(base_url) == base_url


def test_model_response_has_no_raw_and_metadata_is_a_strict_safe_allowlist():
    from services.model_gateway.base import ModelResponse

    response = ModelResponse(
        action=None,
        model="qwen3:8b",
        provider="ollama",
        metadata={
            "token_source": "provider",
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "total_tokens": 5,
            "access_token": "access-secret",
            "x-api-key": "api-secret",
            "model_url": "https://user:secret@model.internal/v1",
            "endpoint": "https://model.internal/v1/chat",
            "nested": {"url": "https://user:secret@internal"},
            "unrequested": "should be dropped",
        },
    )

    assert not hasattr(response, "raw")
    assert response.metadata == {
        "token_source": "provider",
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
    }
    assert response.safe_metadata == dict(response.metadata)
    assert all(
        secret not in repr(response)
        for secret in (
            "access-secret",
            "api-secret",
            "model.internal",
            "internal",
            "should be dropped",
        )
    )
