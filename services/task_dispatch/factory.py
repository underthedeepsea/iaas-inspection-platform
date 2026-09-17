from django.conf import settings

from .airflow import AirflowTaskDispatcher
from .local import LocalTaskDispatcher


_local_dispatcher = LocalTaskDispatcher()


def get_task_dispatcher():
    provider = settings.BACKGROUND_TASK_PROVIDER.lower()
    if provider == "local":
        return _local_dispatcher
    if provider == "airflow":
        return AirflowTaskDispatcher()
    raise ValueError(f"unsupported background task provider: {provider}")
