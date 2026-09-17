"""Airflow entrypoint for an existing resource investigation."""

from datetime import datetime, timedelta
import os

from airflow import DAG
from airflow.operators.python import PythonOperator


DAG_ID = os.environ["AIRFLOW_RESOURCE_INVESTIGATION_DAG_ID"]


def run_investigation(**context):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    import django

    django.setup()
    from apps.investigations.models import Investigation
    from apps.investigations.services.runtime import run_resource_investigation

    conf = context["dag_run"].conf
    investigation = Investigation.objects.get(pk=conf["investigation_id"])
    run_resource_investigation(investigation, conf["context"])


with DAG(
    dag_id=DAG_ID,
    schedule_interval=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1)},
    tags=["iaas", "resource-investigation"],
) as dag:
    run = PythonOperator(
        task_id="run_resource_investigation",
        python_callable=run_investigation,
        provide_context=True,
    )
