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

## Fix Round 1 (2026-08-24)

### RED

- Added regression coverage for each missing Ollama setting (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `LLM_TIMEOUT_SECONDS`) and invalid URL/model/timeout values. The first run failed because the provider supplied source fallbacks and accepted malformed URLs/`nan` timeout values.
- Added a public-boundary regression requiring `ModelResponse` to have no `raw` field and metadata to allow only token accounting fields. It initially failed because provider responses exposed the complete raw body and recursive sanitization admitted arbitrary URL/secret-bearing keys.
- The initial Fix Round 1 run showed 8 failures and 14 existing passes, including the expected `raw` and fallback failures.

### GREEN

- Ollama now requires all three settings from Django/environment configuration, validates finite positive timeout and an HTTP(S) URL without credentials/query/fragment/invalid port, and raises stable `MODEL_GATEWAY_CONFIGURATION_INVALID` before invoking the injected HTTP client.
- `ModelResponse.raw` was removed from the public contract. Metadata is normalized at construction through a strict allowlist (`token_source`, `prompt_tokens`, `completion_tokens`, `total_tokens`); arbitrary access tokens, API keys, endpoints, URLs, nested values, and credential-bearing URLs are discarded.
- Focused Task 10 suite: `25 passed in 0.09s`.
- Full Web suite with local PostgreSQL: `141 passed in 5.63s`.
- `manage.py check`: `System check identified no issues (0 silenced).`
- `manage.py makemigrations --check --dry-run`: `No changes detected`.
- `compileall` and `git diff --check`: passed.

### Fix Round 1 risk

- The documented local `.env.example` values remain the intended runtime configuration; an Ollama provider now fails closed when deployment configuration is absent instead of silently targeting a local daemon. OpenAI-compatible configuration also no longer supplies a timeout/model fallback.

## Fix Round 2 (2026-08-24)

### RED

- Added Ollama and OpenAI-compatible regressions for raw/percent-encoded authority whitespace, control characters, and backslashes, while also adding valid IPv4/IPv6 and ports `1`/`65535` boundary cases. The initial run failed 15 cases: the shared validator accepted all six invalid authority variants, and both providers trusted a response-body model name.
- Added response fixtures containing `https://user:secret@attacker.internal/v1`; the initial `ModelResponse.model` assertions failed because both providers used `body["model"]`.

### GREEN

- The shared URL validator now rejects forbidden characters in both the configured string and percent-decoded form before parsing or any HTTP call, while preserving valid IPv4/IPv6 authority and port boundaries.
- Ollama and OpenAI-compatible responses always expose `self.model`; provider response metadata such as `credential_url` is not retained, so `repr(ModelResponse)` contains neither the attacker host nor secret.
- Focused Task 10 suite: `42 passed in 0.10s`.
