from django.db import transaction

from apps.inspections.models import InspectionRun, InspectionRunEvent


RUN_EVENT_TYPES = (
    "scope.resolved",
    "assets.discovered",
    "inspection.item.started",
    "inspection.item.progress",
    "inspection.item.completed",
    "risk.correlation.started",
    "risk.correlation.completed",
    "ai.admission.completed",
    "summary.completed",
    "run.completed",
    "run.failed",
)


@transaction.atomic
def append_run_event(inspection_run, event_type, status="INFO", payload=None):
    if event_type not in RUN_EVENT_TYPES:
        raise ValueError(f"unsupported inspection run event type: {event_type}")
    run_id = inspection_run.pk if isinstance(inspection_run, InspectionRun) else inspection_run
    run = InspectionRun.objects.select_for_update().get(pk=run_id)
    last_sequence = (
        InspectionRunEvent.objects.filter(inspection_run=run)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
        or 0
    )
    return InspectionRunEvent.objects.create(
        inspection_run=run,
        sequence=last_sequence + 1,
        event_type=event_type,
        status=status,
        payload=payload or {},
    )


def get_run_events(inspection_run, *, after_sequence=0):
    run_id = inspection_run.pk if isinstance(inspection_run, InspectionRun) else inspection_run
    return InspectionRunEvent.objects.filter(
        inspection_run_id=run_id,
        sequence__gt=after_sequence,
    ).order_by("sequence", "pk")


__all__ = ["RUN_EVENT_TYPES", "append_run_event", "get_run_events"]
