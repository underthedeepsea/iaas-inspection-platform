"""Asynchronous resource investigation runtime.

Resource investigations use the same provider-neutral graph as conversational
investigations. This module owns only the resource-specific context and the
small persistence adapter around the graph's bounded result.
"""

from collections.abc import Mapping
import logging

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.conversations.services import run_graph, sanitize_result
from apps.inspections.models import InspectionItemRun
from apps.investigations.models import Investigation, InvestigationEvent
from apps.risks.models import Evidence


logger = logging.getLogger(__name__)


def run_resource_investigation(
    investigation,
    context,
    *,
    failed_tools=(),
    gateway=None,
    graph_runner=None,
):
    """Run the read-only investigation graph and persist its bounded result.

    ``failed_tools`` is retained as a deterministic test hook for optional
    evidence-source failure coverage. Normal calls always use the injected
    graph runner or the configured ModelGateway-backed graph.
    """

    investigation_id = investigation.pk
    context = dict(context or {}) if isinstance(context, Mapping) else {}
    current = _start(investigation_id, context)
    if current is None:
        return Investigation.objects.get(pk=investigation_id)

    if failed_tools:
        raw_result = _compatibility_result(context, set(failed_tools or ()))
        metadata = {}
    else:
        graph_input = _graph_input(current, context)
        try:
            if graph_runner is not None:
                raw_result = graph_runner(graph_input)
            else:
                raw_result = run_graph(
                    graph_input,
                    gateway=gateway,
                    allow_tools=True,
                )
        except Exception:
            logger.exception(
                "resource investigation graph failed",
                extra={"investigation_id": str(investigation_id)},
            )
            raw_result = _failed_result()
        metadata = _model_metadata(gateway, raw_result)

    result = sanitize_result(raw_result)
    _persist_result(investigation_id, result, metadata, context)
    return Investigation.objects.get(pk=investigation_id)


def _start(investigation_id, context):
    with transaction.atomic():
        investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
        if investigation.status in {
            Investigation.Status.RESOLVED,
            Investigation.Status.UNRESOLVED,
            Investigation.Status.FAILED,
            Investigation.Status.CANCELLED,
        } and investigation.finished_at is not None:
            return None
        investigation.status = Investigation.Status.RUNNING
        investigation.started_at = investigation.started_at or timezone.now()
        investigation.save(update_fields=["status", "started_at", "updated_at"])
        _append_event(
            investigation,
            "context.ready",
            InvestigationEvent.Status.COMPLETED,
            {
                "context_type": context.get("context_type", "RESOURCE_RUN"),
                "investigation_id": str(investigation.pk),
            },
        )
        _append_event(
            investigation,
            "history.loaded",
            InvestigationEvent.Status.COMPLETED,
            {
                "summary_count": len(context.get("summaries") or [])
                + int(bool(context.get("previous_run"))),
                "trend_count": len(context.get("trend_7d") or []),
            },
        )
        _append_event(
            investigation,
            "analysis.started",
            InvestigationEvent.Status.STARTED,
            {"mode": "read-only-graph"},
        )
        return investigation


def _graph_input(investigation, context):
    graph_context = dict(context)
    graph_context.update(
        {
            "investigation_id": str(investigation.pk),
            "allow_tools": True,
        }
    )
    return {
        "question": context.get("question") or _resource_question(context),
        "context": graph_context,
        "missing_claim": context.get("missing_claim") or "",
        "messages": [],
        "max_rounds": investigation.max_rounds,
        "max_tool_calls": investigation.max_tool_calls,
    }


def _resource_question(context):
    resource_type = context.get("resource_type_code") or "当前资源"
    return (
        f"请基于{resource_type}的当前巡检摘要、7日趋势、风险、发现和证据，"
        "给出健康结论、关键事实、风险原因与下一步建议。只使用已提供的只读证据。"
    )


