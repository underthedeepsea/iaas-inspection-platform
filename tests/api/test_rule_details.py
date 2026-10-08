"""Rule descriptions must expose the actual accepted inputs and effective policy."""
import json
from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone

from apps.hardware_health.evaluator import MIN_EFFECT, evaluate
from apps.hardware_health.schemas import FIELDS
from apps.inference_performance.schemas import METRIC_FIELDS
from apps.inference_performance.services.fixed import PRIMARY_METRICS
from apps.inference_performance.services.policy import load_policy_config, resolve_policy
from apps.inspections.rules.inference_performance import _map_status


def test_rule_details_have_complete_metric_contracts_without_database_access(client, django_db_blocker):
    expected = {
        'llm.performance_profile': {f'{group}.{field}' for group, fields in METRIC_FIELDS.items() for field in fields},
        'hardware.gpu_health': {f'gpu.{field}' for field in FIELDS['gpu']},
        'hardware.host_health': {f'{family}.{field}' for family in ('host', 'filesystem', 'disk') for field in FIELDS[family]},
    }
    with django_db_blocker.block():
        response = client.get('/api/v1/rules')
        assert response.status_code == 200
        rows = {row['rule_code']: row for row in response.json()['items']}
        assert set(rows) == set(expected)
        for code, fields in expected.items():
            detail = client.get(f'/api/v1/rules/{code}')
            assert detail.status_code == 200
            assert detail.json() == rows[code]
            row = detail.json()
            assert {metric['field'] for metric in row['supported_metrics']} == fields
            assert len(row['supported_metrics']) == len(fields)
            assert all(all(metric[key] for key in ('name', 'unit', 'range', 'purpose', 'input_path'))
                       for metric in row['supported_metrics'])
            assert row['parameters'] == {} and row['deterministic'] is True
            assert row['plugin_version'] == '1.0.0'
            assert '外部采集系统' in row['input_contract']
            assert '不直接采集' in row['input_contract']
            assert all(section['title'] and section['items'] for section in row['judgment_rules'])
        assert [len(rows[code]['supported_metrics']) for code in expected] == [20, 7, 10]
        assert client.post('/api/v1/rules').status_code == 405
        assert client.patch('/api/v1/rules/llm.performance_profile').status_code == 405
        assert client.get('/api/v1/rules/unknown.code').status_code == 404
        assert client.get('/api/v1/rules/llm.ttft_slo').status_code == 410


def test_llm_detail_uses_live_policy_and_complete_inheritance(client):
    row = client.get('/api/v1/rules/llm.performance_profile').json()
    config = load_policy_config()
    profiles = row['policy_profiles']
    default = profiles[0]
    assert default['level'] == 'DEFAULT'
    assert default['policy'] == config['default']
    assert {item['field'] for item in default['fixed_thresholds']} == set(PRIMARY_METRICS)
    assert all(item['unit'] == 'ms/token' for item in default['fixed_thresholds'] if item['field'].startswith('tpot.'))
    assert all(item['unit'] == 'ms/token' for item in row['supported_metrics'] if item['field'].startswith('tpot.'))
    for profile in profiles[1:]:
        engine, model = profile['engine_type'], profile['model_name'] or 'not-configured-model'
        resolved = resolve_policy(engine_type=engine, model_name=model)
        assert profile['level'] == resolved.level
        assert profile['policy'] == resolved.policy
        for threshold in profile['fixed_thresholds']:
            assert {'warning': threshold['warning'], 'critical': threshold['critical']} == resolved.policy['fixed'][threshold['field']]
    model = next(item for item in profiles if item['level'] == 'ENGINE_MODEL')
    assert model['engine_type'] == 'vllm' and model['model_name'] == 'Qwen/Qwen3-32B'
    assert model['policy']['fixed']['ttft.p95_ms'] == {'warning': 500, 'critical': 900}
    assert model['policy']['fixed']['e2e.p95_ms'] == default['policy']['fixed']['e2e.p95_ms']
    explanation = json.dumps(row['judgment_rules'], ensure_ascii=False)
    for boundary in ('ENGINE_MODEL → ENGINE → DEFAULT', '100 点', '3 个不同日期', '0.5–1.5', '14 天', 'MAD', '趋势不抬高 overall', 'NOT_READY', 'IDLE', 'STALE', 'UNKNOWN', '不是所有模型通用'):
        assert boundary in explanation


