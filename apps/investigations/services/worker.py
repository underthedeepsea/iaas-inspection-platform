"""Resource-investigation dispatch boundary."""

from services.task_dispatch.factory import get_task_dispatcher


def enqueue_resource_investigation(investigation_id, context):
    return get_task_dispatcher().enqueue_resource_investigation(
        str(investigation_id),
        dict(context or {}),
    )


__all__ = ["enqueue_resource_investigation"]
