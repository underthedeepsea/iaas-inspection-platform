"""Airflow-only HTTP orchestration for the daily inspection pipeline."""

from datetime import datetime, timedelta
import os
import uuid

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator


DAG_ID = "daily_iaas_inspection"
SCHEDULE = os.getenv("INSPECTION_DAG_SCHEDULE", "0 7 * * *")
API_BASE_URL = os.getenv("INSPECTION_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_TOKEN = os.getenv("AIRFLOW_INTERNAL_TOKEN", "")
HTTP_TIMEOUT_SECONDS = float(os.getenv("INSPECTION_HTTP_TIMEOUT_SECONDS", "30"))
DEFAULT_SEED = os.getenv("MOCK_DEFAULT_SEED", "20260823")
DEFAULT_SCENARIO = os.getenv("MOCK_DEFAULT_SCENARIO", "llm_scheduler_pressure")


def _configured_environment_id():
    value = os.getenv("INSPECTION_ENVIRONMENT_ID", "").strip()
    if not value:
        raise RuntimeError(
            "INSPECTION_ENVIRONMENT_ID must be configured as a valid UUID"
        )
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise RuntimeError(
            "INSPECTION_ENVIRONMENT_ID must be configured as a valid UUID"
        ) from None


# Fail at the Airflow DAG import boundary instead of posting an empty UUID.
ENVIRONMENT_ID = _configured_environment_id()


def _post(path, payload):
    response = requests.post(
        f"{API_BASE_URL}/api/internal/v1/batch/{path}",
        json=payload,
        headers={"X-Airflow-Token": INTERNAL_TOKEN},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _date(context):
    return context.get("ds") or context["execution_date"].date().isoformat()


def generate_dataset_task(**context):
    environment_id = _configured_environment_id()
    response = _post(
        "datasets/",
        {
            "environment_id": environment_id,
            "dataset_date": _date(context),
            "seed": DEFAULT_SEED,
            "scenario": DEFAULT_SCENARIO,
        },
    )
    return {"dataset_id": response["dataset_id"]}


def create_run_task(**context):
    environment_id = _configured_environment_id()
    dataset = context["ti"].xcom_pull(task_ids="generate_dataset")
    response = _post(
        "inspection-runs/",
        {
            "dataset_id": dataset["dataset_id"],
            "environment_id": environment_id,
            "run_date": _date(context),
            "dag_run_id": context["run_id"],
        },
    )
    return {"inspection_run_id": response["inspection_run_id"]}


def execute_inspections_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    _post(f"inspection-runs/{run['inspection_run_id']}/execute/", {})
    return None


def correlate_risks_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    _post(f"inspection-runs/{run['inspection_run_id']}/correlate-risks/", {})
    return None


def reverify_pending_risks_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    _post(f"inspection-runs/{run['inspection_run_id']}/reverify/", {})
    return None


def build_resource_summaries_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    _post(f"inspection-runs/{run['inspection_run_id']}/resource-summaries/", {})
    return None


def build_snapshot_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    _post(f"inspection-runs/{run['inspection_run_id']}/snapshot/", {})
    return None


def complete_run_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    _post(f"inspection-runs/{run['inspection_run_id']}/complete/", {})
    return None


with DAG(
    dag_id=DAG_ID,
    schedule_interval=SCHEDULE,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
    },
    tags=["iaas", "inspection"],
) as dag:
    generate_dataset = PythonOperator(
        task_id="generate_dataset",
        python_callable=generate_dataset_task,
        provide_context=True,
    )
    create_run = PythonOperator(
        task_id="create_run",
        python_callable=create_run_task,
        provide_context=True,
    )
    execute_inspections = PythonOperator(
        task_id="execute_inspections",
        python_callable=execute_inspections_task,
        provide_context=True,
    )
    correlate_risks = PythonOperator(
        task_id="correlate_risks",
        python_callable=correlate_risks_task,
        provide_context=True,
    )
    reverify_pending_risks = PythonOperator(
        task_id="reverify_pending_risks",
        python_callable=reverify_pending_risks_task,
        provide_context=True,
    )
    build_resource_summaries = PythonOperator(
        task_id="build_resource_summaries",
        python_callable=build_resource_summaries_task,
        provide_context=True,
    )
    build_snapshot = PythonOperator(
        task_id="build_snapshot",
        python_callable=build_snapshot_task,
        provide_context=True,
    )
    complete_run = PythonOperator(
        task_id="complete_run",
        python_callable=complete_run_task,
        provide_context=True,
    )

    generate_dataset >> create_run >> execute_inspections
    execute_inspections >> correlate_risks >> reverify_pending_risks
    reverify_pending_risks >> build_resource_summaries >> build_snapshot >> complete_run
