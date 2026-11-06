from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.hardware_health.models import HardwareSnapshot
from apps.hardware_health.performance_profile import LINUX_MEMORY, build_profile
from apps.inspections.models import ResourceType
from tests.performance_profile.test_portraits import llm
from tests.performance_profile.test_projection import NOW, asset, cluster


@pytest.mark.django_db
def test_k8s_profile_reuses_resource_selector_and_real_cluster_members():
    env = Environment.objects.create(name='Kubernetes profile', slug='k8s-profile')
    k8s = Asset.objects.create(environment=env, external_key='k8s', name='K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes', 'role': 'primary'})
    kvm = Asset.objects.create(environment=env, external_key='kvm', name='KVM', asset_type='CLUSTER', labels={'platform': 'kvm'})
    Asset.objects.create(environment=env, external_key='untyped', name='Unclassified', asset_type='CLUSTER')
    Asset.objects.create(environment=env, external_key='inactive-k8s', name='Inactive', asset_type='CLUSTER', status='INACTIVE', labels={'platform': 'kubernetes'})
    node = Asset.objects.create(environment=env, external_key='node', name='K8s worker', asset_type='HOST', parent=k8s, labels={'roles': ['WORKER'], 'cpu_cores': 4})
    Asset.objects.create(environment=env, external_key='kvm-node', name='KVM host', asset_type='HOST', parent=kvm, labels={'roles': ['WORKER']})
    end = timezone.now() - timedelta(seconds=1)
    def point(value):
        return {'value': value, 'quality': 'VALID', 'collected_at': end.isoformat()}
    HardwareSnapshot.objects.create(environment=env, asset=node, source='synthetic', sample_id='k8s-host', window_start=end-timedelta(minutes=1), window_end=end,
        payload={'host_id': 'node', 'config_id': 'synthetic', 'identity': {}, 'host_semantics': LINUX_MEMORY, 'metrics': {'host': {'values': {'cpu_busy_ratio': point(.6), 'memory_total_bytes': point(100), 'memory_available_bytes': point(50)}}}}, evaluation={})
    selector = ResourceType.objects.get(code='K8S_CLUSTER').asset_selector
    client = Client()
    params = {'environment_id': str(env.pk), 'resource_type': 'K8S_CLUSTER'}
    response = client.get('/api/v1/hardware-health/performance-profiles', params)
    assert response.status_code == 200
    data = response.json()
    assert [c['id'] for c in data['clusters']] == [str(k8s.pk)]
    cluster = data['clusters'][0]
    assert (cluster['asset_type'], cluster['platform'], cluster['roles']) == ('CLUSTER', 'kubernetes', ['PRIMARY'])
    assert cluster['total']['node_ids'] == [str(node.pk)]
    assert [(n['name'], n['asset_type'], n['roles']) for n in data['nodes']] == [('K8s worker', 'HOST', ['WORKER'])]
    assert data['nodes'][0]['metrics'][0]['current'] == .6
    assert cluster['total']['metrics'][0]['current'] == .6
    assert ResourceType.objects.get(code='K8S_CLUSTER').asset_selector == selector

    # The general portrait endpoint and KVM assets retain their prior data.
    generic = client.get('/api/v1/hardware-health/performance-profiles', {'environment_id': str(env.pk), 'resource_type': 'CLUSTER', 'view': 'portraits'})
    assert generic.status_code == 200
    assert str(kvm.pk) in {row['id'] for row in generic.json()['clusters']}
    assert Asset.objects.get(pk=kvm.pk).labels['platform'] == 'kvm'

    # A configured selector narrows the same entry without changing either asset.
    Asset.objects.create(environment=env, external_key='other-k8s', name='Other K8s', asset_type='CLUSTER', labels={'platform': 'kubernetes'})
    resource = ResourceType.objects.get(code='K8S_CLUSTER')
    resource.asset_selector = {'asset_types': ['CLUSTER'], 'labels': {'platform': 'kubernetes', 'role': 'primary'}}
    resource.save(update_fields=['asset_selector'])
    narrowed = client.get('/api/v1/hardware-health/performance-profiles', params)
    assert narrowed.status_code == 200
    assert [row['id'] for row in narrowed.json()['clusters']] == [str(k8s.pk)]
    assert Asset.objects.get(pk=kvm.pk).labels['platform'] == 'kvm'


def test_scoped_profile_keeps_only_services_related_to_selected_clusters():
    k8s = cluster()
    other = asset('other-cluster', kind='CLUSTER', parent=None)
    node = asset('node')
    other_node = asset('other-node', parent='other-cluster')
    service = asset('service', kind='LLM_INSTANCE', parent='node')
    other_service = asset('other-service', kind='LLM_INSTANCE', parent='other-node')
    unbound = asset('unbound', kind='LLM_INSTANCE', parent=None)
    rows = [llm('in', 'service'), llm('out', 'other-service'), llm('unknown', 'unbound')]
    data = build_profile([k8s, other, node, other_node, service, other_service, unbound], [], rows, now=NOW, resource_type='K8S_CLUSTER', portrait_mode=True, cluster_ids={'cluster'})
    assert [c['id'] for c in data['clusters']] == ['cluster']
    assert [n['id'] for n in data['nodes']] == ['node']
    assert [item['asset_id'] for item in data['llm']] == ['service']
