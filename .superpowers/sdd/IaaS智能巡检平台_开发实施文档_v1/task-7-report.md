# Task 7 report: risk lifecycle, fingerprint, and automatic reverification

## RED / GREEN

- RED: `DJANGO_SETTINGS_MODULE=config.settings.dev /Users/lars.li/Documents/AI-inspect/.venv-web/bin/pytest -q tests/domain/test_risk_lifecycle.py` — 6 failures, each because the requested `apps.risks.services` package did not exist yet.
- GREEN: focused suite — `6 passed`.
- Full suite — `68 passed`.

## Transition evidence

- The same canonical Environment slug, InspectionItem code, finding code, and affected asset external key reuse one UUID Risk across two dates.
- Correlation persists two RiskObservation rows and two RiskStatusHistory rows, and updates `InspectionRun.risk_count` from active correlated Risk rows.
- P3 to P1 changes the risk to `WORSENED` and records the triggering run and reason.
- `mark_handled()` changes an active risk only to `PENDING_REVERIFY`; it does not create `RECOVERED`.
- A later valid successful same-item run without the active Finding creates a `detected=False` observation and moves the risk to `RECOVERED`.
- A later valid successful same-item run with the Finding remains active and moves the risk to `PERSISTING` or `WORSENED` by severity.
- Failed, partial, invalid, or unexecuted evidence does not recover a pending risk.

## Files

- `apps/risks/services/correlation.py`
- `apps/risks/services/lifecycle.py`
- `apps/risks/services/reverify.py`
- `apps/risks/services/__init__.py`
- `apps/risks/models.py`
- `apps/risks/migrations/0002_risk_lifecycle_statuses.py`
- `tests/domain/test_risk_lifecycle.py`

## Commands and results

- `DJANGO_SETTINGS_MODULE=config.settings.dev .../pytest -q tests/domain/test_risk_lifecycle.py` — `6 passed`.
- `DJANGO_SETTINGS_MODULE=config.settings.dev .../pytest -q` — `68 passed`.
- `DJANGO_SETTINGS_MODULE=config.settings.dev .../python manage.py makemigrations --check --dry-run --verbosity 1` — `No changes detected`.
- `DJANGO_SETTINGS_MODULE=config.settings.dev .../python manage.py check` — `System check identified no issues (0 silenced)`.
- `.../python -m compileall -q apps/risks tests/domain/test_risk_lifecycle.py` — passed.
- `git diff --check` — passed.

## Self-review

- Correlation and recovery paths use `transaction.atomic()`; existing Risk rows are fetched with `select_for_update()`.
- Repeated correlation of the same run does not increment occurrence counts or duplicate observations/history.
- Fingerprints never use database IDs and the environment/fingerprint uniqueness constraint remains enforced.
- No API, snapshot generation, Airflow, LLM, or action execution code was added.

## Concerns

- Invalid or incomplete evidence intentionally leaves a risk in `PENDING_REVERIFY` for a later valid item run; it is not treated as recovery evidence.

## Fix Round 1 evidence

### RED / GREEN

- RED: after adding regression coverage, the focused suite reported `9 failed, 10 passed`; failures covered the missing recovery guard, canonical fingerprint helpers, strict evidence gates, unknown severity rejection, and absent migration mapping.
- GREEN: focused suite — `19 passed`.
- Full suite — `81 passed`.

### Fixes verified

- `transition_risk(..., RECOVERED, ...)` now rejects public recovery; only the verified reverify transaction writes the recovery observation and history.
- Reverification requires aggregate `SUCCEEDED` plus `finished_at`, item-run `SUCCEEDED` plus `finished_at`, and `summary["data_valid"] is True`; missing, false, partial, failed, or unexecuted evidence is rejected.
- Candidate completion must be later than the latest `PENDING_REVERIFY` history timestamp, including same-day runs.
- Fingerprints hash only typed environment/item/finding strings and persisted `Asset.external_key`, with an explicit environment-level sentinel when no asset exists; finding value dictionaries and ORM IDs are ignored.
- `risk_count` counts distinct detected Risk observations for the current run, excluding unrelated active environment risks.
- Reverification locks the aggregate run and all candidate-item risks before correlation and reevaluates pending status inside the same transaction, preventing concurrent handling from stranding a matching finding.
- Migration `0002` maps legacy statuses (`ACTIVE→PERSISTING`, `ACKNOWLEDGED→INVESTIGATING`, `MITIGATING→IN_PROGRESS`, `CLOSED→RECOVERED`, `INVALID→FALSE_POSITIVE`) before narrowing choices.
- Tests cover idempotent correlation, exact observations/history/reasons/runs, both failed-reverify statuses, invalid evidence variants, pre-handle timestamps, canonical identity, and severity order/unknown rejection.

### Fix Round 1 commands and results

- `DJANGO_SETTINGS_MODULE=config.settings.dev .../pytest -q tests/domain/test_risk_lifecycle.py` — `19 passed`.
- `DJANGO_SETTINGS_MODULE=config.settings.dev .../pytest -q` — `81 passed`.
- `DJANGO_SETTINGS_MODULE=config.settings.dev .../python manage.py makemigrations --check --dry-run --verbosity 1` — `No changes detected`.
- `DJANGO_SETTINGS_MODULE=config.settings.dev .../python manage.py check` — `System check identified no issues (0 silenced)`.
