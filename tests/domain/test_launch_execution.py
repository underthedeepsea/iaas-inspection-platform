from datetime import date

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import CheckResult, Finding, InspectionItem, InspectionItemRun, InspectionRun, MockDataset, MockMetric
from apps.inspections.services.execution import execute_inspection_item


@pytest.fixture
def launch_context(db):
    env = Environment.objects.create(name='Launch', slug='launch')
    dataset = MockDataset.objects.create(environment=env, seed=1, scenario='arbitrary', dataset_date=date.today(), status='READY')
    item = InspectionItem.objects.create(code='llm.ttft_slo', name='TTFT', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    assets = [Asset.objects.create(environment=env, external_key=str(i), name=str(i), asset_type='LLM_INSTANCE') for i in range(2)]
    for asset in assets:
        for value in [110,125,150,175,210,220]:
            MockMetric.objects.create(dataset=dataset, asset=asset, metric_name='ttft_ms', value=value, ts=timezone.now())
    return env, dataset, item, assets


def execute(context):
    env, dataset, item, assets = context
    run = InspectionRun.objects.create(environment=env, dataset=dataset, run_date=date.today(), trigger_type='MANUAL')
    InspectionItemRun.objects.create(inspection_run=run, inspection_item=item, asset_scope={'asset_ids':[str(assets[0].pk)]})
    return execute_inspection_item(run, item)


def test_rule_result_is_independent_of_mock_scenario_name(launch_context):
    first = execute(launch_context)
    dataset = launch_context[1]
    dataset.scenario = 'healthy_baseline'
    dataset.save(update_fields=['scenario'])
    second = execute(launch_context)
    for item_run in [first, second]:
        assert item_run.status == 'SUCCEEDED'
        result = CheckResult.objects.get(inspection_item_run=item_run)
        assert result.status == 'FAIL'
        assert result.asset_id == launch_context[3][0].pk
        assert result.observed_value['p95_ms'] == 220
        assert Finding.objects.filter(inspection_item_run=item_run).count() == 1
    assert first.check_results.get().observed_value == second.check_results.get().observed_value


def test_unknown_never_generates_finding(launch_context):
    MockMetric.objects.all().delete()
    result = execute(launch_context)
    assert result.check_results.get().status == 'UNKNOWN'
    assert result.status == 'SUCCEEDED'
    assert not Finding.objects.filter(inspection_item_run=result).exists()


def test_invalid_rule_config_persists_error_and_retry_is_idempotent(launch_context):
    item = launch_context[2]
    item.rule_config = {'min_samples': 0}
    item.save()
    result = execute(launch_context)
    assert result.status == 'FAILED'
    assert result.check_results.get().status == 'ERROR'
    execute_inspection_item(result.inspection_run, item)
    assert result.check_results.count() == 1
    assert not Finding.objects.filter(inspection_item_run=result).exists()
