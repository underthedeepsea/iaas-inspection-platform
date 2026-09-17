from collections import Counter, defaultdict

from . import CheckResultSpec


def check_control_plane_anti_affinity(*, reader, assets, config):
    pods = [a for a in assets if a.asset_type == 'POD' and a.labels.get('component') == 'control-plane']
    placements = {}
    invalid = {}
    groups = defaultdict(list)
    for pod in pods:
        replica_group = pod.labels.get('replica_group') or pod.labels.get('anti_affinity')
        parent = pod.parent
        cluster_parent = parent if parent and parent.asset_type == 'CLUSTER' else parent.parent if parent and parent.parent and parent.parent.asset_type == 'CLUSTER' else None
        cluster = pod.topology.get('cluster') or pod.labels.get('cluster') or (cluster_parent.external_key if cluster_parent else None)
        if not isinstance(replica_group, str) or not replica_group.strip() or not isinstance(cluster, str) or not cluster.strip():
            invalid[pod.pk] = ('UNKNOWN', '缺少副本组或集群映射，无法确认反亲和')
            continue
        host = parent.external_key if parent and parent.asset_type == 'HOST' else pod.topology.get('host')
        if host is not None and not isinstance(host, str):
            invalid[pod.pk] = ('ERROR', 'Host 映射格式错误')
            continue
        group = (cluster.strip(), replica_group.strip())
        placements[pod.pk] = {'host': host or None, 'cluster': group[0], 'replica_group': group[1]}
        groups[group].append(pod)
    group_facts = {
        group: (members, Counter(placements[row.pk]['host'] for row in members if placements[row.pk]['host']))
        for group, members in groups.items()
    }
    results = []
    for a in assets:
        members = []
        if a not in pods:
            status, summary = 'NOT_APPLICABLE', '当前对象不适用副本反亲和检查'
        else:
            if a.pk in invalid:
                status, summary = invalid[a.pk]
            else:
                placement = placements[a.pk]
                group = (placement['cluster'], placement['replica_group'])
                members, counts = group_facts[group]
                hosts = [placements[row.pk]['host'] for row in members]
                if len(members) < 2:
                    status, summary = 'NOT_APPLICABLE', '当前副本组不足两个对象'
                elif any(host is None for host in hosts):
                    status, summary = 'UNKNOWN', 'Host 映射不完整，无法确认反亲和'
                elif counts[placement['host']] > 1:
                    status, summary = 'FAIL', '同一副本组内多个控制面 Pod 位于同一 Host'
                else:
                    status, summary = 'PASS', '同一副本组内控制面 Pod 分布在不同 Host'
        placement = placements.get(a.pk, {})
        results.append(CheckResultSpec(
            a,
            status,
            summary,
            {'host': placement.get('host'), 'replicas': len(members)},
            {'distinct_hosts': True, 'min_replicas': 2},
            {
                'cluster': placement.get('cluster'),
                'replica_group': placement.get('replica_group'),
                'placements': {str(row.pk): placements[row.pk]['host'] for row in members},
            },
        ))
    return results
