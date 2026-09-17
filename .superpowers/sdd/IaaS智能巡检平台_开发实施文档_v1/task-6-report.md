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

- `apps/inspections/services/coverage.py`: `ClaimCoverage` and deterministic coverage/admission calculation. The Task 5 registry is authoritative; detector Claims resolve only through an active registered resolver.
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
- Whole-run status closing remains caller-owned; this task updates item counts without implementing the later DAG lifecycle or Risk count.
- The existing `InspectionItem` schema has no `unresolved_claims` column, so the literal unresolved/material gap sets are persisted in `InspectionItemRun.summary`.

## Fix Round 1

### Review findings addressed

- `_asset_scope` now reads the persisted `Asset` rows for the run's environment and sorts their stored external keys; it never regenerates a dataset. A regression mutates one persisted key and deletes another, then asserts the stored scope reflects those exact database rows.
- Claim coverage now treats `CapabilityRegistry.resolve` as authoritative. Detector facts resolve only through an enabled, active `CODE_ACTIVE` resolver. Missing, SHADOW, disabled-binding, inactive-capability, and registry-without-`resolve` cases all remain unresolved and AI-eligible only because their material gaps are explicit.
- `_update_run_counts` no longer writes Finding counts into `InspectionRun.risk_count`; that field remains owned by the later Risk stage. The control-plane persistence test asserts it remains zero after a Finding is saved.
- Data validity now inspects persisted required metric rows. A `READY` scheduler-pressure dataset with all `queue_depth` rows deleted and a cleared generator config is `DATA_INVALID` and never AI eligible.
- Existing item-run retries acquire the row with `select_for_update()` before replacing scoped Findings. Unused speculative service aliases were removed from coverage, execution, and Finding modules.

### RED/GREEN evidence

Regression tests were added before the production fixes. The focused pre-fix run reported:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_inspection_execution.py -q
FFFFFFFF..                                                               [100%]
8 failed, 2 passed in 1.81s
```

The failures were the expected regenerated scope, four non-authoritative resolver states, no-`resolve` registry, risk-count pollution, and deleted queue evidence cases.

After the fixes:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_inspection_execution.py -q
..........                                                               [100%]
10 passed in 1.67s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
.............................................................            [100%]
61 passed in 2.21s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

git diff --check
# no output
```

### Fix Round 1 self-review

- The persisted-scope regression proves asset metadata is read from the database rather than reconstructed from `seed`/`scenario`.
- Registry negative cases cover absence, no method, disabled binding, inactive capability, and SHADOW version/item state; the original active resolver scenarios remain explicit.
- Finding persistence remains separate from run counters, and no risk model write was introduced.
- Required metric completeness is evaluated from the rows loaded for the persisted dataset, with `queue_depth` treated as required for both scheduler-pressure and incomplete-data scenarios.
- No model or migration changes were needed.

### Fix Round 1 concerns

- The existing schema relates `Asset` to `Environment`, not directly to `MockDataset`; scope therefore uses all persisted assets in the run environment, which is the strongest dataset provenance available without a migration.
- Task 6 still intentionally excludes Risk lifecycle, snapshots, Airflow, LLM calls, APIs, and unsupported Task 4 scenarios.

## Fix Round 2

### Important finding addressed

`_asset_scope` no longer includes every asset in the Environment. It now forms a distinct union of `asset_id` values from the current dataset's `MockMetric`, `MockLog`, `MockEvent`, and `MockChange` rows, then resolves those persisted rows to sorted `external_key` values. No model or migration change was needed.

The new regression creates one asset referenced only by each evidence table plus an unrelated same-environment asset with no rows for the dataset. It asserts all four evidence assets and the generated metric assets are included while the unrelated asset is excluded. Existing scope tests now assert the evidence-derived set rather than the generator's complete asset list.

### RED/GREEN evidence

The scope expectations and cross-table regression were written before changing `_asset_scope`. The focused pre-fix run reported:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_inspection_execution.py -q
FFF........                                                              [100%]
3 failed, 8 passed in 1.91s
```

The first implementation run exposed and fixed a missing `MockChange` import; after that, one prior mutation test was corrected to reflect that `host-control-0` has no current dataset evidence row. The final focused and full verification were:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_inspection_execution.py -q
...........                                                              [100%]
11 passed in 1.82s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
..............................................................           [100%]
62 passed in 2.35s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

git diff --check
# no output
```

### Fix Round 2 self-review

- Every scope query is constrained by the current `MockDataset` primary key and every source model's non-null `asset_id`.
- Set union removes duplicate references before the final persisted `Asset` lookup; `external_key` sorting makes the JSON scope deterministic.
- The regression uses unique assets per evidence table and a no-row unrelated asset, so removing any source query or broadening to Environment-wide lookup fails the test.
- No migrations, generators, scenario reconstruction, risk writes, or API changes were added.

### Fix Round 2 concerns

- Assets persisted for a dataset but not referenced by any of the four supported evidence tables are intentionally excluded; the requested scope contract is evidence-derived.
- Task 6 remains limited to the three supported deterministic scenarios and does not implement later Risk, snapshot, Airflow, LLM, or API stages.
