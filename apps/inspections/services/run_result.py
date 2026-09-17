"""Read a run's frozen scope and facts without consulting the current registry."""
from django.db.models import Count, Q

from apps.inspections.models import CheckResult, ResourceInspectionSummary
from apps.inspections.serializers import serialize_check_result, serialize_resource_summary
from apps.operations_api.serializers import serialize_risk, serialize_run
from apps.risks.models import Risk, RiskObservation


def inspection_run_result(run, *, check_limit=None, risk_limit=None):
    item_runs = list(run.item_runs.select_related('inspection_item').order_by('inspection_item__code', 'pk'))
    resolved = (run.config_snapshot or {}).get('resolved_scope') or {}
    asset_ids = {str(pk) for row in item_runs for pk in (row.asset_scope or {}).get('asset_ids', [])}
    frozen_ids = set(resolved.get('asset_ids', asset_ids))
    check_scope = Q(pk__in=[])
    risk_scope = Q(pk__in=[])
    for row in item_runs:
        ids = set((row.asset_scope or {}).get('asset_ids', [])) & frozen_ids
        check_scope |= Q(inspection_item_run=row, asset_id__in=ids)
        risk_scope |= Q(inspection_item_run=row, risk__primary_asset_id__in=ids)
    checks = CheckResult.objects.filter(check_scope, inspection_run=run, asset__environment_id=run.environment_id)
    counts = dict(checks.values('status').annotate(count=Count('pk')).values_list('status', 'count'))
    observations = RiskObservation.objects.filter(risk_scope, inspection_run=run, detected=True, risk__environment_id=run.environment_id)
    risks = Risk.objects.filter(pk__in=observations.values('risk_id')).order_by('severity', 'title', 'pk')
    rows = checks.select_related('asset', 'inspection_item_run__inspection_item').order_by('inspection_item_run__inspection_item__code', 'asset_id')
    summaries = ResourceInspectionSummary.objects.filter(inspection_run=run).select_related('resource_type', 'inspection_run').order_by('resource_type__sort_order', 'resource_type__code')
    plugins = {}
    for row in item_runs:
        source = (row.summary or {}).get('engine_snapshot') or {}
        if source.get('plugin_id'):
            key = (source['plugin_id'], source.get('plugin_version'))
            plugins[key] = {**source, 'rule_code': row.inspection_item.code, 'resource_types': (row.asset_scope or {}).get('resource_types', [])}
    return {
        'run': {**serialize_run(run), 'error_message': (run.error_message or '')[:1000]},
        'scope': {'resource_types': resolved.get('resource_types') or list(dict.fromkeys(code for row in item_runs for code in (row.asset_scope or {}).get('resource_types', [])))},
        'summary': {
            'assets_total': len(frozen_ids),
            'assets_covered': checks.values('asset_id').distinct().count(),
            **{f'{status.lower()}_count': counts.get(status, 0) for status in CheckResult.Status.values},
            'risk_count': risks.count(), 'check_count': checks.count(),
        },
        'resource_summaries': [serialize_resource_summary(s) for s in summaries],
        'check_results': [serialize_check_result(row) for row in rows[:check_limit]],
        'risks': [serialize_risk(risk) for risk in risks[:risk_limit]],
        'code_plugins': list(plugins.values()),
        'truncated': (check_limit is not None and checks.count() > check_limit) or (risk_limit is not None and risks.count() > risk_limit),
    }
