from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.hardware_health.models import HardwareSnapshot
from apps.hardware_health.performance_profile import LINUX_MEMORY, build_profile
from apps.hardware_health.profile_api import ASSET_LIMIT, LIMIT
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inspections.models import ResourceType
from tests.performance_profile.test_projection import NOW, asset, hw
from tests.performance_profile.test_portraits import llm


def test_equal_host_identity_is_scoped_to_each_cluster():
    a = asset('cluster-a', kind='CLUSTER', parent=None)
    b = asset('cluster-b', kind='CLUSTER', parent=None)
    worker = asset('a-worker', parent='cluster-a', host='shared-host', roles=['WORKER'])
    api = asset('b-api', parent='cluster-b', host='shared-host', roles=['API_SERVER'])
    rows = [hw('a-worker', -1, .2, host='shared-host'), hw('b-api', 0, .9, host='shared-host')]
    data = build_profile([a, b, worker, api], rows, [], now=NOW, resource_type='K8S_CLUSTER', cluster_ids={'cluster-a', 'cluster-b'}, portrait_mode=True)
    clusters = {c['id']: c for c in data['clusters']}
    nodes = {n['scope_cluster_id']: n for n in data['nodes']}
    assert [(nodes[key]['id'], nodes[key]['roles'], nodes[key]['metrics'][0]['current']) for key in ('cluster-a', 'cluster-b')] == [('a-worker', ['WORKER'], .2), ('b-api', ['API_SERVER'], .9)]
    assert clusters['cluster-a']['total']['node_ids'] == ['a-worker']
    assert clusters['cluster-b']['total']['node_ids'] == ['b-api']
    assert next(g for g in clusters['cluster-a']['groups'] if g['role'] == 'API_SERVER_ONLY')['node_count'] == 0
    assert next(g for g in clusters['cluster-b']['groups'] if g['role'] == 'API_SERVER_ONLY')['node_count'] == 1
    assert clusters['cluster-a']['total']['metrics'][0]['current'] == .2
    assert clusters['cluster-b']['total']['metrics'][0]['current'] == .9
    assert [r['id'] for r in clusters['cluster-a']['relationships'] if r['kind'] == 'node'] == [nodes['cluster-a']['portrait_id']]
    assert [r['id'] for r in clusters['cluster-b']['relationships'] if r['kind'] == 'node'] == [nodes['cluster-b']['portrait_id']]


def test_identity_dedup_still_combines_members_within_one_cluster():
    cluster = asset('cluster', kind='CLUSTER', parent=None)
    one = asset('api', parent='cluster', host='shared', roles=['API_SERVER'])
    two = asset('etcd', parent='cluster', host='shared', roles=['ETCD'])
    data = build_profile([cluster, one, two], [hw('api', -1, .2, host='shared'), hw('etcd', 0, .9, host='shared')], [], now=NOW, resource_type='K8S_CLUSTER', cluster_ids={'cluster'})
    assert len(data['nodes']) == 1
    assert data['nodes'][0]['roles'] == ['API_SERVER', 'ETCD']
    assert data['clusters'][0]['total']['node_count'] == 1
    assert next(g for g in data['clusters'][0]['groups'] if g['role'] == 'MIXED')['node_count'] == 1


def test_distinct_services_with_equal_engine_identity_keep_separate_observations():
    a = asset('cluster-a', kind='CLUSTER', parent=None)
    b = asset('cluster-b', kind='CLUSTER', parent=None)
    worker = asset('worker', parent='cluster-a')
    other = asset('other', parent='cluster-b')
    one = asset('service-a', kind='LLM_INSTANCE', parent='worker')
    two = asset('service-b', kind='LLM_INSTANCE', parent='other')
    rows = [llm('same', 'service-a', value=10), llm('same', 'service-b', value=90)]
    data = build_profile([a, b, worker, other, one, two], [], rows, now=NOW, resource_type='K8S_CLUSTER', cluster_ids={'cluster-a', 'cluster-b'})
    assert {item['asset_id']: item['metrics'][0]['current'] for item in data['llm']} == {'service-a': 10, 'service-b': 90}
    assert len({item['id'] for item in data['llm']}) == 2


