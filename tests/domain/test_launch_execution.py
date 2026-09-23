from datetime import date, timedelta
import uuid
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inspections.models import CheckResult, Finding, InspectionItem, InspectionItemResourceType, InspectionItemRun, InspectionRun, ResourceType
from apps.inspections.services.execution import execute_inspection_item
from apps.inspections.services.inference_freeze import freeze_inference_inputs


def _evaluation(snapshot, status):
    return {
        'schema_version': 1,
        'plugin': {'id': 'inference-performance', 'version': '1.0.0', 'rule_code': 'llm.performance_profile', 'operation': 'evaluate'},
        'input': {'snapshot_id': str(snapshot.pk)},
        'quality': {'state': 'READY', 'pending_confirmation': False},
        'status': status,
        'resolved_policy': {'quality': {'max_age_seconds': 300}},
        'policy_source': {'level': 'DEFAULT', 'config_hash': 'sha256:test'},
        'reasons': [{'code': 'TTFT_P95_FIXED_HIGH', 'metric': 'ttft.p95_ms', 'current': 1200, 'threshold': 800}] if status != 'NORMAL' else [],
    }


def _snapshot(environment, asset, status='WARNING'):
    end = timezone.now() - timedelta(seconds=5)
    row = InferencePerformanceSnapshot.objects.create(
        environment=environment, asset=asset, source='external-monitor', sample_id=str(uuid.uuid4()),
        engine_id=asset.labels['engine_id'], engine_type=asset.labels['engine_type'], model_name=asset.labels['model_name'],
        window_start=end - timedelta(minutes=1), window_end=end, metrics={},
    )
    row.evaluation = _evaluation(row, status)
    row.save(update_fields=['evaluation'])
    return row


