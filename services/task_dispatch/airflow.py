"""Durable task dispatch through the Airflow REST API."""

import httpx
from django.conf import settings


class AirflowTaskDispatcher:
    def enqueue_manual_inspection(self, run_id: str) -> dict:
        return self._post(
            settings.AIRFLOW_MANUAL_INSPECTION_DAG_ID,
            {"run_id": str(run_id)},
        )

    def enqueue_resource_investigation(
        self,
        investigation_id: str,
        context: dict,
    ) -> dict:
        return self._post(
            settings.AIRFLOW_RESOURCE_INVESTIGATION_DAG_ID,
            {
                "investigation_id": str(investigation_id),
                "context": dict(context or {}),
            },
        )

    @staticmethod
    def _post(dag_id: str, conf: dict) -> dict:
        response = httpx.post(
            f"{settings.AIRFLOW_BASE_URL.rstrip('/')}/api/v1/dags/{dag_id}/dagRuns",
            json={"conf": conf},
            auth=(settings.AIRFLOW_USERNAME, settings.AIRFLOW_PASSWORD),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
