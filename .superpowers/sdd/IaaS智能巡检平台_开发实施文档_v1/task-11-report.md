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

## Files

- `services/investigation_graph/state.py`
- `services/investigation_graph/schemas.py`
- `services/investigation_graph/nodes.py`
- `services/investigation_graph/graph.py`
- `services/investigation_graph/__init__.py`
- `services/plugin_runtime/registry.py`
- `tests/services/test_investigation_graph.py`
