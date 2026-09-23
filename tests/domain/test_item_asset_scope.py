from dataclasses import replace
import uuid

import pytest

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType
from apps.inspections.rules import registry
from apps.inspections.services.trigger import create_manual_inspection_run


@pytest.mark.django_db
def test_manual_run_freezes_each_registered_item_to_its_resource_assets(monkeypatch):
    environment = Environment.objects.create(name='Item scope', slug=f'item-scope-{uuid.uuid4().hex}')
    llm, _ = ResourceType.objects.update_or_create(code='LLM_RUNTIME', defaults={
        'name': 'LLM Runtime', 'enabled': True,
        'asset_selector': {'asset_types': ['LLM_INSTANCE'], 'labels': {'input_source': 'INFERENCE_SNAPSHOT'}},
    })
    gpu = ResourceType.objects.create(code=f'GPU_TEST_{uuid.uuid4().hex[:8].upper()}', name='GPU test', asset_selector={'asset_types': ['GPU']})
    llm_item = InspectionItem.objects.create(code='llm.performance_profile', name='Performance', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    gpu_code = f'test.gpu.{uuid.uuid4().hex}'
    gpu_item = InspectionItem.objects.create(code=gpu_code, name='GPU test plugin', domain='test', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    # A second registered source type is test-only: it verifies the generic
    # per-item selector contract without restoring any demo production rule.
    monkeypatch.setitem(registry.CODE_PLUGINS, gpu_code, replace(
        registry.get_code_plugin('llm.performance_profile'), rule_code=gpu_code, resource_types=(gpu.code,),
    ))
    InspectionItemResourceType.objects.create(resource_type=llm, inspection_item=llm_item)
    InspectionItemResourceType.objects.create(resource_type=gpu, inspection_item=gpu_item)
    llm_asset = Asset.objects.create(environment=environment, external_key='inference:item-scope', name='LLM', asset_type='LLM_INSTANCE', labels={'input_source': 'INFERENCE_SNAPSHOT'})
    gpu_asset = Asset.objects.create(environment=environment, external_key='gpu:item-scope', name='GPU', asset_type='GPU')
    run = create_manual_inspection_run(environment=environment, resource_type_codes=[llm.code, gpu.code])
    llm_scope = run.item_runs.get(inspection_item=llm_item).asset_scope
    gpu_scope = run.item_runs.get(inspection_item=gpu_item).asset_scope
    assert llm_scope['resource_types'] == [llm.code]
    assert gpu_scope['resource_types'] == [gpu.code]
    assert llm_scope['asset_ids'] == [str(llm_asset.pk)]
    assert gpu_scope['asset_ids'] == [str(gpu_asset.pk)]
    assert set(run.config_snapshot['resolved_scope']['asset_ids']) == {str(llm_asset.pk), str(gpu_asset.pk)}
