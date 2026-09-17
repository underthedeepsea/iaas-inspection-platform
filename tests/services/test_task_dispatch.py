from unittest.mock import Mock

from django.test import override_settings


@override_settings(
    AIRFLOW_BASE_URL="https://airflow.example/",
    AIRFLOW_USERNAME="airflow-user",
    AIRFLOW_PASSWORD="airflow-pass",
    AIRFLOW_MANUAL_INSPECTION_DAG_ID="manual-inspection",
    AIRFLOW_RESOURCE_INVESTIGATION_DAG_ID="resource-investigation",
)
def test_airflow_dispatcher_posts_exact_manual_inspection_payload(monkeypatch):
    from services.task_dispatch.airflow import AirflowTaskDispatcher

    response = Mock()
    post = Mock(return_value=response)
    monkeypatch.setattr("services.task_dispatch.airflow.httpx.post", post)

    result = AirflowTaskDispatcher().enqueue_manual_inspection("run-1")

    post.assert_called_once_with(
        "https://airflow.example/api/v1/dags/manual-inspection/dagRuns",
        json={"conf": {"run_id": "run-1"}},
        auth=("airflow-user", "airflow-pass"),
        timeout=10.0,
    )
    response.raise_for_status.assert_called_once_with()
    assert result is response.json.return_value


@override_settings(
    AIRFLOW_BASE_URL="https://airflow.example",
    AIRFLOW_USERNAME="airflow-user",
    AIRFLOW_PASSWORD="airflow-pass",
    AIRFLOW_MANUAL_INSPECTION_DAG_ID="manual-inspection",
    AIRFLOW_RESOURCE_INVESTIGATION_DAG_ID="resource-investigation",
)
def test_airflow_dispatcher_posts_exact_resource_investigation_payload(monkeypatch):
    from services.task_dispatch.airflow import AirflowTaskDispatcher

    response = Mock()
    post = Mock(return_value=response)
    monkeypatch.setattr("services.task_dispatch.airflow.httpx.post", post)
    context = {"resource_type": "host", "filters": {"status": "warning"}}

    AirflowTaskDispatcher().enqueue_resource_investigation("investigation-1", context)

    post.assert_called_once_with(
        "https://airflow.example/api/v1/dags/resource-investigation/dagRuns",
        json={
            "conf": {
                "investigation_id": "investigation-1",
                "context": context,
            }
        },
        auth=("airflow-user", "airflow-pass"),
        timeout=10.0,
    )
    response.raise_for_status.assert_called_once_with()


@override_settings(BACKGROUND_TASK_PROVIDER="airflow")
def test_factory_selects_airflow_for_production_provider():
    from services.task_dispatch.airflow import AirflowTaskDispatcher
    from services.task_dispatch.factory import get_task_dispatcher

    assert isinstance(get_task_dispatcher(), AirflowTaskDispatcher)


@override_settings(BACKGROUND_TASK_PROVIDER="local")
def test_factory_selects_local_for_development_provider():
    from services.task_dispatch.factory import get_task_dispatcher
    from services.task_dispatch.local import LocalTaskDispatcher

    assert isinstance(get_task_dispatcher(), LocalTaskDispatcher)
