# Task 9 report: Airflow 2.3.2 DAG and internal batch API

## Status

DONE_WITH_CONCERNS — implementation and verification completed. The final commit contains the authenticated internal batch API, the HTTP-only Airflow DAG, routing, and focused tests.

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

## Internal endpoint contract and idempotency

All seven POST stages are mounted below `/api/internal/v1/batch/` and are guarded before body parsing by exact `secrets.compare_digest` matching against `AIRFLOW_INTERNAL_TOKEN`. Missing, empty, or misconfigured secrets fail closed with structured `403`; malformed JSON with no token is never parsed and creates no rows.

- `datasets/`: canonical key is environment/date/seed/scenario; same input returns the existing `MockDataset`. A supplied dataset ID is checked against all immutable fields.
- `inspection-runs/`: `dag_run_id` is the idempotency key; environment, dataset, and date conflicts return `409`.
- `inspection-runs/{id}/execute/`: delegates to `execute_inspection_run`; the stage marker and model uniqueness preserve item runs/findings across retries.
- `inspection-runs/{id}/correlate-risks/`: delegates to `correlate_run`; existing risk observations are reused and histories are not duplicated.
- `inspection-runs/{id}/reverify/`: delegates to `reverify_pending_risks`; the stage marker prevents repeat lifecycle writes.
- `inspection-runs/{id}/snapshot/`: delegates to `build_daily_snapshot`; environment/date uniqueness and the existing service conflict guard prevent duplicate or retargeted snapshots.
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

Airflow parse evidence (`.venv-airflow`, Airflow `2.3.2`): `airflow dags list --subdir airflow/dags/daily_iaas_inspection.py` listed `daily_iaas_inspection` successfully.

Genuine end-to-end CLI evidence used a project-local temporary `AIRFLOW_HOME`, a running Django service on `127.0.0.1:8000`, and the running PostgreSQL database:

```text
airflow dags test daily_iaas_inspection 2026-08-23 --subdir airflow/dags/daily_iaas_inspection.py
```

The final fresh-home run completed all seven task instances with `success`: `generate_dataset`, `create_run`, `execute_inspections`, `correlate_risks`, `reverify_pending_risks`, `build_snapshot`, and `complete_run`. PostgreSQL confirmed `run_status='SUCCEEDED'`, `finished=True`, and exactly one dataset and one snapshot for the canonical environment/date. Earlier exploratory attempts were either a future execution date (Airflow deadlock) or an intentionally invalid scenario spelling; neither was used as the final evidence.

## Files

- `airflow/dags/daily_iaas_inspection.py`
- `apps/inspections/api_internal.py`
- `apps/inspections/internal_urls.py`
- `config/urls.py`
- `tests/api/test_internal_batch_api.py`
- `tests/integration/test_airflow_dag_structure.py`

## Self-review

- Authentication is the first operation in every endpoint wrapper; no request body parsing or database write occurs before the token check.
- Dataset/environment and run/environment locks serialize same-key retries; run row locking serializes stage retries.
- Task 4–8 generator, execution, correlation, reverification, and snapshot services are reused rather than duplicated.
- The DAG has no Django/app/service imports and does not embed mock data in XCom.
- No model changes or migrations were needed.
- The focused transaction-isolated test specifically covers the autocommit mode used by the live Django service.

## Concerns

- Task 8's snapshot and reverification services intentionally require a completed run, while the binding DAG order places those stages before `complete_run`. The internal `reverify`/`snapshot` stages therefore reconcile the run to its terminal aggregate state before delegating; the final `complete` stage remains an idempotent reconciliation. This preserves the required edge order and existing Task 8 service contract, but the ordering remains a design wrinkle for a future API revision.
- The end-to-end check applied the repository's unapplied migrations to the local inspection database and created one isolated local environment/dataset/run/snapshot for evidence.
