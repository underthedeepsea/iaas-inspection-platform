from datetime import date
import json
import uuid
from unittest.mock import patch

import pytest
from django.test import Client

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import DailySnapshot, InspectionItem, InspectionItemResourceType, InspectionRun, MockDataset, ResourceType


TOKEN = 'test-airflow-token'
DAY = date(2026, 8, 23)
BASE = '/api/internal/v1/batch'


def _post(client, path, payload=None):
    return client.post(f'{BASE}{path}', data=json.dumps(payload or {}), content_type='application/json', HTTP_X_AIRFLOW_TOKEN=TOKEN)


def _setup(*, with_asset=True):
    environment = Environment.objects.create(name='Internal batch', slug=f'batch-{uuid.uuid4().hex}')
    resource, _ = ResourceType.objects.update_or_create(
        code='LLM_RUNTIME',
        defaults={'name': 'LLM Runtime', 'enabled': True, 'asset_selector': {'asset_types': ['LLM_INSTANCE'], 'labels': {'input_source': 'INFERENCE_SNAPSHOT'}}},
    )
    item = InspectionItem.objects.create(code='llm.performance_profile', name='Performance', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    InspectionItemResourceType.objects.create(resource_type=resource, inspection_item=item)
    if with_asset:
        Asset.objects.create(environment=environment, external_key='inference:test', asset_type='LLM_INSTANCE', name='Engine', labels={'input_source': 'INFERENCE_SNAPSHOT'})
    return environment


def _run_payload(environment, dag_run_id='scheduled-test'):
    return {'environment_id': str(environment.pk), 'run_date': DAY.isoformat(), 'dag_run_id': dag_run_id, 'source_type': 'INFERENCE_SNAPSHOT'}


@pytest.fixture(autouse=True)
def airflow_token(monkeypatch):
    monkeypatch.setenv('AIRFLOW_INTERNAL_TOKEN', TOKEN)


@pytest.mark.django_db
def test_missing_token_rejected_before_json_parsing_and_without_side_effects():
    environment = Environment.objects.create(name='Auth', slug=f'auth-{uuid.uuid4().hex}')
    response = Client().post(f'{BASE}/inspection-runs/', data=b'{not-json', content_type='application/json')
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'invalid_airflow_token'
    assert MockDataset.objects.count() == 0
    assert Environment.objects.filter(pk=environment.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_real_batch_stages_are_idempotent_without_mock_dataset():
    environment = _setup()
    client = Client()
    payload = _run_payload(environment)
    first = _post(client, '/inspection-runs/', payload)
    retry = _post(client, '/inspection-runs/', payload)
    assert first.status_code == retry.status_code == 200
    assert first.json()['inspection_run_id'] == retry.json()['inspection_run_id']
    run_id = first.json()['inspection_run_id']
    run = InspectionRun.objects.get(pk=run_id)
    assert run.dataset_id is None
    assert run.config_snapshot['input']['source_type'] == 'INFERENCE_SNAPSHOT'
    for stage in ('execute', 'correlate-risks', 'reverify', 'resource-summaries', 'snapshot', 'complete'):
        path = f'/inspection-runs/{run_id}/{stage}/'
        first_stage = _post(client, path)
        retry_stage = _post(client, path)
        assert first_stage.status_code == retry_stage.status_code == 200
    run.refresh_from_db()
    assert run.status == InspectionRun.Status.SUCCEEDED
    assert DailySnapshot.objects.filter(inspection_run=run).count() == 1
    assert MockDataset.objects.count() == 0


@pytest.mark.django_db
def test_no_active_plugin_returns_conflict_and_no_empty_healthy_run():
    environment = Environment.objects.create(name='No plugin', slug=f'empty-{uuid.uuid4().hex}')
    response = _post(Client(), '/inspection-runs/', _run_payload(environment))
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'NO_ACTIVE_PLUGIN'
    assert InspectionRun.objects.count() == 0


@pytest.mark.django_db
def test_retired_database_item_cannot_be_executed_as_active_plugin():
    environment = Environment.objects.create(name='Retired', slug=f'retired-{uuid.uuid4().hex}')
    resource, _ = ResourceType.objects.update_or_create(code='LLM_RUNTIME', defaults={'name': 'LLM Runtime', 'enabled': True, 'asset_selector': {'asset_types': ['LLM_INSTANCE']}})
    retired = InspectionItem.objects.create(code='llm.ttft_slo', name='Retired demo', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    InspectionItemResourceType.objects.create(resource_type=resource, inspection_item=retired)
    response = _post(Client(), '/inspection-runs/', _run_payload(environment, 'retired-dag'))
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'NO_ACTIVE_PLUGIN'
    assert InspectionRun.objects.count() == 0


@pytest.mark.django_db
def test_legacy_mock_generation_is_restricted_to_test_environments():
    environment = Environment.objects.create(name='Production-like', slug=f'prod-{uuid.uuid4().hex}', environment_type=Environment.EnvironmentType.PROD_SIM)
    response = _post(Client(), '/datasets/', {
        'environment_id': str(environment.pk), 'dataset_date': DAY.isoformat(), 'seed': 7, 'scenario': 'llm_scheduler_pressure',
    })
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'mock_disabled'
    assert MockDataset.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_out_of_order_stages_reject_without_side_effects():
    environment = _setup()
    client = Client()
    run_id = _post(client, '/inspection-runs/', _run_payload(environment, 'out-of-order')).json()['inspection_run_id']
    response = _post(client, f'/inspection-runs/{run_id}/correlate-risks/')
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'invalid_stage_order'
    run = InspectionRun.objects.get(pk=run_id)
    assert run.status == InspectionRun.Status.PENDING
    assert run.config_snapshot['batch']['stages'] == {}


@pytest.mark.django_db(transaction=True)
def test_snapshot_failure_keeps_run_nonterminal():
    environment = _setup()
    client = Client()
    run_id = _post(client, '/inspection-runs/', _run_payload(environment, 'snapshot-failure')).json()['inspection_run_id']
    for stage in ('execute', 'correlate-risks', 'reverify', 'resource-summaries'):
        assert _post(client, f'/inspection-runs/{run_id}/{stage}/').status_code == 200
    with patch('apps.inspections.api_internal.build_daily_snapshot', side_effect=ValueError('snapshot failure')):
        response = _post(client, f'/inspection-runs/{run_id}/snapshot/')
    assert response.status_code == 409
    run = InspectionRun.objects.get(pk=run_id)
    assert run.status == InspectionRun.Status.RUNNING
    assert not run.config_snapshot['batch']['stages'].get('snapshot')


@pytest.mark.django_db
def test_dag_run_retry_rejects_changed_immutable_context():
    environment = _setup()
    client = Client()
    payload = _run_payload(environment, 'same-dag-run')
    assert _post(client, '/inspection-runs/', payload).status_code == 200
    changed = dict(payload, run_date='2026-08-24')
    response = _post(client, '/inspection-runs/', changed)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'immutable_input_conflict'
    assert InspectionRun.objects.count() == 1
