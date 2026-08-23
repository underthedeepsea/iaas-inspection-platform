"""Airflow-only HTTP orchestration for the daily inspection pipeline."""

from datetime import datetime, timedelta
import os

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
ENVIRONMENT_ID = os.getenv("INSPECTION_ENVIRONMENT_ID", "")


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
    return _post(
        "datasets/",
        {
            "environment_id": ENVIRONMENT_ID,
            "dataset_date": _date(context),
            "seed": DEFAULT_SEED,
            "scenario": DEFAULT_SCENARIO,
        },
    )


def create_run_task(**context):
    dataset = context["ti"].xcom_pull(task_ids="generate_dataset")
    return _post(
        "inspection-runs/",
        {
            "dataset_id": dataset["dataset_id"],
            "environment_id": ENVIRONMENT_ID,
            "run_date": _date(context),
            "dag_run_id": context["run_id"],
        },
    )


def execute_inspections_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    return _post(f"inspection-runs/{run['inspection_run_id']}/execute/", {})


def correlate_risks_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    return _post(f"inspection-runs/{run['inspection_run_id']}/correlate-risks/", {})


def reverify_pending_risks_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    return _post(f"inspection-runs/{run['inspection_run_id']}/reverify/", {})


def build_snapshot_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    return _post(f"inspection-runs/{run['inspection_run_id']}/snapshot/", {})


def complete_run_task(**context):
    run = context["ti"].xcom_pull(task_ids="create_run")
    return _post(f"inspection-runs/{run['inspection_run_id']}/complete/", {})


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
    reverify_pending_risks >> build_snapshot >> complete_run
