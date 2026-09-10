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


def test_risks_require_failed_checks_and_pass_reverifies_same_risk(launch_context):
    from apps.risks.models import Risk
    from apps.risks.services.correlation import correlate_run
    from apps.risks.services.lifecycle import mark_handled
    from apps.risks.services.reverify import reverify_pending_risks

    first = execute(launch_context)
    risk = correlate_run(first.inspection_run)[0]
    second = execute(launch_context)
    assert correlate_run(second.inspection_run)[0].pk == risk.pk
    mark_handled(risk)
    MockMetric.objects.update(value=100)
    third = execute(launch_context)
    run = third.inspection_run
    run.status, run.finished_at = 'SUCCEEDED', timezone.now()
    run.save()
    assert [r.pk for r in reverify_pending_risks(run)] == [risk.pk]
    assert Risk.objects.get(pk=risk.pk).status == 'RECOVERED'


def test_fabricated_finding_without_failed_check_cannot_create_risk(launch_context):
    from apps.risks.services.correlation import correlate_run
    MockMetric.objects.all().delete()
    item_run = execute(launch_context)
    Finding.objects.create(inspection_item_run=item_run, asset=launch_context[3][0], finding_code='fabricated', title='AI said risk', category='llm', severity='P2', source_type='RULE', observed_at=timezone.now())
    assert correlate_run(item_run.inspection_run) == []


def test_ai_receives_scoped_facts_and_cannot_mutate_inspection(launch_context):
    from apps.inspections.models import InspectionItemResourceType, ResourceType
    from apps.inspections.services.resource_summary import build_resource_summaries
    from apps.investigations.models import Investigation
    from apps.investigations.services.explanation import build_resource_run_context, explain
    from apps.risks.services.correlation import correlate_run
    from apps.risks.models import Risk
    from services.model_gateway.base import ModelResponse, FinalAction
    from unittest.mock import Mock

    item_run = execute(launch_context)
    resource = ResourceType.objects.get(code='LLM_RUNTIME')
    InspectionItemResourceType.objects.create(inspection_item=launch_context[2], resource_type=resource)
    item_run.asset_scope['resource_types'] = ['LLM_RUNTIME']
    item_run.save()
    run = item_run.inspection_run
    build_resource_summaries(run)
    correlate_run(run)
    context = build_resource_run_context(resource_type_code='LLM_RUNTIME', inspection_run_id=run.pk)
    assert {r['asset_id'] for r in context['check_results']} == {str(launch_context[3][0].pk)}
    before = list(CheckResult.objects.values())
    risks = list(Risk.objects.values())
    for failed in [False, True]:
        gateway = Mock(spec=['invoke'])
        if failed:
            gateway.invoke.side_effect = RuntimeError('provider unavailable')
        else:
            gateway.invoke.return_value = ModelResponse(action=FinalAction(summary='llm.ttft_slo 超阈值；不能确认根因',confidence=.5),model='test',provider='fake')
        inv = Investigation.objects.create(trigger_type='HUMAN',entry_reason='USER_QUESTION',model_name='test',model_provider='fake')
        result = explain(inv, context, gateway=gateway)
        assert result.status == ('FAILED' if failed else 'RESOLVED')
        assert gateway.invoke.call_count == 1
        assert result.max_rounds == 1 and result.tool_calls_used == 0
        assert list(CheckResult.objects.values()) == before
        assert list(Risk.objects.values()) == risks
