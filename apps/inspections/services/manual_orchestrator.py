"""Application service for running a manual inspection end to end.

The public trigger creates the immutable run input and hands the run to this
orchestrator.  Keeping the stage sequence here means the HTTP boundary does
not need to know about internal batch endpoints or ask callers to supply a
dataset by hand.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.inspections.models import (
    DailySnapshot,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
    InspectionRunEvent,
    ResourceInspectionSummary,
)
from apps.inspections.services.events import append_run_event
from apps.inspections.services.execution import execute_inspection_run
from apps.inspections.services.resource_summary import build_resource_summaries
from apps.inspections.services.snapshot import build_daily_snapshot
from apps.risks.services.correlation import correlate_run
from apps.risks.services.reverify import reverify_pending_risks


logger = logging.getLogger(__name__)

STAGE_ORDER = (
    "execute",
    "correlate_risks",
    "reverify",
    "ai_admission",
    "resource_summaries",
    "snapshot",
    "complete",
)


def start_manual_inspection_run(run_id):
    """Run every manual inspection stage in order and return the final run."""

    run = _claim_run(run_id)
    if run is None:
        return InspectionRun.objects.get(pk=run_id)
    try:
        _execute(run)
        _correlate(run)
        _reverify(run)
        _admit(run)
        _summarize(run)
        _snapshot(run)
        _complete(run)
    except Exception as error:
        _fail(run_id, error)
        raise
    return InspectionRun.objects.get(pk=run_id)


def _claim_run(run_id):
    with transaction.atomic():
        run = (
            InspectionRun.objects.select_for_update()
            .get(pk=run_id)
        )
        if run.status in {
            InspectionRun.Status.SUCCEEDED,
            InspectionRun.Status.PARTIAL,
            InspectionRun.Status.FAILED,
        } and run.finished_at is not None:
            return None
        if run.dataset_id is None:
            raise ValueError("manual inspection run must reference a mock dataset")
        snapshot = dict(run.config_snapshot or {})
        batch = dict(snapshot.get("batch") or {})
        # A claimed but unfinished run is resumable after a worker restart.
        # Each stage takes its own row lock and checks its durable completion
        # marker, so duplicate queue deliveries remain idempotent.
        batch["manual_orchestrator_claimed"] = True
        snapshot["batch"] = batch
        run.config_snapshot = snapshot
        run.status = InspectionRun.Status.RUNNING
        run.started_at = run.started_at or timezone.now()
        run.save(update_fields=["config_snapshot", "status", "started_at"])
        return run


def _execute(run):
    if _stage_done(run, "execute"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "execute"):
            return
        items = _items_for_run(run)
        append_run_event(
            run,
            "inspection.started",
            InspectionRun.Status.RUNNING,
            {"total_items": len(items)},
        )
        for item in items:
            append_run_event(
                run,
                "inspection.item.started",
                InspectionRun.Status.RUNNING,
                {"inspection_item_id": str(item.pk), "inspection_item_code": item.code},
            )
        execute_inspection_run(run, inspection_items=items)
        item_runs = list(
            InspectionItemRun.objects.filter(inspection_run=run).select_related("inspection_item")
        )
        total = len(item_runs)
        for position, item_run in enumerate(item_runs, start=1):
            event_status = (
                InspectionRun.Status.SUCCEEDED
                if item_run.status == InspectionItemRun.Status.SUCCEEDED
                else InspectionRun.Status.FAILED
            )
            append_run_event(
                run,
                "inspection.item.completed",
                event_status,
                {
                    "inspection_item_id": str(item_run.inspection_item_id),
                    "inspection_item_code": item_run.inspection_item.code,
                    "status": item_run.status,
                },
            )
            if item_run.status == InspectionItemRun.Status.FAILED:
                append_run_event(
                    run,
                    "inspection.item.failed",
                    InspectionRun.Status.FAILED,
                    {
                        "inspection_item_id": str(item_run.inspection_item_id),
                        "inspection_item_code": item_run.inspection_item.code,
                        "error_code": item_run.error_code,
                        "error_message": item_run.error_message,
                    },
                )
            append_run_event(
                run,
                "inspection.item.progress",
                InspectionRun.Status.RUNNING,
                {
                    "completed_items": position,
                    "total_items": total,
                    "completed_asset_count": len((item_run.asset_scope or {}).get("asset_ids") or []),
                },
            )
        failed = sum(item_run.status == InspectionItemRun.Status.FAILED for item_run in item_runs)
        append_run_event(
            run,
            "inspection.completed",
            InspectionRun.Status.PARTIAL if failed else InspectionRun.Status.SUCCEEDED,
            {
                "total_items": total,
                "success_items": total - failed,
                "failed_items": failed,
            },
        )
        _mark_stage(run, "execute")


def _correlate(run):
    if _stage_done(run, "correlate_risks"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "correlate_risks"):
            return
        append_run_event(run, "risk.correlation.started", InspectionRun.Status.RUNNING, {})
        correlate_run(run)
        append_run_event(run, "risk.correlation.completed", InspectionRun.Status.SUCCEEDED, {})
        _mark_stage(run, "correlate_risks")


def _reverify(run):
    if _stage_done(run, "reverify"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "reverify"):
            return
        reverify_pending_risks(run, allow_nonterminal=True, as_of=timezone.now())
        _mark_stage(run, "reverify")


def _admit(run):
    if _stage_done(run, "ai_admission"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "ai_admission"):
            return
        item_runs = list(
            InspectionItemRun.objects.filter(inspection_run=run)
            .select_related("inspection_item")
            .order_by("inspection_item__code", "pk")
        )
        append_run_event(run, "ai.admission.started", InspectionRun.Status.RUNNING, {})
        for item_run in item_runs:
            append_run_event(
                run,
                "ai.admission.completed",
                InspectionRun.Status.SUCCEEDED,
                {
                    "inspection_item_id": str(item_run.inspection_item_id),
                    "inspection_item_code": item_run.inspection_item.code,
                    "status": item_run.ai_admission_status,
                },
            )
        _mark_stage(run, "ai_admission")


def _summarize(run):
    if _stage_done(run, "resource_summaries"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "resource_summaries"):
            return
        append_run_event(run, "summary.started", InspectionRun.Status.RUNNING, {})
        summaries = build_resource_summaries(run)
        append_run_event(
            run,
            "summary.completed",
            InspectionRun.Status.SUCCEEDED,
            {"resource_summary_ids": [str(summary.pk) for summary in summaries]},
        )
        _mark_stage(run, "resource_summaries")


def _snapshot(run):
    if _stage_done(run, "snapshot"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "snapshot"):
            return
        build_daily_snapshot(run, allow_nonterminal=True, as_of=timezone.now())
        _mark_stage(run, "snapshot")


def _complete(run):
    if _stage_done(run, "complete"):
        return
    with transaction.atomic():
        run = _locked_run(run.pk)
        if _stage_done(run, "complete"):
            return
        _finish_run(run)
        _mark_stage(run, "complete")
        append_run_event(
            run,
            "run.completed",
            run.status,
            {
                "status": run.status,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            },
        )


def _fail(run_id, error):
    logger.exception("manual inspection run failed", exc_info=error)
    with transaction.atomic():
        run = _locked_run(run_id)
        if run.status in {
            InspectionRun.Status.SUCCEEDED,
            InspectionRun.Status.PARTIAL,
            InspectionRun.Status.FAILED,
        } and run.finished_at is not None:
            return
        run.status = InspectionRun.Status.FAILED
        run.error_message = str(error)[:4000]
        run.finished_at = run.finished_at or timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        ResourceInspectionSummary.objects.filter(inspection_run=run).update(
            status=run.status,
            finished_at=run.finished_at,
        )
        if not InspectionRunEvent.objects.filter(
            inspection_run=run,
            event_type="run.failed",
        ).exists():
            append_run_event(
                run,
                "run.failed",
                InspectionRun.Status.FAILED,
                {"error_message": str(error)[:4000]},
            )


def _locked_run(run_id):
    return InspectionRun.objects.select_for_update().get(pk=run_id)


def _items_for_run(run):
    resolved_scope = (run.config_snapshot or {}).get("resolved_scope") or {}
    if "inspection_item_ids" in resolved_scope:
        return list(
            InspectionItem.objects.filter(pk__in=resolved_scope.get("inspection_item_ids") or [])
            .order_by("code", "created_at", "pk")
        )
    return list(InspectionItem.objects.filter(enabled=True).order_by("code", "created_at"))


def _stage_done(run, stage):
    batch = (run.config_snapshot or {}).get("batch") or {}
    return bool((batch.get("stages") or {}).get(stage))


def _mark_stage(run, stage):
    snapshot = dict(run.config_snapshot or {})
    batch = dict(snapshot.get("batch") or {})
    stages = dict(batch.get("stages") or {})
    stages[stage] = True
    batch["stages"] = stages
    snapshot["batch"] = batch
    run.config_snapshot = snapshot
    run.save(update_fields=["config_snapshot"])


def _finish_run(run):
    item_runs = InspectionItemRun.objects.filter(inspection_run=run)
    total = item_runs.count()
    succeeded = item_runs.filter(status=InspectionItemRun.Status.SUCCEEDED).count()
    failed = item_runs.filter(status=InspectionItemRun.Status.FAILED).count()
    status = InspectionRun.Status.PARTIAL if failed else InspectionRun.Status.SUCCEEDED
    run.status = status
    run.total_items = total
    run.success_items = succeeded
    run.failed_items = failed
    run.finished_at = run.finished_at or timezone.now()
    run.save(
        update_fields=[
            "status",
            "total_items",
            "success_items",
            "failed_items",
            "finished_at",
        ]
    )
    ResourceInspectionSummary.objects.filter(inspection_run=run).update(
        status=status,
        finished_at=run.finished_at,
    )


__all__ = ["start_manual_inspection_run"]
