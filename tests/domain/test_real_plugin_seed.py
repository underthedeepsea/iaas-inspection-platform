import pytest
from django.core.management import call_command

from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType
from apps.inspections.models import InspectionRun, MockDataset
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.core.models import Environment
from apps.inspections.api import _serialize_resource_type


@pytest.mark.django_db
def test_seed_twice_keeps_retired_history_and_only_real_active_binding():
    retired = InspectionItem.objects.create(
        code='llm.ttft_slo', name='Historical demo', domain='llm',
        execution_mode='CODE_ONLY', code_status='CODE_ACTIVE', enabled=True,
    )
    resource, _ = ResourceType.objects.get_or_create(code='LLM_RUNTIME', defaults={'name': 'LLM Runtime'})
    binding = InspectionItemResourceType.objects.create(resource_type=resource, inspection_item=retired)
    call_command('seed_launch')
    call_command('seed_launch')
    retired.refresh_from_db()
    binding.refresh_from_db()
    assert not retired.enabled
    assert not binding.enabled
    assert InspectionItem.objects.filter(code='llm.performance_profile', enabled=True).count() == 1
    assert InspectionItemResourceType.objects.filter(resource_type=resource, enabled=True, inspection_item__enabled=True).values_list('inspection_item__code', flat=True).get() == 'llm.performance_profile'
    assert resource.inspection_items.count() == 2
    environment = Environment.objects.create(name='Seed display', slug='seed-display')
    assert _serialize_resource_type(resource, environment)['release_state'] == 'READY'
    control, _ = ResourceType.objects.get_or_create(code='CONTROL_PLANE', defaults={'name': 'Control plane'})
    control_view = _serialize_resource_type(control, environment)
    assert control_view['release_state'] == 'PLANNED'
    assert control_view['health_score'] is None
    assert control_view['data_state'] == 'NOT_CONNECTED'


@pytest.mark.django_db(transaction=True)
def test_e2e_complete_uses_real_snapshot_schema_without_mock_dataset():
    call_command('seed_e2e_complete')
    call_command('seed_e2e_complete')
    assert InferencePerformanceSnapshot.objects.filter(source='e2e-real-schema').count() == 2
    assert MockDataset.objects.count() == 0
    assert InspectionRun.objects.filter(trigger_type=InspectionRun.TriggerType.MANUAL).count() == 1
