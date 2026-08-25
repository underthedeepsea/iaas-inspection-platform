from django.db import transaction
from django.utils import timezone

from apps.investigations.models import Investigation, InvestigationEvent


def run_resource_investigation(investigation, context, *, failed_tools=()):
    failed_tools = set(failed_tools or ())
    with transaction.atomic():
        investigation = Investigation.objects.select_for_update().get(pk=investigation.pk)
        _append_event(
            investigation,
            "context.ready",
            InvestigationEvent.Status.COMPLETED,
            {"context_type": context.get("context_type", "RESOURCE_RUN")},
        )
        _append_event(
            investigation,
            "history.loaded",
            InvestigationEvent.Status.COMPLETED,
            {"summary_count": len(context.get("summaries") or []) + bool(context.get("previous_run"))},
        )
        tool_names = ("summary", "change_history")
        for tool_name in tool_names:
            _append_event(
                investigation,
                "tool.started",
                InvestigationEvent.Status.STARTED,
                {"tool": tool_name},
            )
            if tool_name in failed_tools:
                _append_event(
                    investigation,
                    "tool.failed",
                    InvestigationEvent.Status.FAILED,
                    {"tool": tool_name, "error": "optional evidence source unavailable"},
                )
            else:
                _append_event(
                    investigation,
                    "tool.completed",
                    InvestigationEvent.Status.COMPLETED,
                    {"tool": tool_name},
                )
        _append_event(investigation, "analysis.started", InvestigationEvent.Status.STARTED, {})
        conclusion = _conclusion(context)
        _append_event(
            investigation,
            "analysis.completed",
            InvestigationEvent.Status.COMPLETED,
            {"summary": conclusion, "confidence": 0.8},
        )
        investigation.status = Investigation.Status.RESOLVED
        investigation.conclusion = conclusion
        investigation.confidence = 0.8
        investigation.rounds_used = 1
        investigation.tool_calls_used = len(tool_names)
        investigation.started_at = investigation.started_at or timezone.now()
        investigation.finished_at = timezone.now()
        investigation.claim_token = None
        investigation.claim_heartbeat_at = None
        investigation.save(
            update_fields=[
                "status",
                "conclusion",
                "confidence",
                "rounds_used",
                "tool_calls_used",
                "started_at",
                "finished_at",
                "claim_token",
                "claim_heartbeat_at",
                "updated_at",
            ]
        )
    return investigation


def _append_event(investigation, event_type, status, payload):
    sequence = (
        InvestigationEvent.objects.filter(investigation=investigation)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
        or 0
    )
    return InvestigationEvent.objects.create(
        investigation=investigation,
        sequence=sequence + 1,
        event_type=event_type,
        status=status,
        payload=payload,
    )


def _conclusion(context):
    summary = context.get("current_summary") or (context.get("summaries") or [{}])[-1]
    health_score = summary.get("health_score")
    risk_count = summary.get("risk_count", 0)
    return f"资源健康度 {health_score if health_score is not None else '未知'}，当前关联风险 {risk_count} 项。"


__all__ = ["run_resource_investigation"]
