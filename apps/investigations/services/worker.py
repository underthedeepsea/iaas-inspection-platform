"""Local background worker for resource investigations."""

import logging

from django.conf import settings
from django.db import close_old_connections


logger = logging.getLogger(__name__)
_EXECUTOR = None


def _executor():
    global _EXECUTOR
    if not getattr(settings, "LOCAL_BACKGROUND_WORKER_ENABLED", False):
        raise RuntimeError("durable worker adapter is required when local background worker is disabled")
    if _EXECUTOR is None:
        from concurrent.futures import ThreadPoolExecutor

        _EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="resource-ai")
    return _EXECUTOR


def enqueue_resource_investigation(investigation_id, context):
    future = _executor().submit(
        _run_resource_investigation,
        str(investigation_id),
        dict(context or {}),
    )
    return {"investigation_id": str(investigation_id), "future": future}


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


__all__ = ["enqueue_resource_investigation"]
