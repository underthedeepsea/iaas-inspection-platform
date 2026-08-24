"""Small, bounded serializers for the operations/risk API."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import re


_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:[A-Za-z][A-Za-z0-9+.-]*://|\b(?:api[_ -]?key|password|passwd|token|secret|authorization)\s*=|bearer\s+)"
)


def _text(value, limit=512):
    if value is None:
        return ""
    value = str(value).strip()
    return "[redacted]" if _SENSITIVE_TEXT.search(value) else value[:limit]


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _number(value):
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return float(value)
    return value


def _list(value, limit=64):
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, 192) for item in value[:limit] if isinstance(item, str)]


def _safe_summary(value, *, limit=16):
    """Keep only scalar/list summary fields; never expose raw provider payloads."""

    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "data_valid",
        "ai_eligible",
        "required_claims",
        "resolved_claims",
        "unresolved_claims",
        "material_claim_gaps",
        "code_coverage_percent",
        "missing_data",
    }
    result = {}
    for key in allowed:
        item = value.get(key)
        if isinstance(item, bool):
            result[key] = item
        elif isinstance(item, (int, float, Decimal)):
            result[key] = _number(item)
        elif isinstance(item, (list, tuple)):
            result[key] = _list(item, limit=limit)
    return result


def serialize_snapshot(snapshot):
    return {
        "id": str(snapshot.pk),
        "snapshot_id": str(snapshot.pk),
        "environment_id": str(snapshot.environment_id),
        "date": snapshot.snapshot_date.isoformat(),
        "snapshot_date": snapshot.snapshot_date.isoformat(),
        "inspection_run_id": str(snapshot.inspection_run_id),
        "assets_total": snapshot.assets_total,
        "assets_covered": snapshot.assets_covered,
        "inspection_item_count": snapshot.inspection_item_count,
        "risk_total": snapshot.risk_total,
        "p1_count": snapshot.p1_count,
        "p2_count": snapshot.p2_count,
        "new_count": snapshot.new_count,
        "worsened_count": snapshot.worsened_count,
        "recovered_count": snapshot.recovered_count,
        "pending_action_count": snapshot.pending_action_count,
        "pending_reverify_count": snapshot.pending_reverify_count,
        "code_only_cases": snapshot.code_only_cases,
        "ai_dependent_cases": snapshot.ai_dependent_cases,
        "code_coverage_rate": _number(snapshot.code_coverage_rate),
        "deterministic_deflection_rate": _number(snapshot.deterministic_deflection_rate),
        "ai_displacement_rate": _number(snapshot.ai_displacement_rate),
        "data_completeness_rate": _number(snapshot.data_completeness_rate),
        "summary": _safe_summary(snapshot.summary),
    }


def serialize_inspection_item(item, *, detail=False):
    result = {
        "id": str(item.pk),
        "code": item.code,
        "name": item.name,
        "domain": item.domain,
        "execution_mode": item.execution_mode,
        "code_status": item.code_status,
        "code_coverage_percent": _number(item.code_coverage_percent),
        "resolved_claims": _list(item.resolved_claims),
        "llm_responsibilities": _list(item.llm_responsibilities),
        "enabled": bool(item.enabled),
    }
    if detail:
        result.update(
            {
                "description": _text(item.description, 2000),
                "default_severity": item.default_severity,
                "required_claims": _list(item.required_claims),
                "schedule_policy": _safe_summary(item.schedule_policy),
                "version": item.version,
            }
        )
    return result


def serialize_capability_binding(binding):
    version = binding.capability_version
    capability = version.capability
    return {
        "capability_id": capability.capability_id,
        "name": capability.name,
        "version": version.version,
        "version_id": str(version.pk),
        "implementation_type": version.implementation_type,
        "status": version.status,
        "role": binding.role,
        "claim": binding.claim,
        "required": bool(binding.required),
        "enabled": bool(binding.enabled),
    }


def serialize_run(run, *, detail=False):
    result = {
        "id": str(run.pk),
        "inspection_run_id": str(run.pk),
        "environment_id": str(run.environment_id),
        "dataset_id": str(run.dataset_id) if run.dataset_id else None,
        "run_date": run.run_date.isoformat(),
        "trigger_type": run.trigger_type,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "total_items": run.total_items,
        "success_items": run.success_items,
        "failed_items": run.failed_items,
        "risk_count": run.risk_count,
    }
    if detail:
        result["item_runs"] = [serialize_item_run(value) for value in run._public_item_runs]
        result["error_message"] = _text(run.error_message, 1000) if run.error_message else None
    return result


def serialize_item_run(item_run, *, detail=False):
    result = {
        "id": str(item_run.pk),
        "inspection_item_run_id": str(item_run.pk),
        "inspection_run_id": str(item_run.inspection_run_id),
        "inspection_item_id": str(item_run.inspection_item_id),
        "status": item_run.status,
        "ai_admission_status": item_run.ai_admission_status,
        "asset_scope": _safe_summary(item_run.asset_scope),
        "summary": _safe_summary(item_run.summary),
        "started_at": _iso(item_run.started_at),
        "finished_at": _iso(item_run.finished_at),
        "model_provider": _text(item_run.model_provider, 32) if item_run.model_provider else None,
        "model_name": _text(item_run.model_name, 128) if item_run.model_name else None,
        "input_tokens": item_run.input_tokens,
        "output_tokens": item_run.output_tokens,
    }
    if detail:
        result["findings"] = [serialize_finding(value) for value in item_run._public_findings]
    return result


def serialize_finding(finding):
    return {
        "id": str(finding.pk),
        "finding_id": str(finding.pk),
        "inspection_item_run_id": str(finding.inspection_item_run_id),
        "inspection_run_id": str(finding.inspection_item_run.inspection_run_id),
        "risk_id": str(finding._public_risk_id) if getattr(finding, "_public_risk_id", None) else None,
        "asset_id": str(finding.asset_id) if finding.asset_id else None,
        "finding_code": finding.finding_code,
        "title": _text(finding.title, 255),
        "category": finding.category,
        "severity": finding.severity,
        "materiality": _number(finding.materiality),
        "status": finding.status,
        "source_type": finding.source_type,
        "observed_at": _iso(finding.observed_at),
    }


def serialize_risk(risk, *, detail=False):
    result = {
        "id": str(risk.pk),
        "risk_id": str(risk.pk),
        "environment_id": str(risk.environment_id),
        "inspection_item_id": str(risk.inspection_item_id),
        "primary_asset_id": str(risk.primary_asset_id) if risk.primary_asset_id else None,
        "risk_key": risk.risk_key,
        "fingerprint": risk.fingerprint,
        "title": _text(risk.title, 255),
        "domain": risk.domain,
        "severity": risk.severity,
        "status": risk.status,
        "occurrence_count": risk.occurrence_count,
        "duration_days": risk.duration_days,
        "llm_involved_last": bool(risk.llm_involved_last),
        "ai_involved": bool(risk.llm_involved_last),
        "first_seen_at": _iso(risk.first_seen_at),
        "last_seen_at": _iso(risk.last_seen_at),
        "recovered_at": _iso(risk.recovered_at),
    }
    if detail:
        item = getattr(risk, "inspection_item", None)
        result.update(
            {
                "current_conclusion": _text(risk.current_conclusion, 4000),
                "impact_summary": _text(risk.impact_summary, 2000),
                "recommendation": _text(risk.recommendation, 2000),
                "codeization": (
                    {
                        "code_status": item.code_status,
                        "execution_mode": item.execution_mode,
                        "code_coverage_percent": _number(item.code_coverage_percent),
                        "resolved_claims": _list(item.resolved_claims),
                    }
                    if item is not None
                    else {}
                ),
                "current_investigation_id": (
                    str(risk.current_investigation_id)
                    if risk.current_investigation_id
                    else None
                ),
                "recent_investigation": _serialize_investigation(
                    getattr(risk, "_public_investigation", None)
                ),
            }
        )
    return result


def _serialize_investigation(investigation):
    if investigation is None:
        return None
    return {
        "investigation_id": str(investigation.pk),
        "status": investigation.status,
        "trigger_type": investigation.trigger_type,
        "entry_reason": investigation.entry_reason,
        "missing_claim": _text(investigation.missing_claim, 192) if investigation.missing_claim else None,
        "conclusion": _text(investigation.conclusion, 4000),
        "confidence": _number(investigation.confidence),
        "rounds_used": investigation.rounds_used,
        "tool_calls_used": investigation.tool_calls_used,
        "finished_at": _iso(investigation.finished_at),
    }


def serialize_history(history):
    return {
        "id": str(history.pk),
        "at": _iso(history.created_at),
        "type": "STATUS_CHANGE",
        "from_status": history.from_status,
        "to_status": history.to_status,
        "label": _status_label(history.to_status),
        "source": history.source,
        "reason": _text(history.reason, 1000),
        "actor_user_id": str(history.actor_user_id) if history.actor_user_id else None,
    }


def _status_label(status):
    return {
        "NEW": "首次发现",
        "PERSISTING": "风险持续",
        "WORSENED": "风险加重",
        "PENDING_ACTION": "待处置",
        "PENDING_REVERIFY": "待复验",
        "RECOVERED": "已恢复",
        "IGNORED": "已忽略",
        "FALSE_POSITIVE": "误报",
    }.get(status, _text(status, 64))


def serialize_evidence(evidence):
    return {
        "id": str(evidence.pk),
        "evidence_id": str(evidence.pk),
        "risk_id": str(evidence.risk_id) if evidence.risk_id else None,
        "inspection_run_id": str(evidence.inspection_run_id) if evidence.inspection_run_id else None,
        "inspection_item_run_id": str(evidence.inspection_item_run_id) if evidence.inspection_item_run_id else None,
        "evidence_type": evidence.evidence_type,
        "evidence_key": evidence.evidence_key,
        "summary": _text(evidence.summary, 2000),
        "source": _text(evidence.source, 128),
        "window_start": _iso(evidence.window_start),
        "window_end": _iso(evidence.window_end),
        "confidence": _number(evidence.confidence),
        "materiality": _number(evidence.materiality),
    }


__all__ = [
    "serialize_capability_binding",
    "serialize_evidence",
    "serialize_finding",
    "serialize_history",
    "serialize_inspection_item",
    "serialize_item_run",
    "serialize_risk",
    "serialize_run",
    "serialize_snapshot",
]