def test_policy_file_changes_are_reflected_without_mutation_or_stale_catalog(client, settings, tmp_path):
    config = load_policy_config()
    config['default']['fixed']['ttft.p95_ms'] = {'warning': 810, 'critical': 1510}
    config['default']['dynamic']['warning_z'] = 3.5
    config['default']['trend']['window_minutes'] = 75
    config['engines']['vllm'] = {'persistence': {'consecutive_hits': 3}}
    config['models']['vllm']['Qwen/Qwen3-32B']['quality'] = {'max_age_seconds': 120}
    directory = tmp_path / 'config'
    directory.mkdir()
    path = directory / 'inference_performance_policies.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    before = path.read_bytes()
    settings.BASE_DIR = tmp_path
    response = client.get('/api/v1/rules/llm.performance_profile')
    assert response.status_code == 200
    profiles = response.json()['policy_profiles']
    assert profiles[0]['fixed_thresholds'][0]['warning'] == 810
    model = next(item for item in profiles if item['level'] == 'ENGINE_MODEL')
    assert model['policy']['persistence']['consecutive_hits'] == 3
    assert model['policy']['quality'] == {'max_age_seconds': 120, 'max_gap_seconds': 300}
    assert model['policy']['fixed']['ttft.p95_ms']['warning'] == 500
    text = json.dumps(response.json()['judgment_rules'], ensure_ascii=False)
    assert '75 分钟' in text and '3.5×σ' in text
    assert path.read_bytes() == before


def test_hardware_details_disclose_actual_confirmation_and_health_limits(client):
    for code, families in [('hardware.gpu_health', ('gpu',)), ('hardware.host_health', ('host', 'filesystem', 'disk'))]:
        row = client.get(f'/api/v1/rules/{code}').json()
        assert row['policy_profiles'] == []
        text = json.dumps(row['judgment_rules'], ensure_ascii=False)
        for boundary in ('至少 8 点', '最近 3 点至少 2 点', 'CUSUM', 'NOT_READY', 'NORMAL', '不会自动将 overall 改为 UNKNOWN', '当前实现固定 300 秒'):
            assert boundary in text
        for metric, effect in MIN_EFFECT.items():
            if any(metric in FIELDS[family] for family in families):
                assert f'{metric}={effect:g}' in text
        if code.endswith('gpu_health'):
            for boundary in ('ECC_DBE_NEW（P1）', '48/79/94/95/119/120', 'hardware_reverification', 'PASSED', '0.7', '0.2'):
                assert boundary in text
        else:
            assert 'GPU 输出吞吐 floor' not in text and 'r 为温度' not in text
            for boundary in ('至少 6 点', '0.25–4', '首值×0.03', '10%', '不单凭空间低于 10%'):
                assert boundary in text


def test_pending_llm_metric_does_not_hide_another_confirmed_failure(client):
    evaluation = {'status': 'WARNING', 'quality': {'state': 'READY', 'pending_confirmation': True}}
    assert _map_status(evaluation)[:2] == ('FAIL', 'P2')
    evaluation['status'] = 'CRITICAL'
    assert _map_status(evaluation)[:2] == ('FAIL', 'P1')
    evaluation['status'] = 'NORMAL'
    assert _map_status(evaluation)[:2] == ('UNKNOWN', None)
    description = json.dumps(client.get('/api/v1/rules/llm.performance_profile').json()['judgment_rules'], ensure_ascii=False)
    assert '已确认异常优先于待确认状态，仍映射 FAIL' in description


def test_hardware_normal_with_not_ready_diagnostics_is_disclosed(client):
    end = timezone.now()
    metrics = {'gpu': {'identity': {}, 'values': {
        key: {'value': [] if key == 'xid_events' else 100 if key == 'memory_total_bytes' else 0, 'quality': 'VALID'}
        for key in FIELDS['gpu']
    }}}
    snapshot = SimpleNamespace(pk=1, window_start=end - timedelta(minutes=1), window_end=end,
                               payload={'kind': 'GPU', 'identity': {'gpu_uuid': 'device'}, 'config_id': 'config',
                                        'bindings': {'complete': False, 'engines': []}, 'metrics': metrics})
    evaluation = evaluate(snapshot, [])
    assert evaluation['status'] == 'NORMAL'
    assert evaluation['diagnostics']['gpu/temperature_celsius']['status'] == 'NOT_READY'
    assert evaluation['diagnostics']['gpu/queue_idle']['status'] == 'NOT_READY'
    description = json.dumps(client.get('/api/v1/rules/hardware.gpu_health').json()['judgment_rules'], ensure_ascii=False)
    assert '基础检查 PASS / NORMAL 时仍可能有高级诊断未就绪' in description
