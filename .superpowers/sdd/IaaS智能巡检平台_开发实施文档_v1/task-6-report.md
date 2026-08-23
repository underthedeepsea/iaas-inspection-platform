# Task 6 report: inspection execution and deterministic coverage

## Scope

- Added code-first execution for the Task 4 persisted mock datasets.
- Added deterministic required/resolved/material Claim coverage and AI admission.
- Added isolated Finding specification/persistence helpers.
- Persisted one `InspectionItemRun` per `(InspectionRun, InspectionItem)` and its Finding rows transactionally.
- Did not implement risk correlation, snapshots, Airflow, LLM calls, or APIs.

## RED

The three scenario tests were written first in `tests/domain/test_inspection_execution.py` and run before the service modules existed. With the required project Python, Django dev settings, and PostgreSQL access enabled, the focused command failed at the intended missing production boundary:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_inspection_execution.py -q
FFF                                                                      [100%]
ModuleNotFoundError: No module named 'apps.inspections.services'
3 failed in 1.44s
```

An initial sandbox-only attempt was blocked by the environment's PostgreSQL network restriction (`Operation not permitted`); the approved database-enabled rerun captured the expected import failures above.

## GREEN

Focused scenario and persistence contracts:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_inspection_execution.py -q
...                                                                      [100%]
3 passed in 1.36s
```

The tests assert literal persisted values for all three scenarios:

- `control_plane_anti_affinity`: `CODE_ONLY`, `NO_AI`, the exact required/resolved/empty-gap Claim sets, 100% code coverage, and an active `CONTROL_PLANE_ANTI_AFFINITY` topology Finding.
- `llm_scheduler_pressure`: deterministic degradation Finding, `AI_ELIGIBLE`, and exactly one material gap: `llm.performance.degradation_category`.
- `data_incomplete`: `DATA_INVALID`, `data_valid=False`, missing `queue_depth`, no material AI gap, and an `INVALID` `DATA_INCOMPLETE` Finding.

Mutation checks confirmed the tests catch the material persistence/admission regressions:

```text
# Mutated AI_ELIGIBLE -> NO_AI
1 failed (the LLM admission assertion)

# Mutated Finding persistence to persist an empty set
1 failed (the control-plane Finding lookup)
```

After restoring both mutations, the focused suite returned `3 passed`.

Full suite and project checks:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
......................................................                   [100%]
54 passed in 1.90s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

git diff --check
# no output
```

## Implementation

- `apps/inspections/services/coverage.py`: `ClaimCoverage` and deterministic coverage/admission calculation. The Task 5 registry is consulted; positive Claims established by the built-in deterministic detector remain code-resolved even if a separate registry binding has not been seeded yet.
- `apps/inspections/services/findings.py`: `FindingSpec` and scoped, retry-safe Finding persistence.
- `apps/inspections/services/execution.py`: persisted-row execution boundary, Task 4 metric/event detectors, literal Claim summaries, AI admission status, asset scope, and run counters.
- `apps/inspections/services/__init__.py`: service exports.
- `tests/domain/test_inspection_execution.py`: real PostgreSQL scenario tests with literal Claim sets and persisted row assertions.

## Self-review

- Execution, coverage/admission, and Finding persistence are separate modules.
- No LLM/runtime call, risk model write, snapshot, Airflow, or API path was added.
- `data_incomplete` exits through `DATA_INVALID` before Claim resolution and cannot become AI eligible due to missing evidence.
- Retries replace only Findings for the same item run; the unique database constraint preserves one `InspectionItemRun`.
- Re-running an item refreshes its current Claim coverage and `InspectionItem.code_coverage_percent` rather than retaining stale run metadata.
- No migration was required because Task 3 already persisted the run/finding schema.

## Concerns

- The detector intentionally supports only Task 4's `control_plane_anti_affinity`, `llm_scheduler_pressure`, and `data_incomplete` cases; other design scenarios remain out of scope.
- Whole-run status closing remains caller-owned; this task updates item counts and active Finding count without implementing the later DAG lifecycle.
- The existing `InspectionItem` schema has no `unresolved_claims` column, so the literal unresolved/material gap sets are persisted in `InspectionItemRun.summary`.