def test_service_scope_uses_direct_or_parent_membership_with_environment_isolation():
    a = asset('cluster-a', kind='CLUSTER', parent=None)
    b = asset('cluster-b', kind='CLUSTER', parent=None)
    a_host = asset('a-host', parent='cluster-a')
    b_host = asset('b-host', parent='cluster-b')
    a_service = asset('service-a', kind='LLM_INSTANCE', parent='a-host')
    b_service = asset('service-b', kind='LLM_INSTANCE', parent='b-host')
    direct = asset('service-direct', kind='LLM_INSTANCE', parent='cluster-a')
    foreign = asset('service-foreign', kind='LLM_INSTANCE', parent='a-host', env='foreign')
    unknown = asset('service-unknown', kind='LLM_INSTANCE', parent=None)
    assets = [a, b, a_host, b_host, a_service, b_service, direct, foreign, unknown]
    rows = [llm('same', 'service-a', value=10), llm('same', 'service-b', value=90), llm('direct', 'service-direct', value=30), llm('foreign', 'service-foreign'), llm('unknown', 'service-unknown')]
    data = build_profile(assets, [], rows, now=NOW, resource_type='K8S_CLUSTER', cluster_ids={'cluster-a', 'cluster-b'})
    services = {row['asset_id']: row for row in data['llm']}
    assert set(services) == {'service-a', 'service-b', 'service-direct'}
    assert (services['service-a']['asset_name'], services['service-a']['scope_cluster_ids'], services['service-a']['metrics'][0]['current']) == ('service-a', ['cluster-a'], 10)
    assert (services['service-b']['asset_name'], services['service-b']['scope_cluster_ids'], services['service-b']['metrics'][0]['current']) == ('service-b', ['cluster-b'], 90)
    assert services['service-direct']['scope_cluster_ids'] == ['cluster-a']
    detail = build_profile(assets, [], rows, now=NOW, resource_type='K8S_CLUSTER', cluster_ids={'cluster-a'}, portrait_mode=True)
    assert {row['asset_id'] for row in detail['llm']} == {'service-a', 'service-direct'}
    assert {row['id'] for row in detail['clusters'][0]['relationships'] if row['kind'] == 'llm'} == {row['portrait_id'] for row in detail['llm']}
    global_profile = build_profile(assets, [], rows[:2], now=NOW, resource_type='CLUSTER')
    assert len(global_profile['llm']) == 1 and 'scope_cluster_ids' not in global_profile['llm'][0]


def payload(end, cpu=.6):
    def point(value):
        return {'quality': 'VALID', 'value': value, 'collected_at': end.isoformat()}
    return {'host_id': 'selected-host', 'config_id': 'cfg', 'identity': {}, 'host_semantics': LINUX_MEMORY,
            'metrics': {'host': {'values': {'cpu_busy_ratio': point(cpu), 'memory_total_bytes': point(100), 'memory_available_bytes': point(50)}}}}


