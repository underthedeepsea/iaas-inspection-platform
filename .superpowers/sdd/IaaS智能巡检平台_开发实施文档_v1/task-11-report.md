# Task 11 report: LangGraph Investigation Graph

## Status

DONE — implemented the provider-neutral investigation graph, strict Claim Gap
tool gate, bounded Evidence output, deterministic budgets, and stable terminal
result shape. The graph has no database persistence, Conversation/SSE/API, or
Task 12 orchestration.

## RED / GREEN evidence

### RED round 1

- Added `tests/services/test_investigation_graph.py` before the graph modules.
- The focused run failed with 8 expected `ModuleNotFoundError: No module named
  'services.investigation_graph.graph'` failures, proving the tests exercised the
  missing contract rather than existing behavior.

### GREEN round 1

- Added the state, schema, node, graph, and package modules.
- Direct FINAL, Claim Gap, read-only security, max-round, max-tool-call, and
  stable-result scenarios passed: `8 passed`.

### RED/GREEN security hardening rounds

- A non-serialisable successful tool result with an unconstrained output schema
  first crashed during summary JSON encoding; the regression then passed after
  unsupported output was rejected before Evidence creation.
- An over-budget initial counter regression first reported `99`, violating the
  hard ceiling; counters are now clamped in `build_context`, and the regression
  passes.
- Model tool arguments are sanitized before they enter graph state or executor
  dispatch; provider URLs/passwords are not retained.
- Final focused graph suite: `12 passed`.

## Implementation decisions

- `build_investigation_graph(gateway=..., registry=..., executor=...)` requires
  the provider-neutral gateway and lazily creates defaults only when a tool path
  actually needs them. Direct FINAL execution therefore does not require a live
  Ollama service or even Django configuration.
- `ModelGateway.parse_action` remains the single strict parser for `FINAL` and
  `CALL_TOOL`. Claim Gap selection then resolves the model capability ID through
  the Registry, verifies active capability/version status, exact `read_only is
  True`, compatible claim, and JSON Schema arguments before dispatch.
- Tool execution always uses `ExecutionOrigin.LLM`; the existing
  `PluginExecutor` remains the backend safety boundary. Successful output is
  output-schema validated and reduced to bounded, JSON-safe Evidence. URLs,
  credentials, raw/payload fields, deep/unbounded values, and ORM objects are
  excluded from state.
- `max_rounds` and `max_tool_calls` are independent hard ceilings (defaults 3
  and 5), counters are clamped and incremented only within budget, and budget
  exhaustion routes directly to a deterministic `UNRESOLVED` terminal result.
- Every terminal path exposes `summary: str`, `conclusion: str`, `facts: list[str]`,
  and `next_steps: list[str]`, with the same shape nested in `final`.
- Added `CapabilityRegistry.resolve_capability()` so active Claim Gap
  capabilities can be resolved independently of the formal CODE_ACTIVE resolver
  path; the graph still performs the read-only and schema gates itself.

## Verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest \
  tests/services/test_investigation_graph.py -q
12 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest -q
170 passed in 5.73s

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py \
  makemigrations --check --dry-run
No changes detected