def _persist_result(investigation_id, result, metadata, context):
    with transaction.atomic():
        investigation = Investigation.objects.select_for_update().get(pk=investigation_id)
        if investigation.finished_at is not None and investigation.status in {
            Investigation.Status.RESOLVED,
            Investigation.Status.UNRESOLVED,
            Investigation.Status.FAILED,
            Investigation.Status.CANCELLED,
        }:
            return
        item_run = (
            InspectionItemRun.objects.filter(pk=investigation.inspection_item_run_id).first()
            if investigation.inspection_item_run_id
            else None
        )
        context_evidence = {
            str(item.get("evidence_key")): item
            for item in context.get("evidence") or []
            if isinstance(item, Mapping) and item.get("evidence_key")
        }
        evidence_rows = []
        for item in result.get("evidence") or []:
            evidence_key = item["evidence_key"]
            reference = context_evidence.get(evidence_key, {})
            payload = item["payload"] or reference.get("value") or {}
            evidence_type = reference.get("evidence_type") or Evidence.EvidenceType.TOOL_RESULT
            if evidence_type not in set(Evidence.EvidenceType.values):
                evidence_type = Evidence.EvidenceType.TOOL_RESULT
            window_start = _parse_datetime(reference.get("window_start"))
            window_end = _parse_datetime(reference.get("window_end"))
            row = Evidence.objects.filter(
                investigation=investigation,
                evidence_key=evidence_key,
            ).first()
            if row is None:
                row = Evidence.objects.create(
                    inspection_run_id=item_run.inspection_run_id if item_run else None,
                    inspection_item_run=item_run,
                    investigation=investigation,
                    evidence_type=evidence_type,
                    evidence_key=evidence_key,
                    summary=item["summary"] or reference.get("summary") or evidence_key,
                    payload=payload,
                    source=item["source"] or reference.get("source") or "investigation",
                    window_start=window_start,
                    window_end=window_end,
                    confidence=item["confidence"] if item["confidence"] is not None else reference.get("confidence", 1),
                    materiality=item["materiality"] if item["materiality"] is not None else reference.get("materiality", 0),
                )
            evidence_rows.append(row)

        for history in result.get("tool_history") or []:
            outcome = history.get("outcome")
            succeeded = outcome == "SUCCEEDED"
            failed = outcome in {"FAILED", "REJECTED", "BUDGET_EXHAUSTED"}
            _append_event(
                investigation,
                "tool.started",
                InvestigationEvent.Status.STARTED,
                {
                    "capability_id": history.get("capability_id", ""),
                    "arguments": history.get("arguments") or {},
                },
            )
            _append_event(
                investigation,
                "tool.completed" if succeeded else "tool.failed" if failed else "tool.requested",
                InvestigationEvent.Status.COMPLETED if succeeded else InvestigationEvent.Status.FAILED if failed else InvestigationEvent.Status.INFO,
                {
                    "capability_id": history.get("capability_id", ""),
                    "status": history.get("status", "UNKNOWN"),
                    "outcome": outcome or "UNKNOWN",
                    "evidence_key": history.get("evidence_key", ""),
                    "error_code": history.get("error_code", ""),
                },
            )
        for row in evidence_rows:
            reference = context_evidence.get(row.evidence_key, {})
            _append_event(
                investigation,
                "evidence.created",
                InvestigationEvent.Status.COMPLETED,
                {
                    "evidence_id": str(row.pk),
                    "evidence_key": row.evidence_key,
                    "evidence_type": row.evidence_type,
                    "source": row.source,
                    "summary": row.summary,
                    "observed_at": reference.get("observed_at") or (row.window_end.isoformat() if row.window_end else row.created_at.isoformat()),
                    "window_start": row.window_start.isoformat() if row.window_start else None,
                    "window_end": row.window_end.isoformat() if row.window_end else None,
                    "value": row.payload,
                    "confidence": float(row.confidence),
                    "materiality": float(row.materiality),
                    "related_finding_ids": reference.get("related_finding_ids") or [],
                    "related_risk_ids": reference.get("related_risk_ids") or [],
                },
            )

        status = result["status"]
        investigation.status = {
            "RESOLVED": Investigation.Status.RESOLVED,
            "UNRESOLVED": Investigation.Status.UNRESOLVED,
            "FAILED": Investigation.Status.FAILED,
        }[status]
        investigation.conclusion = result["conclusion"]
        investigation.confidence = result["confidence"]
        investigation.rounds_used = result["rounds_used"]
        investigation.tool_calls_used = result["tool_calls_used"]
        investigation.started_at = investigation.started_at or timezone.now()
        investigation.finished_at = timezone.now()
        investigation.claim_token = None
        investigation.claim_heartbeat_at = None
        if metadata.get("provider"):
            investigation.model_provider = metadata["provider"][:32]
        if metadata.get("model"):
            investigation.model_name = metadata["model"][:128]
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
                "model_provider",
                "model_name",
                "updated_at",
            ]
        )
        _append_event(
            investigation,
            "analysis.completed" if status != "FAILED" else "analysis.failed",
            InvestigationEvent.Status.COMPLETED if status != "FAILED" else InvestigationEvent.Status.FAILED,
            {
                "summary": result["summary"],
                "conclusion": result["conclusion"],
                "confidence": result["confidence"],
                "status": status,
                "evidence_count": len(evidence_rows),
                "next_steps": result["next_steps"],
            },
        )


def _compatibility_result(context, failed_tools):
    tool_names = ("summary", "change_history")
    history = [
        {
            "capability_id": tool_name,
            "capability_version_id": "",
            "arguments": {},
            "reason": "resource context evidence",
            "status": "FAILED" if tool_name in failed_tools else "SUCCEEDED",
            "outcome": "FAILED" if tool_name in failed_tools else "SUCCEEDED",
            "error_code": "OPTIONAL_SOURCE_UNAVAILABLE" if tool_name in failed_tools else "",
            "evidence_key": "",
        }
        for tool_name in tool_names
    ]
    conclusion = _conclusion(context)
    return {
        "status": "RESOLVED",
        "summary": conclusion,
        "conclusion": conclusion,
        "facts": [],
        "next_steps": [],
        "confidence": 0.8,
        "evidence": [],
        "tool_history": history,
        "rounds_used": 1,
        "tool_calls_used": len(tool_names),
    }


def _failed_result():
    return {
        "status": "FAILED",
        "summary": "AI 调查未能完成。",
        "conclusion": "AI 调查未能完成。",
        "facts": [],
        "next_steps": ["检查模型服务和只读能力后重试。"],
        "confidence": 0,
        "evidence": [],
        "tool_history": [],
        "rounds_used": 0,
        "tool_calls_used": 0,
        "error_code": "GRAPH_EXECUTION_FAILED",
    }


def _model_metadata(gateway, raw_result):
    provider = getattr(gateway, "provider_name", None) or getattr(gateway, "provider", None)
    model = getattr(gateway, "model", None) or getattr(gateway, "model_name", None)
    if isinstance(raw_result, Mapping):
        provider = raw_result.get("provider", raw_result.get("model_provider", provider))
        model = raw_result.get("model", raw_result.get("model_name", model))
    if not isinstance(provider, str) or not provider.strip():
        provider = str(getattr(settings, "LLM_PROVIDER", "ollama"))
    if not isinstance(model, str) or not model.strip():
        model = str(getattr(settings, "OLLAMA_MODEL", "configured"))
    return {"provider": provider.strip(), "model": model.strip()}


def _parse_datetime(value):
    if not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    return parsed if parsed is not None and timezone.is_aware(parsed) else None


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
