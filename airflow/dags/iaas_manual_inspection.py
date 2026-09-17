"""Airflow orchestrates manual batches only through the internal HTTP API."""
from datetime import datetime, timedelta
import os
import uuid

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator


DAG_ID = os.getenv('AIRFLOW_MANUAL_INSPECTION_DAG_ID', 'iaas_manual_inspection')
API_BASE_URL = os.getenv('INSPECTION_API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
INTERNAL_TOKEN = os.getenv('AIRFLOW_INTERNAL_TOKEN', '')
HTTP_TIMEOUT_SECONDS = float(os.getenv('INSPECTION_HTTP_TIMEOUT_SECONDS', '30'))
STAGES = ('execute', 'correlate-risks', 'reverify', 'resource-summaries', 'snapshot', 'complete')


def run_manual_inspection(**context):
    run_id = str(uuid.UUID(str(context['dag_run'].conf['run_id'])))
    for stage in STAGES:
        response = requests.post(f'{API_BASE_URL}/api/internal/v1/batch/inspection-runs/{run_id}/{stage}/', json={}, headers={'X-Airflow-Token': INTERNAL_TOKEN}, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()


with DAG(dag_id=DAG_ID, schedule_interval=None, start_date=datetime(2026, 1, 1), catchup=False, default_args={'retries': 2, 'retry_delay': timedelta(minutes=1)}, tags=['iaas', 'manual-inspection']) as dag:
    run = PythonOperator(task_id='run_manual_inspection', python_callable=run_manual_inspection)
