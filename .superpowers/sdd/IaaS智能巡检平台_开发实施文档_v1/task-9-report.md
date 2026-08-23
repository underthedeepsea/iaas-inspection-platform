# Task 9 report: Airflow 2.3.2 DAG and internal batch API

## Status

DONE — fix round 1 implementation and verification completed. The final commit hardens the authenticated internal batch API, preserves the HTTP-only Airflow DAG, and keeps terminal run finalization in `complete` only.

## RED / GREEN evidence

### RED

- The first focused run failed as expected because the routes and DAG file did not yet exist: the API requests returned `404`, and the DAG structure tests raised `FileNotFoundError`.
- After adding the transaction-isolated retry regression, the first run exposed a genuine live-service-only defect: snapshot used `select_for_update()` outside a request transaction and returned `500` (`TransactionManagementError`). The snapshot view was changed to perform the initial lookup without a lock and acquire the lock inside `transaction.atomic()`.

### GREEN

- Focused API and DAG tests: `5 passed`.
- Full web suite: `97 passed in 3.46s`.
- Django checks: `manage.py check` reported no issues.
- Migration consistency: `manage.py migrate --check` passed with no pending migrations.
- Python compilation, DAG AST syntax, and `git diff --check` passed.

## Fix Round 1 (2026-08-24)

### RED

- The new DAG regressions initially failed because the source still lacked the explicit `INSPECTION_ENVIRONMENT_ID` validation and non-producing callables still returned `_post(...)` responses.
- The first database-backed run of the new stage-order test exposed an incorrect test expectation: `reverify`, `snapshot`, and `complete` correctly reported their immediate predecessor (`correlate_risks`, `reverify`, and `snapshot`) rather than all reporting `execute`. The regression now asserts the exact predecessor for each endpoint.
- A sandboxed PostgreSQL attempt failed with `Operation not permitted`; the same bounded suite passed after the required database permission was granted.

### GREEN

- Focused API, Task 7, Task 8, and DAG suite: `43 passed in 4.01s`.
- Full Web suite after the fix round: `105 passed in 4.95s`.
- `manage.py check`: `System check identified no issues (0 silenced).`
- `manage.py migrate --check`: passed with no pending migrations.
- Airflow import-isolation/config test: direct Airflow 2.3.2 import without the variable fails with the exact error `RuntimeError: INSPECTION_ENVIRONMENT_ID must be configured as a valid UUID`.

The API now records stage markers only after successful work and enforces the exact marker chain `execute -> correlate_risks -> reverify -> snapshot -> complete`. Out-of-order requests return structured `409 invalid_stage_order` with `required_stage` and do not create markers, item runs, observations, or snapshots. `reverify` and `snapshot` use explicit nonterminal `allow_nonterminal=True` plus an aware `as_of` boundary; they do not write run terminal status, `finished_at`, or final totals. A snapshot failure rolls back its service transaction and leaves the run `RUNNING` with no snapshot marker. `_finish_run` is called only by `complete`.

The `dag_run_id` create path uses an inner savepoint. A mocked unique-key `IntegrityError` now becomes structured `409 dag_run_conflict` without leaving the outer transaction broken; the regression proves a follow-up query still works. The DAG validates the required UUID at import and task execution boundaries, returns only dataset/run IDs from producing tasks, and returns `None` from all non-producing tasks.

## Internal endpoint contract and idempotency

All seven POST stages are mounted below `/api/internal/v1/batch/` and are guarded before body parsing by exact `secrets.compare_digest` matching against `AIRFLOW_INTERNAL_TOKEN`. Missing, empty, or misconfigured secrets fail closed with structured `403`; malformed JSON with no token is never parsed and creates no rows.

- `datasets/`: canonical key is environment/date/seed/scenario; same input returns the existing `MockDataset`. A supplied dataset ID is checked against all immutable fields.
- `inspection-runs/`: `dag_run_id` is the idempotency key; environment, dataset, and date conflicts return `409`.
- `inspection-runs/{id}/execute/`: delegates to `execute_inspection_run`; the stage marker and model uniqueness preserve item runs/findings across retries.
- `inspection-runs/{id}/correlate-risks/`: delegates to `correlate_run`; existing risk observations are reused and histories are not duplicated.
- `inspection-runs/{id}/reverify/`: delegates to `reverify_pending_risks` with the opt-in nonterminal/as-of boundary needed by the binding DAG order; the stage marker prevents repeat lifecycle writes and no terminal run fields are changed.
- `inspection-runs/{id}/snapshot/`: delegates to `build_daily_snapshot` with the opt-in nonterminal/as-of boundary; environment/date uniqueness and the existing service conflict guard prevent duplicate or retargeted snapshots, and a failed snapshot leaves the run nonterminal.
- `inspection-runs/{id}/complete/`: reconciles totals/status and is safe to repeat without lifecycle side effects.

Stage calls accept optional immutable context fields and reject mismatches with structured `409` responses. Unexpected failures are returned as structured `500` JSON errors.

## DAG and CLI evidence

