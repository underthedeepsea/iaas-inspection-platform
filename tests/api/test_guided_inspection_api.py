import json
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.core.models import Environment
from apps.inspections.models import CheckResult, InspectionRun
from apps.risks.models import Risk
from apps.risks.services.correlation import correlate_run
from services.model_gateway.base import FinalAction, CallToolAction, ModelResponse
from tests.domain.test_launch_execution import launch_context, execute


@pytest.fixture
def guided(client, launch_context):


    item_run = execute(launch_context)
    run = item_run.inspection_run
    run.status, run.finished_at = 'SUCCEEDED', timezone.now()
    run.config_snapshot = {'resolved_scope': {'resource_types': ['CONTROL_PLANE', 'LLM_RUNTIME']}}
    run.save()
    correlate_run(run)
    return client, run


def test_code_plugins_are_anonymous_and_read_only(client, guided):

    assert client.get('/api/v1/code-plugins').status_code == 200

    response = client.get('/api/v1/code-plugins')
    assert response.status_code == 200
    rows = response.json()['items']
    assert len(rows) == 3
    assert {r['engine'] for r in rows} == {'PYTHON_RULE'}
    assert all(r['deterministic'] and r['version'] == '1.0.0' for r in rows)
    assert client.post('/api/v1/code-plugins').status_code == 405


def test_rule_catalog_is_anonymous_read_only_and_complete(client, guided):

    assert client.get('/api/v1/rules').status_code == 200

    response = client.get('/api/v1/rules')
    assert response.status_code == 200
    rows = response.json()['items']
    assert {row['rule_code'] for row in rows} == {
        'topology.control_plane_anti_affinity',
        'llm.ttft_slo',
        'llm.queue_backlog',
    }
    assert all(row['plugin_id'] and row['operation_key'] and row['parameters'] for row in rows)
    detail = client.get('/api/v1/rules/llm.queue_backlog')
    assert detail.status_code == 200
    assert detail.json()['name'] == 'LLM 最近 N 点连续超限'
    assert detail.json()['parameters']['consecutive_points'] == 3
    assert client.post('/api/v1/rules').status_code == 405
    assert client.patch('/api/v1/rules/llm.queue_backlog').status_code == 405


def test_aggregate_result_is_scoped_and_keeps_provenance(guided):
    client, run = guided
    other = Environment.objects.create(name='Other', slug='other')
    url = f'/api/v1/inspection-runs/{run.pk}/result'
    assert client.get(url, {'environment_id': str(other.pk)}).status_code == 404
    response = client.get(url, {'environment_id': str(run.environment_id)})
    assert response.status_code == 200
    body = response.json()
    assert body['scope']['resource_types'] == ['CONTROL_PLANE', 'LLM_RUNTIME']
    assert body['summary']['fail_count'] == 1
    assert body['summary']['assets_total'] == 1
    assert body['summary']['risk_count'] == 1
    assert len(body['check_results']) == 1
    assert body['check_results'][0]['source']['plugin_version'] == '1.0.0'
    assert body['code_plugins'][0]['plugin_id'] == 'llm-ttft-slo'
    assert {r['id'] for r in body['risks']} == {str(r.pk) for r in Risk.objects.filter(environment=run.environment)}


@pytest.mark.parametrize('payload', [{}, {'question': 'test'}, {'question': ''}, {'question': ['test']}])
def test_dashboard_ask_validates_request(guided, payload):
    client, run = guided
    if 'question' in payload and payload['question'] != 'test':
        payload['environment_id'] = str(run.environment_id)
    assert client.post('/api/v1/dashboard/ask', data=json.dumps(payload), content_type='application/json').status_code == 400


