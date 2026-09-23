import json
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from django.test import Client

from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inspections.rules.registry import get_code_plugin
from apps.inspections.services.code_dispatch import dispatch_code_rule
from apps.inference_performance.services.input_reader import InferenceSnapshotInputReader

from .helpers import payload, sample


def test_registered_rule_requires_real_input_source():
    plugin = get_code_plugin('llm.performance_profile')
    assert plugin.input_source == 'INFERENCE_SNAPSHOT'
    assert plugin.plugin_id == 'inference-performance'

    class WrongReader:
        source_type = 'MOCK_DATASET'

    with pytest.raises(ValueError, match='input source'):
        dispatch_code_rule(rule_code='llm.performance_profile', reader=WrongReader(), assets=[], config={})


@pytest.mark.django_db
def test_push_and_replay_use_registered_plugin_and_stable_asset(monkeypatch):
    environment = Environment.objects.create(name='Production', slug='plugin-prod')
    client = Client()
    request = payload(str(environment.id), sample_id='plugin-sample')
    monkeypatch.setenv('DEPLOY_COMMIT_SHA', 'a' * 40)
    from apps.inference_performance.services import ingest
    real_dispatch = ingest.dispatch_code_rule
    calls = []

    def spy(**kwargs):
        calls.append(kwargs['rule_code'])
        return real_dispatch(**kwargs)

    monkeypatch.setattr(ingest, 'dispatch_code_rule', spy)
    first = client.post('/api/v1/inference-performance/snapshots', data=json.dumps(request), content_type='application/json')
    from apps.inference_performance.services import policy
    initial = InferencePerformanceSnapshot.objects.get(sample_id='plugin-sample').evaluation
    changed_config = policy.load_policy_config()
    changed_config['default']['fixed']['requests.waiting']['warning'] = 5
    monkeypatch.setattr(policy, 'load_policy_config', lambda: changed_config)
    second = client.post('/api/v1/inference-performance/snapshots', data=json.dumps(request), content_type='application/json')
    assert first.status_code == 201
    assert second.status_code == 200
    assert calls == ['llm.performance_profile']
    row = InferencePerformanceSnapshot.objects.get(sample_id='plugin-sample')
    assert row.asset.external_key.startswith('inference:')
    assert row.asset.labels['input_source'] == 'INFERENCE_SNAPSHOT'
    assert row.evaluation['plugin']['id'] == 'inference-performance'
    assert row.evaluation['plugin']['deployment_commit'] == 'a' * 40
    assert row.evaluation['resolved_policy']['quality']['max_age_seconds'] == 300
    assert row.evaluation == initial
    digest = hashlib.sha256(json.dumps(initial['resolved_policy'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert initial['policy_source']['config_hash'] == f'sha256:{digest}'


def test_unconfigured_or_invalid_deploy_commit_is_not_claimed(monkeypatch):
    from apps.inference_performance.services.evaluator import _deployment_commit
    monkeypatch.delenv('DEPLOY_COMMIT_SHA', raising=False)
    assert _deployment_commit() is None
    monkeypatch.setenv('DEPLOY_COMMIT_SHA', 'not-a-commit')
    assert _deployment_commit() is None


@pytest.mark.django_db
def test_conflicting_replay_and_batch_are_atomic():
    environment = Environment.objects.create(name='Production', slug='conflict-prod')
    client = Client()
    original = payload(str(environment.id), sample_id='same')
    assert client.post('/api/v1/inference-performance/snapshots', data=json.dumps(original), content_type='application/json').status_code == 201
    conflict = payload(str(environment.id), sample_id='same', ttft_p95=600)
    response = client.post('/api/v1/inference-performance/snapshots', data=json.dumps(conflict), content_type='application/json')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert 'profile' not in response.json()

    end = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    batch = {
        'source': original['source'], 'environment_id': str(environment.id), 'engine': original['engine'],
        'evaluate_latest': False,
        'samples': [sample('new-before-conflict', end + timedelta(minutes=1)), conflict['sample']],
    }
    response = client.post('/api/v1/inference-performance/snapshots/batch', data=json.dumps(batch), content_type='application/json')
    assert response.status_code == 409
    assert not InferencePerformanceSnapshot.objects.filter(sample_id='new-before-conflict').exists()


@pytest.mark.django_db
def test_batch_evaluates_event_time_latest_and_frozen_reader_reuses_result():
    environment = Environment.objects.create(name='Production', slug='batch-prod')
    client = Client()
    end = datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)
    batch = {
        'source': 'inference-monitor', 'environment_id': str(environment.id),
        'engine': {'engine_id': 'engine-a', 'engine_type': 'vllm', 'model_name': 'Qwen/Qwen3-32B'},
        'evaluate_latest': True,
        'samples': [sample('later', end + timedelta(minutes=1)), sample('earlier', end)],
    }
    response = client.post('/api/v1/inference-performance/snapshots/batch', data=json.dumps(batch), content_type='application/json')
    assert response.status_code == 201
    row = InferencePerformanceSnapshot.objects.get(sample_id='later')
    assert response.json()['evaluated']['snapshot_id'] == str(row.pk)
    reader = InferenceSnapshotInputReader(
        mode='FROZEN_RESULT', assets=[row.asset], frozen_inputs_by_asset={str(row.asset_id): {
            'snapshot_id': str(row.pk), 'evaluation': row.evaluation,
            'window_start': row.window_start.isoformat(), 'window_end': row.window_end.isoformat(),
            'frozen_at': (row.window_end + timedelta(seconds=30)).isoformat(),
            'identity': {'asset_id': str(row.asset_id), 'environment_id': str(environment.id)},
        }},
    )
    result = dispatch_code_rule(rule_code='llm.performance_profile', reader=reader, assets=[row.asset], config={})
    assert len(result) == 1
    assert result[0].status in {'PASS', 'FAIL', 'UNKNOWN'}
    assert result[0].evidence['evaluation'] == row.evaluation
    invalid_config = dispatch_code_rule(
        rule_code='llm.performance_profile', reader=reader, assets=[row.asset], config={'max_age_seconds': 'invalid'},
    )
    assert invalid_config[0].status == 'ERROR'
    assert invalid_config[0].evidence['error_code'] == 'ValueError'
    stale_reader = InferenceSnapshotInputReader(
        mode='FROZEN_RESULT', assets=[row.asset], frozen_inputs_by_asset={str(row.asset_id): {
            'snapshot_id': str(row.pk), 'evaluation': row.evaluation,
            'window_end': row.window_end.isoformat(),
            'frozen_at': (row.window_end + timedelta(hours=1)).isoformat(),
        }},
    )
    stale = dispatch_code_rule(rule_code='llm.performance_profile', reader=stale_reader, assets=[row.asset], config={})
    assert stale[0].status == 'UNKNOWN'


@pytest.mark.django_db
def test_engine_list_disambiguation_and_stale_profile():
    environment = Environment.objects.create(name='Production', slug='engine-list-prod')
    client = Client()
    first = payload(str(environment.id), sample_id='model-a', end=datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc))
    second = payload(str(environment.id), sample_id='model-b', end=datetime(2026, 9, 22, 8, 1, tzinfo=timezone.utc))
    second['engine']['model_name'] = 'Other/Model'
    for request in (first, second):
        assert client.post('/api/v1/inference-performance/snapshots', data=json.dumps(request), content_type='application/json').status_code == 201
    listing = client.get('/api/v1/inference-performance/engines', {'environment_id': str(environment.id)})
    assert listing.status_code == 200
    assert len(listing.json()['engines']) == 2
    ambiguous = client.get('/api/v1/inference-performance/engines/qwen-prod-1/profile', {'environment_id': str(environment.id)})
    assert ambiguous.status_code == 409
    selected = client.get('/api/v1/inference-performance/engines/qwen-prod-1/profile', {
        'environment_id': str(environment.id), 'engine_type': 'vllm', 'model_name': 'Other/Model',
    })
    assert selected.status_code == 200
    assert selected.json()['engine']['model_name'] == 'Other/Model'
    assert selected.json()['freshness']['state'] == 'STALE'
    assert selected.json()['status'] == 'UNKNOWN'
    assert selected.json()['evaluation_status'] in {'NORMAL', 'WARNING', 'CRITICAL'}
