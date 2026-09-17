from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from apps.inspections.rules.registry import get_rule, UnsupportedInspectionRule


def asset(pk, host=None, kind='POD', *, replica_group='control-plane', cluster='cluster-1'):
    labels = {'component': 'control-plane'}
    if replica_group is not None:
        labels['replica_group'] = replica_group
    topology = {}
    if host is not None:
        topology['host'] = host
    if cluster is not None:
        topology['cluster'] = cluster
    return NS(pk=pk, asset_type=kind, labels=labels, parent=None, parent_id=None, topology=topology, external_key=str(pk))


class Reader:
    def __init__(self, values):
        self.values = values

    def metrics(self, name, *, asset_ids=None):
        return [NS(id=i, value=v, ts=datetime(2026, 9, 10, tzinfo=timezone.utc)+timedelta(minutes=i), asset_id=1) for i, v in enumerate(self.values)]


class PerAssetReader:
    def __init__(self, values):
        self.values = values
        self.calls = 0

    def metrics(self, name, *, asset_ids=None):
        self.calls += 1
        return [
            NS(id=f'{asset_id}-{i}', value=value, ts=datetime(2026, 9, 10, tzinfo=timezone.utc)+timedelta(minutes=i), asset_id=asset_id)
            for asset_id in asset_ids
            for i, value in enumerate(self.values[asset_id])
        ]


def test_registry_is_static_and_rejects_unknown_codes():
    with pytest.raises(UnsupportedInspectionRule):
        get_rule('future.dynamic.rule')


@pytest.mark.parametrize('hosts,statuses', [(['a','a'], ['FAIL','FAIL']), (['a','b'], ['PASS','PASS']), (['a',None], ['UNKNOWN','UNKNOWN']), (['a'], ['NOT_APPLICABLE'])])
def test_control_plane_placements(hosts, statuses):
    result = get_rule('topology.control_plane_anti_affinity')(reader=None, assets=[asset(i,h) for i,h in enumerate(hosts)], config={})
    assert [r.status for r in result] == statuses


def test_control_plane_anti_affinity_is_scoped_by_cluster_and_replica_group():
    assets = [
        asset(1, 'shared', replica_group='api', cluster='a'),
        asset(2, 'other', replica_group='api', cluster='a'),
        asset(3, 'shared', replica_group='worker', cluster='a'),
        asset(4, 'shared', replica_group='api', cluster='b'),
        asset(5, 'other-b', replica_group='api', cluster='b'),
    ]
    result = get_rule('topology.control_plane_anti_affinity')(reader=None, assets=assets, config={})
    assert [row.status for row in result] == ['PASS', 'PASS', 'NOT_APPLICABLE', 'PASS', 'PASS']


def test_control_plane_missing_group_or_cluster_is_unknown():
    assets = [asset(1, 'a', replica_group=None), asset(2, 'b', cluster=None)]
    result = get_rule('topology.control_plane_anti_affinity')(reader=None, assets=assets, config={})
    assert [row.status for row in result] == ['UNKNOWN', 'UNKNOWN']


@pytest.mark.parametrize('values,status,p95', [([110,125,150,175,210,220], 'FAIL', 220), ([100,120,180], 'PASS',180), ([200,220], 'UNKNOWN',None)])
def test_ttft_uses_nearest_rank_p95(values, status, p95):
    result = get_rule('llm.ttft_slo')(reader=Reader(values), assets=[asset(1,kind='LLM_INSTANCE')], config={})[0]
    assert result.status == status
    assert result.observed_value.get('p95_ms') == p95
    assert result.expected_value['threshold_ms'] == 180


@pytest.mark.parametrize('values,status', [([11,12,15],'FAIL'), ([9,12,15],'PASS'), ([11,12],'UNKNOWN'), ([20,20,20,0],'PASS')])
def test_queue_requires_last_n_consecutive_points(values, status):
    result = get_rule('llm.queue_backlog')(reader=Reader(values), assets=[asset(1,kind='LLM_INSTANCE')], config={})
    assert result[0].status == status


@pytest.mark.parametrize('rule_code', ['llm.ttft_slo', 'llm.queue_backlog'])
def test_bad_asset_sample_does_not_overwrite_valid_asset(rule_code):
    assets = [asset(1, kind='LLM_INSTANCE'), asset(2, kind='LLM_INSTANCE')]
    reader = PerAssetReader({1: [1, 2, 3], 2: [1, 2, float('nan')]})
    result = get_rule(rule_code)(
        reader=reader,
        assets=assets,
        config={},
    )
    assert result[0].status == 'PASS'
    assert result[1].status == 'ERROR'
    assert reader.calls == 1


def test_invalid_rule_configuration_remains_item_level_error():
    with pytest.raises(ValueError):
        get_rule('llm.ttft_slo')(reader=Reader([1, 2, 3]), assets=[asset(1, kind='LLM_INSTANCE')], config={'min_samples': 0})
