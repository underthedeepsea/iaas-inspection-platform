"""In-process task dispatch for development only."""

from concurrent.futures import ThreadPoolExecutor
import logging

from django.conf import settings
from django.db import close_old_connections


logger = logging.getLogger(__name__)


class LocalTaskDispatcher:
    def __init__(self):
        self._executor = None

    def _get_executor(self):
        if not getattr(settings, "LOCAL_BACKGROUND_WORKER_ENABLED", False):
            raise RuntimeError(
                "durable worker adapter is required when local background worker is disabled"
            )
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="background-task",
            )
        return self._executor

    def enqueue_manual_inspection(self, run_id: str) -> dict:
        run_id = str(run_id)
        future = self._get_executor().submit(_run_manual_inspection, run_id)
        return {"run_id": run_id, "future": future}

    def enqueue_resource_investigation(
        self,
        investigation_id: str,
        context: dict,
    ) -> dict:
        investigation_id = str(investigation_id)
        future = self._get_executor().submit(
            _run_resource_investigation,
            investigation_id,
            dict(context or {}),
        )
        return {"investigation_id": investigation_id, "future": future}


def _run_manual_inspection(run_id):
    close_old_connections()
    try:
        from apps.inspections.services.manual_orchestrator import (
            start_manual_inspection_run,
        )

        start_manual_inspection_run(run_id)
    except Exception:
        logger.exception("queued manual inspection failed", extra={"run_id": run_id})
    finally:
        close_old_connections()


def _run_resource_investigation(investigation_id, context):
    close_old_connections()
    try:
        from apps.investigations.models import Investigation
        from apps.investigations.services.runtime import run_resource_investigation

        investigation = Investigation.objects.get(pk=investigation_id)
        run_resource_investigation(investigation, context)
    except Exception:
        logger.exception(
            "queued resource investigation failed",
            extra={"investigation_id": investigation_id},
        )
    finally:
        close_old_connections()
