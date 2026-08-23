# Task 5 report: Capability Registry and secure plugin executors

## Scope

- Implemented the database-backed registry and RULE, EXEC, REST, and fake-MCP executor boundaries.
- No API, registration/publishing flow, production MCP integration, migrations, or unrelated refactoring was added.

## RED/GREEN evidence

1. Added registry and security tests before runtime modules existed.
   - RED: `pytest tests/services/test_capability_registry.py tests/services/test_plugin_security.py -q` reported four expected `ModuleNotFoundError: services.plugin_runtime` failures. The two database tests could not initialise because the sandbox disallowed local PostgreSQL access.
   - GREEN: after implementation, non-database security tests passed (`4 passed`), and with local PostgreSQL access registry tests passed (`2 passed`).
2. URL host-boundary regression test was added before its implementation.
   - RED: `test_rest_rejects_a_hostname_that_only_looks_like_a_local_prefix` reached `localhost.evil` and failed because the error was `REST plugin request failed`, not a rejected endpoint.
   - GREEN: parsed URL scheme/host/port/path matching rejects it before dispatch; the security module passed (`6 passed`).
3. Traversal regression test was added before its implementation.
   - RED: `test_exec_rejects_traversal_even_when_it_resolves_back_into_the_allowlist` failed with `DID NOT RAISE`.
   - GREEN: explicit `..` rejection was added; the security module passed (`7 passed`).

## Security cases verified

- LLM-origin execution rejects `capability.read_only=False` before backend dispatch.
- Stored JSON Schema is validated before dispatch.
- EXEC rejects paths outside `plugins/exec`, symlink escapes, and traversal; it uses an argument list, `shell=False`, a model timeout, and JSON stdout.
- EXEC converts timeouts, nonzero exits, and malformed JSON to domain errors.
- REST allows only configured internal/local parsed URL prefixes and rejects host-prefix confusion.
- Formal resolution returns only an enabled `CODE_ACTIVE` inspection binding with an active capability/version; `resolve_shadow` only returns enabled `SHADOW` equivalents and has no mutation path.

## Files

- `services/plugin_runtime/registry.py`
- `services/plugin_runtime/executor.py`
- `services/plugin_runtime/errors.py`
- `services/plugin_runtime/rule_executor.py`
- `services/plugin_runtime/exec_executor.py`
- `services/plugin_runtime/rest_executor.py`
- `services/plugin_runtime/mcp_executor.py`
- `tests/services/test_capability_registry.py`
- `tests/services/test_plugin_security.py`

## Commands and results

```text
DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/pytest tests/services/test_capability_registry.py tests/services/test_plugin_security.py -q
9 passed in 1.33s

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/pytest -q
28 passed in 1.70s

DJANGO_SETTINGS_MODULE=config.settings.dev .venv-web/bin/python manage.py check
System check identified no issues (0 silenced).
```

## Self-review

- Confirmed registry queries registered Django models only; no module-name dispatch is present.
- Confirmed formal and shadow status filters are separate and read-only.
- Confirmed resolved script containment follows symlinks, rejects traversal, and never invokes a shell.
- Confirmed REST comparison parses URLs instead of trusting string prefixes.
- `git diff --check` reported no whitespace errors; no model changes mean migration consistency remains clean.

## Concerns

- The fake MCP adapter deliberately raises without a supplied adapter; production MCP remains out of scope.
- REST uses the default local/internal prefixes unless `PLUGIN_REST_ALLOWED_PREFIXES` is configured by a later deployment task.

## Fix Round 1

### Findings addressed

- REST allowlist now compares effective ports (`80`/`443` when the URL omits a port) for every authority, rejects user-info and unsupported schemes, rejects raw and percent-encoded path escape segments before prefix matching, and maps malformed URL/port handling to `RestExecutionError`.
- Plugin origins use the strict `ExecutionOrigin.CODE` / `ExecutionOrigin.LLM` contract. Exact canonical strings and the existing boolean compatibility flag are normalized deliberately; lowercase, unknown, non-string, and conflicting values are rejected before validation or backend dispatch.
- EXEC is read-only at both `PluginExecutor` and the direct `ExecExecutor` boundary. A future write path must use the separate Action Gateway boundary described by the design.
- Stored JSON Schema `ValidationError`, `SchemaError`, and malformed-schema `TypeError` cases are normalized to `InputValidationError`.
- Added EXEC argv/shell/JSON-result, timeout, nonzero-exit, and malformed-stdout regressions, plus registry exclusions for disabled bindings, inspection items, and capabilities.

### RED/GREEN evidence

1. Security regressions were added before the runtime fix.
   - RED: `DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest tests/services/test_plugin_security.py -q` reported `14 failed, 12 passed`; failures covered the missing strict origin contract, EXEC write gate, invalid stored schema handling, effective-port comparison, encoded traversal rejection, and malformed-port normalization.
   - GREEN: the same focused command reported `27 passed in 0.07s` after the fix.
2. Registry disabled-state tests were verified against a deliberately removed-filter mutation.
   - RED: `.../pytest tests/services/test_capability_registry.py -q` reported `3 failed, 2 passed`; each disabled binding/item/capability case resolved when its filter was removed.
   - GREEN: after restoring the filters, the focused command reported `5 passed in 1.43s`.

### Final verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest -q
51 passed in 2.05s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

git diff --check
No output (clean)
```

### Self-review

- The REST comparison is performed before `httpx.post`; malformed ports cannot reach the HTTP client.
- Origin normalization is performed before schema validation and all backend lookup, so unknown origin values cannot be interpreted as non-LLM calls.
- EXEC read-only checks run before path resolution and subprocess dispatch, and subprocess invocation remains an argv list with `shell=False` and a timeout.
- Registry resolution remains database-backed and excludes disabled binding/item/capability state for both formal and shadow resolution.
- No model or migration files changed; migration consistency is clean.
