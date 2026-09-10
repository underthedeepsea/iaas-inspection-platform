from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from apps.inspections.rules.registry import get_rule, UnsupportedInspectionRule


def asset(pk, host=None, kind='POD'):
    return NS(pk=pk, asset_type=kind, labels={'component': 'control-plane'}, parent=None, parent_id=None, topology={'host': host} if host else {}, external_key=str(pk))


class Reader:
    def __init__(self, values):
        self.values = values

    def metrics(self, name, *, asset_ids=None):
        return [NS(id=i, value=v, ts=datetime(2026, 9, 10, tzinfo=timezone.utc)+timedelta(minutes=i), asset_id=1) for i, v in enumerate(self.values)]


def test_registry_is_static_and_rejects_unknown_codes():
    with pytest.raises(UnsupportedInspectionRule):
        get_rule('future.dynamic.rule')


@pytest.mark.parametrize('hosts,statuses', [(['a','a'], ['FAIL','FAIL']), (['a','b'], ['PASS','PASS']), (['a',None], ['UNKNOWN','UNKNOWN']), (['a'], ['NOT_APPLICABLE'])])
def test_control_plane_placements(hosts, statuses):
    result = get_rule('topology.control_plane_anti_affinity')(reader=None, assets=[asset(i,h) for i,h in enumerate(hosts)], config={})
    assert [r.status for r in result] == statuses


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


def test_non_finite_samples_raise_execution_error():
    with pytest.raises(ValueError):
        get_rule('llm.ttft_slo')(reader=Reader([1,2,float('nan')]), assets=[asset(1,kind='LLM_INSTANCE')], config={})
