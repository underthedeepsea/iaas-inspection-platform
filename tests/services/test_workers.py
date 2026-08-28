import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(LOCAL_BACKGROUND_WORKER_ENABLED=False)
def test_manual_worker_fails_closed_when_local_executor_is_disabled():
    from apps.inspections.services.worker import enqueue_manual_inspection

    with pytest.raises(RuntimeError, match="durable worker"):
        enqueue_manual_inspection("run-1")


@pytest.mark.django_db
@override_settings(LOCAL_BACKGROUND_WORKER_ENABLED=False)
def test_resource_worker_fails_closed_when_local_executor_is_disabled():
    from apps.investigations.services.worker import enqueue_resource_investigation

    with pytest.raises(RuntimeError, match="durable worker"):
        enqueue_resource_investigation("investigation-1", {})