`airflow/dags/daily_iaas_inspection.py` imports only Airflow, `requests`, standard-library modules, and environment configuration. It passes only IDs/small JSON state through XCom and uses an explicit HTTP timeout.

The parsed DAG has the exact edges:

```text
generate_dataset
  -> create_run
  -> execute_inspections
  -> correlate_risks
  -> reverify_pending_risks
  -> build_snapshot
  -> complete_run
```

Airflow parse evidence (`.venv-airflow`, Airflow `2.3.2`, project-local `AIRFLOW_HOME`): `airflow dags list --subdir airflow/dags/daily_iaas_inspection.py` listed `daily_iaas_inspection` successfully. Importing the same file without `INSPECTION_ENVIRONMENT_ID` fails before DAG construction with the explicit UUID configuration error.

Genuine end-to-end CLI evidence used a project-local temporary `AIRFLOW_HOME`, a running Django service on `127.0.0.1:8000`, and the running PostgreSQL database:

```text
airflow dags test daily_iaas_inspection 2026-08-21 --subdir airflow/dags/daily_iaas_inspection.py
```

The final bounded run used a watchdog-managed Django server (maximum 75 seconds) and `airflow dags test daily_iaas_inspection 2026-08-21 --subdir airflow/dags/daily_iaas_inspection.py`. The exact Airflow task-state CLI evidence for run `backfill__2026-08-21T00:00:00+00:00` was:

```text
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | generate_dataset       | success
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | create_run             | success
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | execute_inspections    | success
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | correlate_risks        | success
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | reverify_pending_risks | success
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | build_snapshot         | success
daily_iaas_inspection | 2026-08-21T00:00:00+00:00 | complete_run           | success
```

PostgreSQL read-only evidence for that run was:

```text
run 197df13b-b240-4034-8c88-791fa72f3ea1 SUCCEEDED 2026-08-23 18:35:13.860664+00:00
stages {'execute': True, 'complete': True, 'reverify': True, 'snapshot': True, 'correlate_risks': True}
dataset d9a9540d-a4de-48cc-94c1-a606ee5caf63 READY llm_scheduler_pressure
snapshot 1bc8fc10-9353-49af-8e6c-9e3eb53f57ce -> 197df13b-b240-4034-8c88-791fa72f3ea1
```

The first bounded exploratory date (`2026-08-24`) produced Airflow's exact `BackfillJob is deadlocked` because it was future relative to the current UTC time; a second exploratory attempt correctly produced `403 Client Error: Forbidden` when the Django child intentionally lacked the token. Both processes were stopped by the watchdog and created no successful run. The final `2026-08-21` run used the shared token and completed all seven tasks.

## Files

- `airflow/dags/daily_iaas_inspection.py`
- `apps/inspections/api_internal.py`
- `apps/inspections/services/snapshot.py`
- `apps/risks/services/reverify.py`
- `.env.example`
- `apps/inspections/internal_urls.py`
- `config/urls.py`
- `tests/api/test_internal_batch_api.py`
- `tests/integration/test_airflow_dag_structure.py`
- `tests/domain/test_daily_snapshot.py`
- `tests/domain/test_risk_lifecycle.py`

## Self-review

- Authentication is the first operation in every endpoint wrapper; no request body parsing or database write occurs before the token check.
- Dataset/environment and run/environment locks serialize same-key retries; run row locking serializes stage retries.
- Task 4–8 generator, execution, correlation, reverification, and snapshot services are reused rather than duplicated; only the minimal nonterminal/as-of opt-in was added to Task 7/8 services.
- The DAG has no Django/app/service imports and does not embed mock data in XCom.
- No model changes or migrations were needed.
- The focused transaction-isolated test specifically covers the autocommit mode used by the live Django service.

## Concerns

- Airflow 2.3.2's `dags test` command uses backfill scheduling semantics: future dates deadlock, so the final evidence uses the past date `2026-08-21`.
- The E2E evidence uses the running local PostgreSQL database and creates the isolated environment/date resources listed above; no model or migration changes were needed.

## Fix Round 2 (2026-08-24)

### RED / GREEN

- Direct-service regressions first failed as intended: six new cases showed that `allow_nonterminal=True` accepted `PENDING`, incomplete `RUNNING`, and implicit `as_of` calls.
- After the guard implementation, the focused API/Task7/Task8 suite passed: `44 passed in 3.46s`.
- The full Web suite passed: `111 passed in 4.92s`.
- Django `check` reported no issues and `migrate --check` passed with no pending migrations.
- Airflow 2.3.2 bounded parse with project-local `AIRFLOW_HOME` listed `daily_iaas_inspection` successfully.

The nonterminal service opt-in now requires `status=RUNNING`, `finished_at=NULL`, an explicit timezone-aware `as_of`, `started_at`, terminal persisted item runs whose counts match the run aggregate, and no item completion after `as_of`. Reverification additionally requires the persisted `correlate_risks` stage marker. These checks run before snapshot creation, risk locking, correlation, or risk lifecycle writes. The existing API marker chain remains defense in depth, and the valid API nonterminal path remains covered by the idempotent batch API test.
