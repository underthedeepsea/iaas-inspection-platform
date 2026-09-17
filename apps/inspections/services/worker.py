"""Manual-inspection dispatch boundary."""

from services.task_dispatch.factory import get_task_dispatcher


def enqueue_manual_inspection(run_id):
    return get_task_dispatcher().enqueue_manual_inspection(str(run_id))


__all__ = ["enqueue_manual_inspection"]
