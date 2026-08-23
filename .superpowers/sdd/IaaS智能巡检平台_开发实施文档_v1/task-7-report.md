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
