"""Airflow entrypoint for an existing manual inspection run."""

from datetime import datetime, timedelta
import os

from airflow import DAG
from airflow.operators.python import PythonOperator


DAG_ID = os.environ["AIRFLOW_MANUAL_INSPECTION_DAG_ID"]


def run_manual_inspection(**context):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from apps.inspections.services.manual_orchestrator import (
        start_manual_inspection_run,
    )

    start_manual_inspection_run(context["dag_run"].conf["run_id"])


with DAG(
    dag_id=DAG_ID,
    schedule_interval=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1)},
    tags=["iaas", "manual-inspection"],
) as dag:
    run = PythonOperator(
        task_id="run_manual_inspection",
        python_callable=run_manual_inspection,
        provide_context=True,
    )
