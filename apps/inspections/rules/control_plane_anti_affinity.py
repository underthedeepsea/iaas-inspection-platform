from collections import Counter

from . import CheckResultSpec


def check_control_plane_anti_affinity(*, reader, assets, config):
    pods = [a for a in assets if a.asset_type == 'POD' and a.labels.get('component') == 'control-plane']
    hosts = {}
    for pod in pods:
        parent = pod.parent
        host = parent.external_key if parent and parent.asset_type == 'HOST' else pod.topology.get('host')
        if host is not None and not isinstance(host, str):
            raise ValueError('Host placement must be a string')
        hosts[pod.pk] = host or None
    counts = Counter(h for h in hosts.values() if h)
    results = []
    for a in assets:
        if a not in pods or len(pods) < 2:
            status, summary = 'NOT_APPLICABLE', '当前对象不适用副本反亲和检查'
        elif hosts[a.pk] and counts[hosts[a.pk]] > 1:
            status, summary = 'FAIL', '多个控制面 Pod 位于同一 Host'
        elif any(h is None for h in hosts.values()):
            status, summary = 'UNKNOWN', 'Host 映射不完整，无法确认反亲和'
        else:
            status, summary = 'PASS', '控制面 Pod 分布在不同 Host'
        results.append(CheckResultSpec(a, status, summary, {'host': hosts.get(a.pk), 'replicas': len(pods)}, {'distinct_hosts': True, 'min_replicas': 2}, {'placements': {str(k):v for k,v in hosts.items()}}))
    return results
