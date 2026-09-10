"""Deterministic execution from scoped input facts, independent of AI and scenarios."""
from collections import Counter

from django.db import transaction
from django.utils import timezone

from apps.assets.models import Asset
from apps.inspections.models import CheckResult, Finding, InspectionItem, InspectionItemRun, InspectionRun
from apps.inspections.rules import CheckResultSpec
from apps.inspections.rules.registry import RULES, get_rule
from apps.inspections.services.findings import FindingSpec, persist_findings
from apps.inspections.services.input_reader import InspectionInputReader
from apps.inspections.services.scope import resolve_item_asset_scope


def execute_inspection_item(inspection_run, inspection_item, dataset=None, *, registry=None, observed_at=None):
    dataset = dataset or inspection_run.dataset
    if dataset is None or dataset.environment_id != inspection_run.environment_id:
        raise ValueError('Run requires a dataset from the same environment')
    with transaction.atomic():
        item_run, _ = InspectionItemRun.objects.select_for_update().get_or_create(inspection_run=inspection_run, inspection_item=inspection_item)
        # Completed facts are immutable on duplicate delivery.
        if item_run.finished_at is not None:
            return item_run
        if 'asset_ids' not in (item_run.asset_scope or {}):
            scope = resolve_item_asset_scope(inspection_run, inspection_item)
            if scope is None:
                asset_type = 'POD' if inspection_item.code == 'topology.control_plane_anti_affinity' else 'LLM_INSTANCE'
                targets = Asset.objects.filter(environment_id=inspection_run.environment_id, status='ACTIVE', asset_type=asset_type)
                if asset_type == 'POD':
                    targets = targets.filter(labels__component='control-plane')
                scope = {'asset_ids': [str(pk) for pk in targets.values_list('pk', flat=True)]}
            item_run.asset_scope = scope
        reader = InspectionInputReader(dataset, item_run.asset_scope['asset_ids'])
        assets = list(reader.assets())
        item_run.started_at = observed_at or timezone.now()
        item_run.status = 'RUNNING'
        item_run.ai_admission_status = 'NO_AI'
        item_run.save()
        try:
            results = get_rule(inspection_item.code)(reader=reader, assets=assets, config=item_run.asset_scope.get("rule_config", inspection_item.rule_config))
            result_ids = [r.asset.pk for r in results]
            if set(result_ids) != {a.pk for a in assets} or len(result_ids) != len(assets):
                raise ValueError('Rule must return exactly one result for each scoped asset')
            if any(r.status not in CheckResult.Status.values for r in results):
                raise ValueError('Invalid check status')
            item_run.status = 'FAILED' if any(r.status == 'ERROR' for r in results) else 'SUCCEEDED'
        except Exception as error:
            item_run.status = 'FAILED'
            item_run.error_code = type(error).__name__[:64]
            item_run.error_message = str(error)[:4000]
            results = [CheckResultSpec(a, 'ERROR', '规则执行失败', evidence={'error_code': item_run.error_code}) for a in assets]
        item_run.finished_at = timezone.now()
        CheckResult.objects.bulk_create([CheckResult(inspection_run=inspection_run, inspection_item_run=item_run, asset=r.asset, status=r.status, summary=r.summary, observed_value=r.observed_value, expected_value=r.expected_value, evidence={**r.evidence, 'asset_name':r.asset.name}, checked_at=item_run.finished_at) for r in results])
        failures = [r for r in results if r.status == 'FAIL']
        persist_findings(item_run, [FindingSpec(finding_code=inspection_item.code, title=r.summary, category=inspection_item.domain, severity=inspection_item.default_severity, observed_at=item_run.finished_at, asset=r.asset, materiality=1, value={'observed':r.observed_value, 'expected':r.expected_value, 'evidence':r.evidence}, source_type=Finding.SourceType.RULE) for r in failures])
        counts = dict(Counter(r.status for r in results))
        item_run.summary = {'result_counts':counts, 'finding_count':len(failures), 'data_valid':bool(results) and not any(r.status in {'UNKNOWN','ERROR'} for r in results), 'rule_config':dict(item_run.asset_scope.get('rule_config', inspection_item.rule_config)), 'data_source':'MOCK'}
        item_run.save()
        _update_run_counts(inspection_run)
        return item_run


def execute_inspection_run(inspection_run, inspection_items=None, dataset=None, *, registry=None):
    requested_by_id = not isinstance(inspection_run, InspectionRun)
    if requested_by_id:
        inspection_run = InspectionRun.objects.select_related('dataset').get(pk=inspection_run)
    items = inspection_items
    if items is None:
        resolved = (inspection_run.config_snapshot or {}).get('resolved_scope') or {}
        items = InspectionItem.objects.all()
        if 'inspection_item_ids' in resolved:
            items = items.filter(pk__in=resolved['inspection_item_ids'])
        else:
            items = items.filter(enabled=True, code__in=RULES)
        items = items.order_by('code', 'pk')
    results = [execute_inspection_item(inspection_run, item, dataset, registry=registry) for item in items]
    _update_run_counts(inspection_run)
    inspection_run.refresh_from_db()
    return inspection_run if requested_by_id else results


def _update_run_counts(inspection_run):
    item_runs = InspectionItemRun.objects.filter(inspection_run=inspection_run)
    InspectionRun.objects.filter(pk=inspection_run.pk).update(total_items=item_runs.count(), success_items=item_runs.filter(status='SUCCEEDED').count(), failed_items=item_runs.filter(status='FAILED').count())
