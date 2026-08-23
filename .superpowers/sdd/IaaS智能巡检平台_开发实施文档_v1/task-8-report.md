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