def test_dashboard_ask_exact_run_read_only_and_bounded_failure(guided, monkeypatch):
    client, run = guided
    gateway = Mock(spec=['invoke', 'timeout'])
    gateway.timeout = 120.0
    gateway.invoke.return_value = ModelResponse(action=FinalAction('根据 llm.ttft_slo 检查，TTFT 超阈值。', .7), model='test', provider='fake')
    monkeypatch.setattr('apps.conversations.services._default_gateway', lambda: gateway)
    before = list(CheckResult.objects.values())
    risks = list(Risk.objects.values())
    body = {'question': '哪些是代码分析？', 'environment_id': str(run.environment_id), 'inspection_run_id': str(run.pk)}
    response = client.post('/api/v1/dashboard/ask', data=json.dumps(body), content_type='application/json')
    assert response.status_code == 200
    answer = response.json()
    assert answer['inspection_run_id'] == str(run.pk)
    assert answer['source'] == {'type': 'AI', 'provider': 'fake', 'model': 'test'}
    assert answer['references'][0]['source'] == 'CODE'
    context = json.loads(gateway.invoke.call_args.args[0].messages[-1]['content'])
    assert len(context['check_results']) == 1
    assert context['check_results'][0]['source']['plugin_version'] == '1.0.0'
    assert context['check_results'][0]['evidence']
    assert 'fingerprint' not in context['risks'][0]
    assert gateway.timeout == 120.0
    assert gateway.invoke.call_count == 1
    for result in [RuntimeError('secret-provider-detail'), ModelResponse(action=CallToolAction('write.risk', {}, 'change'), model='test', provider='fake')]:
        gateway.invoke.side_effect = result if isinstance(result, Exception) else None
        gateway.invoke.return_value = result
        response = client.post('/api/v1/dashboard/ask', data=json.dumps(body), content_type='application/json')
        assert response.status_code == 503
        assert 'secret-provider-detail' not in response.content.decode()
    assert list(CheckResult.objects.values()) == before
    assert list(Risk.objects.values()) == risks


def test_dashboard_ask_rejects_wrong_environment_and_running_run(guided):
    client, run = guided
    other = Environment.objects.create(name='Other', slug='other')
    body = {'question': '解释', 'environment_id': str(other.pk), 'inspection_run_id': str(run.pk)}
    assert client.post('/api/v1/dashboard/ask', data=json.dumps(body), content_type='application/json').status_code == 404
    body['environment_id'] = str(run.environment_id)
    run.status = 'RUNNING'
    run.save()
    assert client.post('/api/v1/dashboard/ask', data=json.dumps(body), content_type='application/json').status_code == 409


def test_dashboard_ask_implicit_context_skips_running_and_other_environments(guided, monkeypatch):
    client, run = guided
    InspectionRun.objects.create(environment=run.environment, run_date=run.run_date, trigger_type='MANUAL', status='RUNNING')
    other = Environment.objects.create(name='Other', slug='other')
    InspectionRun.objects.create(environment=other, run_date=run.run_date, trigger_type='MANUAL', status='SUCCEEDED', finished_at=timezone.now(), config_snapshot=run.config_snapshot)
    gateway = Mock(spec=['invoke'])
    gateway.invoke.return_value = ModelResponse(action=FinalAction('根据 llm.ttft_slo 检查。', .5), model='test', provider='fake')
    monkeypatch.setattr('apps.conversations.services._default_gateway', lambda: gateway)
    response = client.post('/api/v1/dashboard/ask', data=json.dumps({'environment_id':str(run.environment_id),'question':'本次巡检发现了什么？'}), content_type='application/json')
    assert response.status_code == 200
    assert response.json()['inspection_run_id'] == str(run.pk)


def test_dashboard_explanation_limits_checks_and_excludes_unscoped_facts(guided):
    from apps.assets.models import Asset
    from apps.investigations.services.dashboard_explanation import explain_dashboard
    client, run = guided
    original = CheckResult.objects.get(inspection_run=run)
    item_run = original.inspection_item_run
    for index in range(51):
        asset = Asset.objects.create(environment=run.environment, name=f'bounded-{index}', external_key=f'bounded-{index}', asset_type='LLM_INSTANCE')
        item_run.asset_scope['asset_ids'].append(str(asset.pk))
        CheckResult.objects.create(inspection_run=run, inspection_item_run=item_run, asset=asset, status='PASS', summary='bounded fact', checked_at=timezone.now())
    item_run.save()
    unscoped = Asset.objects.create(environment=run.environment, name='outside-scope', external_key='outside-scope', asset_type='LLM_INSTANCE')
    CheckResult.objects.create(inspection_run=run, inspection_item_run=item_run, asset=unscoped, status='FAIL', summary='not permitted in context', checked_at=timezone.now())
    gateway = Mock(spec=['invoke'])
    gateway.invoke.return_value = ModelResponse(action=FinalAction('证据限于提供的检查。', .5), model='test', provider='fake')
    result = explain_dashboard(run, '对比上一次', gateway=gateway)
    context = json.loads(gateway.invoke.call_args.args[0].messages[-1]['content'])
    assert len(context['check_results']) == 50
    assert result['truncated'] is True
    assert context['previous_run'] is None
    assert all(row['asset_id'] != str(unscoped.pk) for row in context['check_results'])
    assert context['summary']['check_count'] == 52
