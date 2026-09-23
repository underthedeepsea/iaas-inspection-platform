from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inspections.models import CheckResult, InspectionItem, InspectionItemResourceType, ResourceType
from apps.inspections.services.execution import execute_inspection_run
from apps.inspections.services.resource_summary import build_resource_summaries
from apps.inspections.services.trigger import create_manual_inspection_run


def _setup():
    environment = Environment.objects.create(name='Frozen scope', slug=f'frozen-{uuid.uuid4().hex}')
    resource, _ = ResourceType.objects.update_or_create(code='LLM_RUNTIME', defaults={
        'name': 'LLM Runtime', 'enabled': True,
        'asset_selector': {'asset_types': ['LLM_INSTANCE'], 'labels': {'input_source': 'INFERENCE_SNAPSHOT'}},
    })
    item = InspectionItem.objects.create(code='llm.performance_profile', name='Performance', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE', rule_config={'max_age_seconds': 300})
    InspectionItemResourceType.objects.create(resource_type=resource, inspection_item=item)
    assets = [Asset.objects.create(
        environment=environment, external_key=f'inference:{index}', name=f'Engine {index}', asset_type='LLM_INSTANCE',
        labels={'input_source': 'INFERENCE_SNAPSHOT', 'engine_id': f'engine-{index}', 'engine_type': 'vllm', 'model_name': 'Qwen/Test'},
    ) for index in range(2)]
    return environment, resource, item, assets


def _snapshot(environment, asset):
    end = timezone.now() - timedelta(seconds=5)
    row = InferencePerformanceSnapshot.objects.create(
        environment=environment, asset=asset, source='external', sample_id=str(uuid.uuid4()),
        engine_id=asset.labels['engine_id'], engine_type='vllm', model_name='Qwen/Test',
        window_start=end - timedelta(minutes=1), window_end=end, metrics={},
    )
    row.evaluation = {
        'plugin': {'id': 'inference-performance', 'version': '1.0.0'},
        'input': {'snapshot_id': str(row.pk)},
        'quality': {'state': 'READY', 'pending_confirmation': False},
        'status': 'WARNING', 'resolved_policy': {'quality': {'max_age_seconds': 300}},
    }
    row.save(update_fields=['evaluation'])
    return row


@pytest.mark.django_db
def test_execution_uses_item_ids_frozen_at_run_creation():
    environment, resource, item, assets = _setup()
    run = create_manual_inspection_run(environment=environment, resource_type_codes=[resource.code])
    original_ids = set(run.config_snapshot['resolved_scope']['inspection_item_ids'])
    added = InspectionItem.objects.create(code='test.added-after-run', name='Later', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    InspectionItemResourceType.objects.create(resource_type=resource, inspection_item=added)
    execute_inspection_run(run)
    assert {str(pk) for pk in run.item_runs.values_list('inspection_item_id', flat=True)} == original_ids
    assert run.item_runs.get().asset_scope['asset_ids'] == run.config_snapshot['resolved_scope']['asset_ids']
    assert set(run.item_runs.get().asset_scope['asset_ids']) == {str(asset.pk) for asset in assets}


@pytest.mark.django_db
def test_execution_keeps_asset_ids_frozen_when_selector_changes():
    environment, resource, item, assets = _setup()
    run = create_manual_inspection_run(environment=environment, resource_type_codes=[resource.code])
    frozen_ids = run.config_snapshot['resolved_scope']['asset_ids']
    resource.asset_selector = {'asset_types': ['GPU']}
    resource.save(update_fields=['asset_selector'])
    execute_inspection_run(run)
    assert run.item_runs.get(inspection_item=item).asset_scope['asset_ids'] == frozen_ids
    assert CheckResult.objects.filter(inspection_run=run).count() == len(assets)


@pytest.mark.django_db
def test_real_snapshot_and_summary_scope_remain_frozen_after_inventory_and_config_change():
    environment, resource, item, assets = _setup()
    _snapshot(environment, assets[0])
    run = create_manual_inspection_run(environment=environment, resource_type_codes=[resource.code])
    frozen_ids = run.config_snapshot['resolved_scope']['asset_ids']
    # Mutable policy/inventory after creation cannot change this Run's inputs.
    item.rule_config = {'max_age_seconds': 'invalid'}
    item.save(update_fields=['rule_config'])
    Asset.objects.filter(pk=assets[1].pk).update(labels={'input_source': 'removed'})
    resource.asset_selector = {'asset_types': ['GPU']}
    resource.save(update_fields=['asset_selector'])
    execute_inspection_run(run)
    assert CheckResult.objects.filter(inspection_run=run, status='FAIL').count() == 1
    summary = build_resource_summaries(run)[0]
    assert summary.assets_total == len(frozen_ids) == 2
    assert summary.assets_covered == 2
