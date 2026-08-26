"""Small local worker used when no external queue is configured."""

from concurrent.futures import ThreadPoolExecutor
import logging

from django.db import close_old_connections


logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="inspection-run")


def enqueue_manual_inspection(run_id):
    """Queue a manual run after its transaction commits.

    Deployments can replace this function with an Airflow/Celery adapter.  A
    bounded in-process worker keeps the local web environment asynchronous and
    exercises the same orchestrator used by production adapters.
    """

    future = _EXECUTOR.submit(_run_manual_inspection, str(run_id))
    return {"run_id": str(run_id), "future": future}


def _run_manual_inspection(run_id):
    close_old_connections()
    try:
        from apps.inspections.services.manual_orchestrator import start_manual_inspection_run

        start_manual_inspection_run(run_id)
    except Exception:
        logger.exception("queued manual inspection failed", extra={"run_id": run_id})
    finally:
        close_old_connections()


__all__ = ["enqueue_manual_inspection"]