@pytest.fixture
def launch_context(db):
    env = Environment.objects.create(name='Launch', slug=f'launch-{uuid.uuid4().hex}')
    item = InspectionItem.objects.create(code='llm.performance_profile', name='Performance', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    resource, _ = ResourceType.objects.update_or_create(code='LLM_RUNTIME', defaults={
        'name': 'LLM Runtime', 'enabled': True,
        'asset_selector': {'asset_types': ['LLM_INSTANCE'], 'labels': {'input_source': 'INFERENCE_SNAPSHOT'}},
    })
    InspectionItemResourceType.objects.create(inspection_item=item, resource_type=resource)
    assets = [Asset.objects.create(
        environment=env, external_key=f'inference:{index}', name=f'Engine {index}', asset_type='LLM_INSTANCE',
        labels={'input_source': 'INFERENCE_SNAPSHOT', 'engine_id': f'engine-{index}', 'engine_type': 'vllm', 'model_name': 'Qwen/Test'},
    ) for index in range(2)]
    snapshot = _snapshot(env, assets[0])
    return env, snapshot, item, assets


def execute(context):
    env, _snapshot_row, item, assets = context
    frozen = freeze_inference_inputs([assets[0].pk])
    run = InspectionRun.objects.create(
        environment=env, run_date=date.today(), trigger_type='MANUAL',
        config_snapshot={'input': frozen, 'resolved_scope': {
            'resource_types': ['LLM_RUNTIME'], 'inspection_item_ids': [str(item.pk)],
            'asset_ids': [str(assets[0].pk)], 'resource_asset_ids': {'LLM_RUNTIME': [str(assets[0].pk)]},
        }},
    )
    InspectionItemRun.objects.create(
        inspection_run=run, inspection_item=item,
        asset_scope={'asset_ids': [str(assets[0].pk)], 'resource_types': ['LLM_RUNTIME'], 'rule_config': dict(item.rule_config)},
    )
    return execute_inspection_item(run, item)


def test_result_is_independent_of_mutable_snapshot_source_name(launch_context):
    first = execute(launch_context)
    snapshot = launch_context[1]
    snapshot.source = 'renamed-external-monitor'
    snapshot.save(update_fields=['source'])
    second = execute(launch_context)
    for item_run in (first, second):
        assert item_run.status == 'SUCCEEDED'
        result = CheckResult.objects.get(inspection_item_run=item_run)
        assert result.status == 'FAIL'
        assert result.asset_id == launch_context[3][0].pk
        assert result.observed_value['status'] == 'WARNING'
        assert Finding.objects.filter(inspection_item_run=item_run).count() == 1
    assert first.check_results.get().evidence == second.check_results.get().evidence


def test_legacy_unversioned_result_never_generates_finding(launch_context):
    snapshot = launch_context[1]
    snapshot.evaluation = {'status': 'NORMAL'}
    snapshot.save(update_fields=['evaluation'])
    result = execute(launch_context)
    assert result.check_results.get().status == 'UNKNOWN'
    assert result.status == 'SUCCEEDED'
    assert not Finding.objects.filter(inspection_item_run=result).exists()


def test_invalid_rule_config_persists_error_and_retry_is_idempotent(launch_context):
    item = launch_context[2]
    item.rule_config = {'max_age_seconds': 'invalid'}
    item.save(update_fields=['rule_config'])
    result = execute(launch_context)
    assert result.status == 'FAILED'
    assert result.check_results.get().status == 'ERROR'
    execute_inspection_item(result.inspection_run, item)
    assert result.check_results.count() == 1
    assert not Finding.objects.filter(inspection_item_run=result).exists()


def test_risk_uses_failed_check_and_stable_asset_rule_fingerprint(launch_context):
    from apps.risks.models import Evidence, Risk
    from apps.risks.services.correlation import correlate_run
    first = execute(launch_context)
    risk = correlate_run(first.inspection_run)[0]
    assert Evidence.objects.get(risk=risk).raw_ref == str(launch_context[1].pk)
    second = execute(launch_context)
    assert correlate_run(second.inspection_run)[0].pk == risk.pk
    assert Risk.objects.filter(environment=launch_context[0]).count() == 1


def test_fabricated_finding_without_failed_check_cannot_create_risk(launch_context):
    from apps.risks.services.correlation import correlate_run
    snapshot = launch_context[1]
    snapshot.evaluation = {'status': 'NORMAL'}
    snapshot.save(update_fields=['evaluation'])
    item_run = execute(launch_context)
    Finding.objects.create(inspection_item_run=item_run, asset=launch_context[3][0], finding_code='fabricated', title='AI said risk', category='llm', severity='P2', source_type='RULE', observed_at=timezone.now())
    assert correlate_run(item_run.inspection_run) == []


def test_ai_receives_scoped_facts_and_cannot_mutate_inspection(launch_context):
    from apps.inspections.services.resource_summary import build_resource_summaries
    from apps.investigations.models import Investigation
    from apps.investigations.services.explanation import build_resource_run_context, explain
    from apps.risks.services.correlation import correlate_run
    from apps.risks.models import Risk
    from services.model_gateway.base import ModelResponse, FinalAction
    item_run = execute(launch_context)
    build_resource_summaries(item_run.inspection_run)
    correlate_run(item_run.inspection_run)
    context = build_resource_run_context(resource_type_code='LLM_RUNTIME', inspection_run_id=item_run.inspection_run.pk)
    assert {row['asset_id'] for row in context['check_results']} == {str(launch_context[3][0].pk)}
    before = list(CheckResult.objects.values())
    risks = list(Risk.objects.values())
    for failed in (False, True):
        gateway = Mock(spec=['invoke'])
        if failed:
            gateway.invoke.side_effect = RuntimeError('provider unavailable')
        else:
            gateway.invoke.return_value = ModelResponse(action=FinalAction(summary='llm.performance_profile 超阈值；不能确认根因', confidence=.5), model='test', provider='fake')
        inv = Investigation.objects.create(trigger_type='HUMAN', entry_reason='USER_QUESTION', model_name='test', model_provider='fake')
        result = explain(inv, context, gateway=gateway)
        assert result.status == ('FAILED' if failed else 'RESOLVED')
        assert gateway.invoke.call_count == 1
        assert result.max_rounds == 1 and result.tool_calls_used == 0
        assert list(CheckResult.objects.values()) == before
        assert list(Risk.objects.values()) == risks


def test_resource_check_history_exposes_only_scoped_results(launch_context):
    from apps.inspections.serializers import resource_check_results
    resource = ResourceType.objects.get(code='LLM_RUNTIME')
    item_run = execute(launch_context)
    rows = resource_check_results(item_run.inspection_run, resource)
    assert len(rows) == 1
    assert rows[0]['status'] == 'FAIL'
    assert rows[0]['observed_value']['status'] == 'WARNING'
    assert rows[0]['expected_value']['policy_source']['level'] == 'DEFAULT'
    assert rows[0]['evidence']['snapshot_id'] == str(launch_context[1].pk)


def test_plugin_provenance_is_frozen_even_when_registry_changes(launch_context, monkeypatch):
    from dataclasses import replace
    from apps.inspections.rules import registry
    from apps.inspections.serializers import serialize_check_result
    item_run = execute(launch_context)
    snapshot = item_run.summary['engine_snapshot']
    assert snapshot['rule_code'] == 'llm.performance_profile'
    assert snapshot['plugin_id'] == 'inference-performance'
    assert snapshot['plugin_version'] == '1.0.0'
    monkeypatch.setitem(registry.CODE_PLUGINS, 'llm.performance_profile', replace(registry.get_code_plugin('llm.performance_profile'), plugin_version='2.0.0'))
    execute_inspection_item(item_run.inspection_run, launch_context[2])
    item_run.refresh_from_db()
    assert item_run.summary['engine_snapshot'] == snapshot
    assert serialize_check_result(item_run.check_results.get())['source']['plugin_version'] == '1.0.0'
