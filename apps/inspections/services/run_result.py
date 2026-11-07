"""Read a run's frozen scope and facts without consulting the current registry."""
from django.db.models import Count, Q

from apps.inspections.models import CheckResult, ResourceInspectionSummary
from apps.inspections.serializers import serialize_check_result, serialize_resource_summary
from apps.operations_api.serializers import serialize_risk, serialize_run
from apps.risks.models import Risk, RiskObservation
from apps.investigations.services.fact_projection import project_report


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
        risk_scope |= Q(inspection_item_run=row, risk__inspection_item_id=row.inspection_item_id, risk__primary_asset_id__in=ids)
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
    check_rows = list(rows)
    risk_rows = list(risks.select_related('primary_asset'))
    risk_refs = {}
    for observation in observations.select_related('risk', 'inspection_item_run'):
        risk = observation.risk
        key = (str(risk.primary_asset_id), str(observation.inspection_item_run.inspection_item_id))
        risk_refs.setdefault(key, []).append({'id': str(risk.pk), 'title': risk.title,
            'status': risk.status, 'severity': risk.severity, 'state_source': 'CURRENT'})
    serialized_checks = []
    for row in check_rows:
        serialized = serialize_check_result(row)
        serialized['risk_references'] = risk_refs.get((str(row.asset_id), str(row.inspection_item_run.inspection_item_id)), [])
        serialized_checks.append(serialized)
    return {
        **({'mapping_input_quality': (run.config_snapshot or {}).get('mapping_quality'), 'mapping_inputs': (run.config_snapshot or {}).get('mapping_inputs')} if 'mapping_inputs' in (run.config_snapshot or {}) else {}),
        'run': {**serialize_run(run), 'error_message': (run.error_message or '')[:1000]},
        'scope': {'resource_types': resolved.get('resource_types') or list(dict.fromkeys(code for row in item_runs for code in (row.asset_scope or {}).get('resource_types', [])))},
        'summary': {
            'assets_total': len(frozen_ids),
            'assets_covered': checks.values('asset_id').distinct().count(),
            **{f'{status.lower()}_count': counts.get(status, 0) for status in CheckResult.Status.values},
            'risk_count': risks.count(), 'check_count': checks.count(),
        },
        'resource_summaries': [serialize_resource_summary(s) for s in summaries],
        'check_results': serialized_checks[:check_limit],
        'fact_report': project_report(serialized_checks, run_id=run.pk, frozen_input=(run.config_snapshot or {}).get('input')),
        'risks': [{**serialize_risk(risk), 'asset_name': risk.primary_asset.name if risk.primary_asset else None, 'state_source': 'CURRENT'} for risk in risk_rows[:risk_limit]],
        'code_plugins': list(plugins.values()),
        'truncated': (check_limit is not None and checks.count() > check_limit) or (risk_limit is not None and risks.count() > risk_limit),
    }


def resource_run_facts(run, resource_type_code):
    """Restrict the shared frozen result to frozen per-item resource membership."""
    result = inspection_run_result(run)
    item_run_ids = [row.pk for row in run.item_runs.all() if resource_type_code in (row.asset_scope or {}).get('resource_types', [])]
    check_ids = {str(pk) for pk in CheckResult.objects.filter(inspection_run=run, inspection_item_run_id__in=item_run_ids).values_list('pk', flat=True)}
    checks = [row for row in result['check_results'] if row['id'] in check_ids]
    return project_report(checks, run_id=run.pk, frozen_input=(run.config_snapshot or {}).get('input')), checks
