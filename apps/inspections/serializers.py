def serialize_manual_inspection_run(run):
    snapshot = run.config_snapshot or {}
    requested = snapshot.get("requested_scope") or {}
    resolved = snapshot.get("resolved_scope") or {}
    return {
        "id": str(run.pk),
        "inspection_run_id": str(run.pk),
        "status": run.status,
        "trigger_type": run.trigger_type,
        "dataset_id": str(run.dataset_id) if run.dataset_id else None,
        "run_date": run.run_date.isoformat(),
        "scope": {
            "resource_types": list(requested.get("resource_types") or resolved.get("resource_types") or []),
            "asset_count": int(resolved.get("asset_count") or 0),
            "inspection_item_count": run.total_items,
        },
    }


def serialize_resource_summary(summary):
    return {
        "id": str(summary.pk),
        "inspection_run_id": str(summary.inspection_run_id),
        "resource_type": summary.resource_type.code,
        "run_date": summary.inspection_run.run_date.isoformat(),
        "status": summary.status,
        "assets_total": summary.assets_total,
        "assets_covered": summary.assets_covered,
        "coverage_rate": (
            summary.assets_covered / summary.assets_total if summary.assets_total else None
        ),
        "inspection_item_count": summary.inspection_item_count,
        "success_item_count": summary.success_item_count,
        "failed_item_count": summary.failed_item_count,
        "finding_count": summary.finding_count,
        "risk_count": summary.risk_count,
        "p1_count": summary.p1_count,
        "p2_count": summary.p2_count,
        "p3_count": summary.p3_count,
        "p4_count": summary.p4_count,
        "ai_dependent_cases": summary.ai_dependent_cases,
        "ai_investigation_count": summary.ai_investigation_count,
        "health_score": float(summary.health_score) if summary.health_score is not None else None,
        "started_at": summary.started_at.isoformat() if summary.started_at else None,
        "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
        "summary": summary.summary or {},
        "data_state": (summary.summary or {}).get("data_state", "READY" if summary.assets_total else "NO_DATA"),
    }


__all__ = ["serialize_manual_inspection_run", "serialize_resource_summary"]


def serialize_check_result(result):
    return {
        'id':str(result.pk), 'inspection_item_code':result.inspection_item_run.inspection_item.code,
        'inspection_item_name':result.inspection_item_run.inspection_item.name,
        'asset_id':str(result.asset_id), 'asset_name':result.evidence.get('asset_name', result.asset.name),
        'status':result.status, 'summary':result.summary, 'observed_value':result.observed_value,
        'expected_value':result.expected_value, 'evidence':result.evidence, 'checked_at':result.checked_at.isoformat(),
    }


def resource_check_results(run, resource_type):
    from apps.inspections.models import CheckResult
    item_runs = [row for row in run.item_runs.all() if resource_type.code in (row.asset_scope or {}).get('resource_types', [])]
    if not item_runs:
        item_runs = list(run.item_runs.filter(inspection_item__resource_types__resource_type=resource_type).distinct())
    asset_ids = {value for row in item_runs for value in (row.asset_scope or {}).get('asset_ids', [])}
    return [serialize_check_result(row) for row in CheckResult.objects.filter(inspection_run=run, inspection_item_run__in=item_runs, asset_id__in=asset_ids).select_related('asset','inspection_item_run__inspection_item').order_by('inspection_item_run__inspection_item__code','asset__external_key')]
