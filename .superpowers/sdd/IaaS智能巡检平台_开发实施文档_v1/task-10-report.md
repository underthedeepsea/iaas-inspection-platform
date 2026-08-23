# Task 10 report: Model Gateway 与 Ollama

## Status

DONE — Model Gateway contract, strict structured-action validation, Ollama HTTP provider, and the minimal OpenAI-compatible provider are implemented and verified. No live Ollama daemon is required by the tests.

## RED / GREEN evidence

### RED round 1

- Added `tests/services/test_model_gateway.py` before any gateway production module existed.
- `PYTHONPATH=. pytest -q tests/services/test_model_gateway.py` failed with 11 expected `ModuleNotFoundError: No module named 'services.model_gateway'` failures.
- A first command without `PYTHONPATH=.` failed at import resolution (`No module named 'services'`); it was rerun with the repository import path so the captured feature failure was unambiguous.

### GREEN round 1

- Implemented the base contract and providers.
- Focused suite passed: `11 passed in 0.08s`.

### RED / GREEN round 2

- Added regressions for non-2xx health responses and exactly-once health status checking.
- The successful-health regression initially failed because `_send()` and `health_check()` both called `raise_for_status()` (`Called 2 times`).
- Removed the duplicate check; final focused suite passed: `13 passed in 0.08s`.

## Design choices

- `ModelGateway` exposes `invoke(ModelRequest) -> ModelResponse` and a one-response fallback `stream()` contract for later graph consumers.
- `parse_action()` accepts decoded objects or JSON text and strictly validates exactly the documented `FINAL` and `CALL_TOOL` shapes. Unknown actions and malformed payloads raise `StructuredOutputInvalidError` with stable code `STRUCTURED_OUTPUT_INVALID` without echoing raw provider output.
- `OllamaProvider` posts only to configured `{OLLAMA_BASE_URL}/api/chat` with configured `OLLAMA_MODEL`, `stream: false`, `format: json`, configured messages, and `LLM_TIMEOUT_SECONDS`. Request compatibility fields named `model`/`base_url` are ignored, so callers cannot reroute a request.
- Ollama health checks use `/api/tags`; transport, timeout, invalid URL, HTTP status, and connectivity failures become `LLMUnavailableError` with stable code `LLM_UNAVAILABLE`. Error messages and response metadata do not contain URLs, credentials, or API keys.
- Provider token counters normalize Ollama (`prompt_eval_count`/`eval_count`) and OpenAI-compatible (`usage`) fields to zero when absent, with a `token_source` metadata marker.
- `OpenAICompatibleProvider` intentionally uses the existing `httpx` dependency and only implements the required JSON `/chat/completions` contract; it does not add SDK-specific or speculative features.

## Verification

- Focused Task 10 tests: `13 passed in 0.08s`.
- Full Web suite with `DJANGO_SETTINGS_MODULE=config.settings.dev`, project `PYTHONPATH`, and local PostgreSQL access: `129 passed in 5.38s`.
- `manage.py check`: `System check identified no issues (0 silenced).`
- `manage.py makemigrations --check --dry-run`: `No changes detected`.
- `python -m compileall -q services/model_gateway tests/services/test_model_gateway.py`: passed.
- `git diff --check`: passed.

## Risks / follow-up

- OpenAI-compatible transport is contract-tested with a mocked HTTP response; no external enterprise endpoint is contacted.
- Token usage depends on provider counters; when the provider omits counters, the gateway records zero counters and marks the source unavailable rather than fabricating an estimate.
- The base gateway does not implement the LangGraph investigation loop; that remains Task 11 scope.

## Files

- `services/model_gateway/base.py`
- `services/model_gateway/ollama.py`
- `services/model_gateway/openai_compatible.py`
- `services/model_gateway/__init__.py`
- `tests/services/test_model_gateway.py`
