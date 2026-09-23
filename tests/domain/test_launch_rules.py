from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.inference_performance.services.input_reader import InferenceSnapshotInputReader
from apps.inspections.rules.registry import UnsupportedInspectionRule, get_rule
from apps.inspections.services.code_dispatch import dispatch_code_rule


NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)


def _asset(pk):
    return SimpleNamespace(pk=pk, asset_type='LLM_INSTANCE', environment_id=1, labels={
        'engine_id': f'engine-{pk}', 'engine_type': 'vllm', 'model_name': 'Qwen/Test',
    })


def _frozen(pk, status, *, pending=False, plugin_version='1.0.0', age_seconds=10):
    return {
        'snapshot_id': f'snapshot-{pk}',
        'identity': {'asset_id': str(pk), 'environment_id': '1'},
        'engine_id': f'engine-{pk}', 'engine_type': 'vllm', 'model_name': 'Qwen/Test',
        'window_start': (NOW - timedelta(seconds=age_seconds + 60)).isoformat(),
        'window_end': (NOW - timedelta(seconds=age_seconds)).isoformat(),
        'frozen_at': NOW.isoformat(),
        'evaluation': {
            'plugin': {'id': 'inference-performance', 'version': plugin_version},
            'input': {'snapshot_id': f'snapshot-{pk}'},
            'quality': {'state': 'READY', 'pending_confirmation': pending},
            'status': status,
            'resolved_policy': {'quality': {'max_age_seconds': 300}},
        },
    }


def test_registry_is_static_and_rejects_retired_codes():
    with pytest.raises(UnsupportedInspectionRule):
        get_rule('future.dynamic.rule')
    for code in ('topology.control_plane_anti_affinity', 'llm.ttft_slo', 'llm.queue_backlog'):
        with pytest.raises(UnsupportedInspectionRule):
            get_rule(code)


def test_frozen_results_map_each_asset_status_and_severity_independently():
    assets = [_asset(1), _asset(2), _asset(3), _asset(4)]
    reader = InferenceSnapshotInputReader(
        mode='FROZEN_RESULT', assets=assets,
        frozen_inputs_by_asset={
            '1': _frozen(1, 'CRITICAL'),
            '2': _frozen(2, 'WARNING'),
            '3': _frozen(3, 'NORMAL'),
            '4': _frozen(4, 'NORMAL', pending=True),
        },
    )
    results = dispatch_code_rule(rule_code='llm.performance_profile', reader=reader, assets=assets, config={})
    assert [(row.status, row.severity) for row in results] == [
        ('FAIL', 'P1'), ('FAIL', 'P2'), ('PASS', None), ('UNKNOWN', None),
    ]


def test_missing_legacy_or_stale_result_never_becomes_pass():
    assets = [_asset(1), _asset(2), _asset(3)]
    reader = InferenceSnapshotInputReader(mode='FROZEN_RESULT', assets=assets, frozen_inputs_by_asset={
        '1': _frozen(1, 'NORMAL', plugin_version='0.0.0'),
        '2': _frozen(2, 'NORMAL', age_seconds=301),
    })
    results = dispatch_code_rule(rule_code='llm.performance_profile', reader=reader, assets=assets, config={})
    assert [row.status for row in results] == ['UNKNOWN', 'UNKNOWN', 'UNKNOWN']


def test_dispatch_rejects_reader_with_wrong_input_source():
    with pytest.raises(ValueError, match='input source'):
        dispatch_code_rule(rule_code='llm.performance_profile', reader=SimpleNamespace(source_type='MOCK'), assets=[], config={})
