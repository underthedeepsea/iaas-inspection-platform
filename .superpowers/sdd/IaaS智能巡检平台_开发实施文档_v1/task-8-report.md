# Task 8 report: daily snapshot

## RED

The new snapshot tests were written before the service existed. With project
Django settings and PostgreSQL access, the focused RED run failed at the
intended missing production boundary:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_daily_snapshot.py -q
FFFF                                                                     [100%]
ModuleNotFoundError: No module named 'apps.inspections.services.snapshot'
4 failed in 1.42s
```

## GREEN

The focused suite passes with literal persisted snapshot assertions:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_daily_snapshot.py -q
....                                                                     [100%]
4 passed in 1.36s
```

The tests cover:

- five current nonterminal Risks, three P1 risks, one P2 risk, one pending
  action, one pending reverification, and run-scoped NEW/WORSENED/RECOVERED
  history counts of `1/1/1`; terminal RECOVERED/IGNORED/FALSE_POSITIVE rows
  are excluded from current risk totals;
- two valid `NO_AI` cases and one valid `AI_ELIGIBLE` case, with invalid data
  excluded from both case counts;
- Decimal rates rounded to three places: code coverage `75.000`, deterministic
  deflection `40.000`, AI displacement `66.667`, and data completeness
  `80.000`; all zero-denominator rates persist as `0.000`;
- six covered asset keys from persisted item-run scopes, while an unrelated
  asset and a scope from another run are excluded;
- retrying the same run updates the existing `(environment, snapshot_date)`
  row, keeps one persisted snapshot and the same source run, and refreshes
  the stored asset coverage.

## Formula evidence

- `code_coverage_rate = 6 / 8 * 100 = 75.000` across four data-valid item
  runs;
- `deterministic_deflection_rate = 2 / 5 * 100 = 40.000` across all completed
  item runs;
- `ai_displacement_rate = 2 / (2 + 1) * 100 = 66.667`;
- `data_completeness_rate = 4 / 5 * 100 = 80.000`.

Rates use `Decimal` arithmetic and `ROUND_HALF_UP`, never binary floats.

## Implementation

- `apps/inspections/services/snapshot.py`: completed-run validation, persisted
  item-run aggregation, persisted asset-scope coverage, current nonterminal
  risk/status counts, Decimal rates, and transactional idempotent persistence.
- `apps/inspections/services/__init__.py`: exports the snapshot service.
- `tests/domain/test_daily_snapshot.py`: focused red/green domain tests.
- No migration was required; `DailySnapshot` and its environment/date and
  source-run uniqueness constraints already exist in the baseline schema.

## Verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
88 passed in 2.76s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

/Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m compileall -q apps/inspections/services tests/domain/test_daily_snapshot.py
git diff --check
```

## Self-review

- The service locks the source run and existing snapshot row in one transaction,
  rejects incomplete runs, and uses the existing database uniqueness contracts
  for retry-safe persistence.
- Run-scoped NEW/WORSENED/RECOVERED counts query only
  `RiskStatusHistory.inspection_run`; pending counts and current risk totals
  query actual current `Risk` rows and exclude terminal statuses.
- Code/AI cases and claim rates consume only completed persisted item runs;
  invalid data is excluded from valid case/coverage numerators while remaining
  in completed-run denominators as required.
- Asset coverage reads only persisted Task 6 `asset_scope` JSON and does not
  regenerate datasets or scenarios. No API, Airflow, UI, or trend comparison
  was added.

## Concerns

- `summary` remains `{}` because the task defines the persisted metric columns,
  while dashboard/API summary projection is explicitly out of scope.
- `assets_total` is the current persisted asset count for the run's
  environment; `assets_covered` is the distinct union of completed item-run
  scope keys.

## Fix Round 1

### RED

Regression tests were added before the production changes. The first focused
run reported the intended missing behaviors:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_daily_snapshot.py -q
....FFF.                                                                 [100%]
3 failed, 5 passed in 1.51s
```

The failures were: a different source run overwrote an existing date row, a
historical snapshot used later current Risk state, and a finished `PARTIAL`
run was rejected. The independent invalid `NO_AI`/`AI_ELIGIBLE` gate was
already green and remains explicitly covered.

A chronology regression then failed as expected when an older lifecycle event
was inserted after a newer event (`1 failed, 7 deselected`); this proved row ID
ordering was insufficient before the event-time fix.

### GREEN

The focused and full suites pass after the fix:

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest tests/domain/test_daily_snapshot.py -q
........                                                                 [100%]
8 passed in 1.41s

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m pytest -q
........................................................................ [ 78%]
....................                                                     [100%]
92 passed in 2.98s
```

### Fixes verified

- A snapshot date owned by another `InspectionRun` now raises a conflict
  before aggregation or writes; same-run retries still lock and refresh the
  existing row.
- Risk totals, P1/P2, and pending-action/pending-reverify metrics rebuild each
  Risk's status and severity from persisted `RiskStatusHistory` and
  `RiskObservation` events whose linked run finish time (or persisted event
  timestamp when unlinked) is at or before `InspectionRun.finished_at`.
  Later-only Risks and later transitions therefore do not leak into a retried
  historical snapshot. Event time, not database primary-key order, controls
  the latest state.
- Completed aggregate runs are `SUCCEEDED`, `PARTIAL`, or `FAILED` when they
  have `finished_at`; accepting terminal `FAILED` runs is the documented
  business choice for preserving a completed historical boundary.
- Completed item runs include terminal `SUCCEEDED` and `FAILED` rows with
  `finished_at`. They contribute to `inspection_item_count`, deterministic
  deflection, and data-completeness denominators. Valid claim/case numerators
  require `SUCCEEDED` plus `summary["data_valid"] is True`; invalid
  `NO_AI`/`AI_ELIGIBLE` rows are neither case.

### Fix Round 1 verification

```text
DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py makemigrations --check --dry-run
No changes detected

DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/python manage.py check
System check identified no issues (0 silenced).

/Users/lars.li/Documents/AI-inspect/.venv-web/bin/python -m compileall -q apps/inspections/services tests/domain/test_daily_snapshot.py
git diff --check
```

### Fix Round 1 self-review and concerns

- The source-run/date conflict is checked while the existing snapshot row is
  locked, so the original source reference cannot be silently replaced.
- Historical lifecycle reconstruction remains scoped to the run's
  environment and excludes terminal effective states; rows without any
  persisted pre-boundary lifecycle event fall back to their stored Risk state
  only when their `first_seen_at` is already at or before the boundary.
- No model, migration, API, Airflow, UI, or trend code was added.