@pytest.mark.django_db
def test_unrelated_assets_and_snapshots_do_not_displace_k8s_or_its_portrait():
    env = Environment.objects.create(name='K8s limits', slug='k8s-limits')
    unrelated = [Asset(environment=env, external_key=f'unrelated-{i}', name=f'unrelated-{i}', asset_type='HOST') for i in range(ASSET_LIMIT)]
    Asset.objects.bulk_create(unrelated, batch_size=500)
    cluster = Asset.objects.create(environment=env, external_key='late-k8s', name='Selected cluster', asset_type='CLUSTER', labels={'platform': 'kubernetes'})
    node = Asset.objects.create(environment=env, external_key='selected-host', name='Selected host', asset_type='HOST', parent=cluster, labels={'roles': ['WORKER'], 'cpu_cores': 4})
    service = Asset.objects.create(environment=env, external_key='selected-service', name='Selected service', asset_type='LLM_INSTANCE', parent=node)
    unrelated_service = Asset.objects.create(environment=env, external_key='unrelated-service', name='Unrelated service', asset_type='LLM_INSTANCE', parent=unrelated[0])
    end = timezone.now() - timedelta(seconds=60)
    HardwareSnapshot.objects.create(environment=env, asset=node, source='selected', sample_id='selected', window_start=end-timedelta(seconds=1), window_end=end, payload=payload(end), evaluation={})
    InferencePerformanceSnapshot.objects.create(environment=env, asset=service, source='selected', sample_id='selected', engine_id='engine', engine_type='vllm', model_name='model', window_start=end-timedelta(seconds=1), window_end=end, metrics={'ttft': {'p95_ms': 80}}, evaluation={})
    rows = []
    for i in range(LIMIT):
        other_end = end + timedelta(seconds=1 + i // 1000)
        rows.append(HardwareSnapshot(environment=env, asset=unrelated[i % 1000], source='unrelated', sample_id=f'unrelated-{i}', window_start=other_end-timedelta(seconds=1), window_end=other_end, payload={}, evaluation={}))
    HardwareSnapshot.objects.bulk_create(rows, batch_size=500)
    inference_rows = [InferencePerformanceSnapshot(environment=env, asset=unrelated_service, source='unrelated', sample_id=f'unrelated-{i}', engine_id='other', engine_type='vllm', model_name='model', window_start=end, window_end=end+timedelta(seconds=1+i//1000), metrics={}, evaluation={}) for i in range(LIMIT)]
    InferencePerformanceSnapshot.objects.bulk_create(inference_rows, batch_size=500)

    client = Client()
    params = {'environment_id': str(env.pk), 'resource_type': 'K8S_CLUSTER'}
    response = client.get('/api/v1/hardware-health/performance-profiles', params)
    assert response.status_code == 200
    data = response.json()
    assert not data['truncated']
    assert [c['id'] for c in data['clusters']] == [str(cluster.pk)]
    assert [(n['id'], n['roles'], n['metrics'][0]['current']) for n in data['nodes']] == [(str(node.pk), ['WORKER'], .6)]
    assert [(item['asset_id'], item['metrics'][0]['current']) for item in data['llm']] == [(str(service.pk), 80)]
    assert data['clusters'][0]['total']['metrics'][0]['current'] == .6
    detail = client.get('/api/v1/hardware-health/performance-profiles', {**params, 'view': 'portraits', 'cluster_id': str(cluster.pk), 'kind': 'cluster', 'id': str(cluster.pk)})
    assert detail.status_code == 200
    assert [c['id'] for c in detail.json()['clusters']] == [str(cluster.pk)]
    assert detail.json()['nodes'][0]['metrics'][0]['current'] == .6
    assert [(item['asset_id'], item['metrics'][0]['current']) for item in detail.json()['llm']] == [(str(service.pk), 80)]
    assert not detail.json()['truncated']


@pytest.mark.django_db
def test_only_scoped_assets_trigger_existing_limit():
    env = Environment.objects.create(name='Scoped asset limit', slug='scoped-asset-limit')
    cluster = Asset.objects.create(environment=env, external_key='k8s', name='K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes'})
    Asset.objects.bulk_create([Asset(environment=env, external_key=f'host-{i}', name=f'host-{i}', asset_type='HOST', parent=cluster) for i in range(ASSET_LIMIT)], batch_size=500)
    response = Client().get('/api/v1/hardware-health/performance-profiles', {'environment_id': str(env.pk), 'resource_type': 'K8S_CLUSTER'})
    assert response.status_code == 200
    data = response.json()
    assert data['truncated'] is True
    assert len(data['nodes']) == ASSET_LIMIT - 1
    assert data['clusters'][0]['total']['metrics'][0]['state'] == 'UNKNOWN'
    assert data['clusters'][0]['total']['metrics'][0]['history']['state'] == 'TRUNCATED_UNKNOWN'


@pytest.mark.django_db
def test_only_scoped_observations_trigger_existing_limit():
    env = Environment.objects.create(name='Scoped observation limit', slug='scoped-observation-limit')
    cluster = Asset.objects.create(environment=env, external_key='k8s', name='K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes'})
    node = Asset.objects.create(environment=env, external_key='host', name='Host', asset_type='HOST', parent=cluster, labels={'cpu_cores': 4})
    now = timezone.now()
    rows = [HardwareSnapshot(environment=env, asset=node, source='scoped', sample_id=f'scoped-{i}', window_start=now-timedelta(seconds=i+1), window_end=now-timedelta(seconds=i), payload={}, evaluation={}) for i in range(LIMIT)]
    HardwareSnapshot.objects.bulk_create(rows, batch_size=500)
    params = {'environment_id': str(env.pk), 'resource_type': 'K8S_CLUSTER'}
    client = Client()
    at_limit = client.get('/api/v1/hardware-health/performance-profiles', params).json()
    assert at_limit['truncated'] is False
    HardwareSnapshot.objects.create(environment=env, asset=node, source='scoped', sample_id='scoped-extra', window_start=now-timedelta(seconds=LIMIT+1), window_end=now-timedelta(seconds=LIMIT), payload={}, evaluation={})
    over_limit = client.get('/api/v1/hardware-health/performance-profiles', params).json()
    assert over_limit['truncated'] is True
    assert over_limit['clusters'][0]['total']['metrics'][0]['state'] == 'UNKNOWN'
    assert over_limit['clusters'][0]['total']['metrics'][0]['history']['state'] == 'TRUNCATED_UNKNOWN'


@pytest.mark.django_db
def test_membership_aliases_and_environment_are_respected():
    env = Environment.objects.create(name='Aliases', slug='k8s-aliases')
    foreign = Environment.objects.create(name='Other', slug='k8s-other')
    cluster = Asset.objects.create(environment=env, external_key='k8s', name='K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes', 'cluster_uid': '123'})
    node = Asset.objects.create(environment=env, external_key='node', name='Node', asset_type='HOST', labels={'cluster_uid': 123, 'roles': ['WORKER']})
    second = Asset.objects.create(environment=env, external_key='second', name='Second', asset_type='HOST', topology={'cluster_uid': '123'})
    other_cluster = Asset.objects.create(environment=env, external_key='second-k8s', name='Second K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes', 'cluster_uid': 456})
    third = Asset.objects.create(environment=env, external_key='third', name='Third', asset_type='HOST', labels={'cluster_uid': '456'})
    bool_cluster = Asset.objects.create(environment=env, external_key='bool-k8s', name='Boolean K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes', 'cluster_uid': 'True'})
    bool_node = Asset.objects.create(environment=env, external_key='bool-node', name='Boolean Node', asset_type='HOST', labels={'cluster_uid': True})
    lower_cluster = Asset.objects.create(environment=env, external_key='lower-k8s', name='Lowercase K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes', 'cluster_uid': 'true'})
    Asset.objects.create(environment=foreign, external_key='foreign', name='Foreign', asset_type='HOST', labels={'cluster_uid': 123})
    params = {'environment_id': str(env.pk), 'resource_type': 'K8S_CLUSTER'}
    client = Client()
    data = client.get('/api/v1/hardware-health/performance-profiles', params).json()
    assert {n['id'] for n in data['nodes']} == {str(node.pk), str(second.pk), str(third.pk), str(bool_node.pk)}
    clusters = {row['id']: row for row in data['clusters']}
    assert set(clusters[str(cluster.pk)]['total']['node_ids']) == {str(node.pk), str(second.pk)}
    assert clusters[str(other_cluster.pk)]['total']['node_ids'] == [str(third.pk)]
    assert clusters[str(bool_cluster.pk)]['total']['node_ids'] == [str(bool_node.pk)]
    assert clusters[str(lower_cluster.pk)]['total']['node_ids'] == []
    empty = client.get('/api/v1/hardware-health/performance-profiles', {**params, 'cluster_id': 'not-in-selector'}).json()
    assert empty['clusters'] == [] and empty['nodes'] == [] and not empty['truncated']
    assert Asset.objects.filter(pk=cluster.pk).exists()


@pytest.mark.django_db
def test_missing_and_disabled_resource_type_return_controlled_404():
    env = Environment.objects.create(name='Missing type', slug='missing-k8s')
    resource = ResourceType.objects.get(code='K8S_CLUSTER')
    client = Client()
    params = {'environment_id': str(env.pk), 'resource_type': 'K8S_CLUSTER'}
    resource.enabled = False
    resource.save(update_fields=['enabled'])
    disabled = client.get('/api/v1/hardware-health/performance-profiles', params)
    assert disabled.status_code == 404 and disabled.json()['error']['code'] == 'RESOURCE_TYPE_NOT_FOUND'
    resource.delete()
    missing = client.get('/api/v1/hardware-health/performance-profiles', params)
    assert missing.status_code == 404 and missing.json()['error']['code'] == 'RESOURCE_TYPE_NOT_FOUND'