/opt/homebrew/bin/python3 -m compileall -q services tests/services/test_investigation_graph.py
git diff --check
```

## Risks / follow-up

- Registry-backed Claim Gap execution is covered by the existing database test
  environment and the graph fake-registry tests; no live LLM or external
  capability backend is contacted.
- The graph intentionally keeps Evidence in memory. Task 12 should persist
  `final`, tool-call metadata, and Evidence through its own Conversation/SSE
  orchestration rather than extending this task.

## Fix Round 1 — reviewer hardening

### RED / GREEN

- Added regression coverage first for normalized sensitive keys, invalid
  capability identifiers, missing Claim Gap, byte caps, 8/8 budgets, safe
  Tool Call handoff, and registry-backed atomic dispatch.
- The first focused Fix run was intentionally RED: 19 tests ran with 6
  failures (the new security/contract assertions).
- After the smallest implementation changes, the focused suite is GREEN:
  19 passed.

### Security and boundedness decisions

- State-bound capability IDs, claims, argument keys, evidence keys, and tool
  history use ASCII identifier contracts plus case/punctuation-normalized
  sensitive-key rejection. This covers apiKey, api-key, accessKey, id_token,
  passwd, authorization/secret/token variants, and URL/raw fields. Declared
  output-schema properties act as a positive public-field allowlist when
  available.
- A CALL_TOOL cannot reach Registry resolution or execution without one
  canonical, non-empty missing_claim. Resolver adapters never fall back to a
  broad claim=None lookup.
- Context and Evidence payloads use deterministic JSON byte ceilings
  (MAX_CONTEXT_BYTES=4096, MAX_EVIDENCE_PAYLOAD_BYTES=4096) with stable,
  valid truncation.
- Factory and invocation budgets are bounded before graph execution. The
  wrapper derives a safe LangGraph recursion limit, preserves an explicit
  caller recursion_limit, and terminates 8-round/8-tool runs structurally.
- State and final include bounded Tool Call history containing only
  capability ID, sanitized arguments/reason, status/outcome, error code, and
  evidence key; raw result/error text is never copied.
- CapabilityRegistry.resolve_capability() selects only the active
  Capability.current_version; execute_readonly() locks and rechecks the
  capability/current version, ACTIVE/read-only/claim/schema gates, and then
  dispatches under one transaction to close the authorization/dispatch TOCTOU
  window.

### Fix Round 1 verification

~~~text
DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q tests/services/test_investigation_graph.py
19 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q tests/services/test_investigation_graph.py \
  tests/services/test_model_gateway.py tests/services/test_plugin_security.py
88 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q tests/services/test_capability_registry.py
7 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q
179 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

python3 -m compileall -q services \
  tests/services/test_investigation_graph.py tests/services/test_capability_registry.py
git diff --check
~~~

### Remaining risks

- The graph remains intentionally in-memory; Task 12 owns persistence and
  conversation/SSE orchestration.
- The default production path uses CapabilityRegistry.execute_readonly() for
  atomic authorization and dispatch. Injected registries must expose the same
  atomic operation; otherwise the graph fails closed with no backend dispatch.

## Fix Round 2 — reviewer hardening

### RED / GREEN

- Added regression coverage before production changes for input-budget
  recursion configuration, strict atomic dispatch results, bounded supplied
  messages, terminal budget history, and direct Action validation.
- The initial Fix Round 2 focused run was RED: 25 tests ran with 6 expected
  failures. The explicit insufficient-recursion-limit regression was then
  added and independently observed RED before its structured-failure guard
  was implemented.
- Final focused graph suite is GREEN: 26 passed.

### Contract decisions

- A non-empty caller config without recursion_limit receives the current
  invocation's effective budget-derived limit, not the factory default.
  Explicit limits below that safe minimum fail closed as a normalized,
  stable UNRESOLVED/BUDGET_EXHAUSTED result; no LangGraph recursion exception
  escapes and no gateway/tool call starts.
- Atomic registry execution must return exactly (version, raw_result), with
  non-null version. The graph always re-runs capability/claim/schema checks
  and validates the returned version output schema before Evidence.
- Every model request includes the fixed protocol/read-only system message,
  compressed investigation context, and a deterministic whole-packet
  MAX_CONTEXT_BYTES ceiling. Supplied message history contributes role
  metadata only; raw log contents are never passed through.
- A selected/pending call encountered after a hard budget is converted to
  REJECTED/BUDGET_EXHAUSTED history before the terminal result. A tool selected
  during the final allowed round remains executable; the next round is
  stopped by the existing round gate.
- Direct FinalAction/CallToolAction responses are round-tripped through
  parse_action(action.to_dict()); malformed dataclass actions become stable
  FAILED/STRUCTURED_OUTPUT_INVALID results.

### Fix Round 2 verification

~~~text
DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q tests/services/test_investigation_graph.py
26 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q tests/services/test_investigation_graph.py \
  tests/services/test_model_gateway.py tests/services/test_plugin_security.py
95 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/pytest -q
186 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  .venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

python3 -m compileall -q services \
  tests/services/test_investigation_graph.py tests/services/test_capability_registry.py
git diff --check
~~~

## Fix Round 3 — reviewer hardening

### RED / GREEN

- Added low-recursion normalization and normal-return message-state
  regressions before production changes. The focused run was RED with 3
  expected failures: low-limit state leaked unnormalized fields and the
  public message state retained content.
- The GREEN focused graph suite is `28 passed`.

### Contract decisions

- `_ConfiguredGraph._prepare()` now runs the local `build_context()` safety
  normalization before checking an explicit recursion limit. A rejected low
  limit therefore receives the same redaction, deterministic byte bounds,
  counter clamps, and safe evidence/history state as a normal invocation,
  then terminates as stable `UNRESOLVED/BUDGET_EXHAUSTED` final output.
- This early normalization is pure and dependency-free: it does not invoke
  the gateway, registry, executor, or any external provider.
- Public graph `messages` retain only bounded role metadata; no content,
  transcript, URL, credential, or raw log is kept in returned state. Model
  outbound messages continue to use the fixed protocol/read-only system
  message and compact context/history envelope.
- Input mappings and nested caller values are not mutated. UTF-8 byte-length
  assertions cover normalized context and public message metadata.

### Fix Round 3 verification

~~~text
DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest -q \
  tests/services/test_investigation_graph.py
28 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest -q \
  tests/services/test_investigation_graph.py \
  tests/services/test_model_gateway.py tests/services/test_plugin_security.py
97 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest -q
188 passed

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

DJANGO_SETTINGS_MODULE=config.settings.dev PYTHONPATH=. \
  /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py \
  makemigrations --check --dry-run
No changes detected

python3 -m compileall -q services \
  tests/services/test_investigation_graph.py tests/services/test_capability_registry.py
git diff --check
~~~

## Files

- `services/investigation_graph/state.py`
- `services/investigation_graph/schemas.py`
- `services/investigation_graph/nodes.py`
- `services/investigation_graph/graph.py`
- `services/investigation_graph/__init__.py`
- `services/plugin_runtime/registry.py`
- `tests/services/test_investigation_graph.py`
