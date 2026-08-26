"""Local background worker for resource investigations."""

from concurrent.futures import ThreadPoolExecutor
import logging

from django.db import close_old_connections


logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="resource-ai")


def enqueue_resource_investigation(investigation_id, context):
    future = _EXECUTOR.submit(
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
