"""Pure synthetic public report compatibility; frozen fixtures immutable, no Django/DB import."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures'
SYNTHETIC = json.loads((FIXTURES / 'host_diagnostic_v1.synthetic.json').read_text())
LEGACY_BASELINE = json.loads((FIXTURES / 'host_diagnostic_v1.synthetic-baseline.json').read_text())['fact_report']
INPUT = SYNTHETIC['frozen_input']
spec = importlib.util.spec_from_file_location('host_diagnostic_projector', ROOT / 'apps/investigations/services/fact_projection.py')
projector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projector)

def project(rows=None, frozen_input=INPUT):
    return projector.project_report(SYNTHETIC['check_results'] if rows is None else rows, run_id=SYNTHETIC['run_id'], frozen_input=frozen_input)

class HostDiagnosticPresentationTests(unittest.TestCase):
    def test_synthetic_frozen_diagnostics_keep_statistics_window_and_binding_scope(self):
        source_rows, source_input = deepcopy(SYNTHETIC['check_results']), deepcopy(INPUT)
        result = project(source_rows, source_input)
        self.assertEqual(result['check_count'], 1)
        fact = result['checks'][0]
        self.assertEqual(fact['status'], 'UNKNOWN')
        self.assertEqual(fact['quality'], {'state': 'INCOMPLETE', 'pending_confirmation': False})
        details = fact['host_diagnostics']
        cpu, decline = details['items']
        self.assertEqual((cpu['status'], cpu['statistics']['sample_count']), ('NOT_READY', 0))
        self.assertEqual(cpu['reason'], 'INSUFFICIENT_COMPARABLE_HISTORY')
        self.assertEqual((decline['status'], decline['statistics']['sample_count']), ('NOT_READY', 1))
        self.assertIsNone(decline['reason'])
        self.assertEqual(cpu['binding_context']['recorded'], True)
        self.assertEqual(cpu['binding_context']['complete'], False)
        self.assertEqual(cpu['binding_context']['engine_count'], 0)
        snapshot = INPUT['snapshots'][fact['asset_id']]
        self.assertEqual(details['window_start'], snapshot['window_start'])
        self.assertEqual(details['window_end'], snapshot['window_end'])
        for item in details['items']:
            self.assertNotIn('baseline_start', item['statistics'])
            self.assertNotIn('baseline_end', item['statistics'])
        self.assertIn('8', cpu['requirements'])
        self.assertIn('6', decline['requirements'])
        self.assertIn('300', decline['requirements'])
        self.assertIn('非本Run新增冻结参数', details['rule_reference'])
        self.assertEqual({x['component']: x['status'] for x in details['coverage']}, {'host':'READY', 'disk':'MISSING', 'filesystem':'MISSING'})
        self.assertEqual(fact['measurements'][0]['current'], .3125)
        self.assertEqual(source_rows, SYNTHETIC['check_results'])
        self.assertEqual(source_input, INPUT)
        checksums = json.loads((FIXTURES / 'host_diagnostic_v1.synthetic-protected-sha256.json').read_text())
        # The public immutable synthetic input and historical baseline replace the
        # private before-source/artifact hash obligation; neither may change in projection.
        self.assertTrue(all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == checksum for name, checksum in checksums.items()))

    def test_capacity_initialized_normal_and_valid_are_not_health_pass(self):
        fact = project()['checks'][0]
        diagnostics = SYNTHETIC['check_results'][0]['evidence']['evaluation']['diagnostics']
        self.assertEqual(diagnostics['host/memory_available_bytes']['status'], 'NORMAL')
        self.assertEqual(diagnostics['host/memory_total_bytes']['status'], 'NORMAL')
        self.assertEqual({item['metric'] for item in fact['host_diagnostics']['items']}, {'host/cpu_busy_ratio','host/decline'})
        for item in fact['measurements']:
            self.assertEqual(item['quality'], 'VALID')
            self.assertEqual(item['layer'], 'OBSERVATION')
            self.assertFalse(item['contributes_to_status'])
            self.assertNotIn('status', item)
        self.assertEqual(fact['status'], 'UNKNOWN')
        self.assertIn('不生成健康PASS', fact['host_diagnostics']['observation_note'])

    def test_recorded_abnormal_with_missing_keeps_fail_priority_and_risk(self):
        failed = deepcopy(SYNTHETIC['check_results'][0])
        failed['status'] = 'FAIL'
        failed['risk_references'] = [{'id':'existing-risk','status':'NEW','severity':'P1'}]
        evaluation = failed['evidence']['evaluation']
        evaluation['status'] = 'CRITICAL'
        evaluation['diagnostics']['host/cpu_busy_ratio'] = {'status':'WARNING','sample_count':8,'baseline_median':0.1,'current':0.4}
        evaluation['diagnostics']['host/decline'] = {'status':'WARNING','sample_count':6,'long_slope_bytes_per_second':-1000,'short_slope_bytes_per_second':-1100}
        evaluation['diagnostics']['disk:sda/read_latency_avg_ms'] = {'status':'CRITICAL','sample_count':9,'current':15}
        other = deepcopy(SYNTHETIC['check_results'][0]); other['asset_id']='other-host'; other['id']='other-check'
        result = project([other, failed])
        fact = result['checks'][0]
        self.assertEqual((result['check_count'], result['status_counts']['FAIL'], result['status_counts']['UNKNOWN']), (2,1,1))
        self.assertEqual(fact['status'], 'FAIL')
        self.assertEqual(fact['quality']['state'], 'INCOMPLETE')
        self.assertEqual(fact['risks'], failed['risk_references'])
        items = {item['metric']:item for item in fact['host_diagnostics']['items']}
        self.assertEqual(items['host/cpu_busy_ratio']['status'], 'WARNING')
        self.assertEqual(items['host/decline']['status'], 'WARNING')
        self.assertEqual(items['disk:sda/read_latency_avg_ms']['status'], 'CRITICAL')
        self.assertEqual(fact['host_diagnostics']['evaluation_status'], 'CRITICAL')
        self.assertTrue(any(item['component']=='disk' and item['status']=='MISSING' for item in fact['host_diagnostics']['coverage']))

    def test_old_report_and_no_matching_frozen_input_stay_compatible(self):
        projected = project()
        projected['checks'][0].pop('host_diagnostics')
        # Ignore only the explicit metadata cleanup changes; the synthetic historical baseline stays byte-for-byte intact.
        expected = deepcopy(LEGACY_BASELINE)
        payload = INPUT['snapshots'][expected['checks'][0]['asset_id']]['payload']
        for item in expected['checks'][0]['measurements']:
            item['config_id'] = payload['config_id']
            point = payload['metrics']['host']['values'][item['metric'].split('/')[1]]
            if 'measurement_semantics' not in point:
                item.pop('measurement_semantics', None)  # old report had a platform-synthesized label
        self.assertEqual(projected, expected)
        no_input = project(frozen_input=None)['checks'][0]
        self.assertFalse(no_input['host_diagnostics']['items'][0]['binding_context']['recorded'])
        self.assertNotIn('complete', no_input['host_diagnostics']['items'][0]['binding_context'])
        mismatch = deepcopy(INPUT)
        next(iter(mismatch['snapshots'].values()))['snapshot_id'] = 'not-this-check'
        self.assertFalse(project(frozen_input=mismatch)['checks'][0]['host_diagnostics']['items'][0]['binding_context']['recorded'])
        old_row = {'id':'old','inspection_item_code':'hardware.host_health','status':'UNKNOWN','evidence':{}}
        self.assertNotIn('host_diagnostics', project([old_row])['checks'][0])
        non_host = deepcopy(SYNTHETIC['check_results'][0]); non_host['inspection_item_code']='llm.performance_profile'
        self.assertNotIn('host_diagnostics', project([non_host])['checks'][0])

    def test_historical_source_config_and_time_preserved_without_platform_synthesis(self):
        fact = project()['checks'][0]
        payload = INPUT['snapshots'][fact['asset_id']]['payload']
        for item in fact['measurements']:
            point = payload['metrics']['host']['values'][item['metric'].split('/')[1]]
            self.assertEqual(item['source'], 'synthetic-macos-observation-only')
            self.assertEqual(item['source'], payload['source'])
            self.assertEqual(item['config_id'], payload['config_id'])
            self.assertEqual(item['current'], point['value'])
            self.assertEqual(item['collected_at'], point['collected_at'])
            self.assertNotIn('measurement_semantics', item)
        self.assertEqual(fact['status'], 'UNKNOWN')
        self.assertEqual(fact['host_diagnostics']['items'][0]['status'], 'NOT_READY')

    def test_controlled_linux_input_contract_preserves_already_converted_bytes(self):
        # Constructed Linux input contract fixture, not sampled telemetry and not a rewritten Mac fixture.
        rows, frozen_input = controlled_linux_fixture()
        original = deepcopy(frozen_input)
        fact = project(rows, frozen_input)['checks'][0]
        points = {item['metric']: item for item in fact['measurements']}
        self.assertEqual(points['host/memory_available_bytes']['current'], 4194304)  # upstream 4096 kB * 1024
        self.assertEqual(points['host/memory_total_bytes']['current'], 16777216)  # upstream 16384 kB * 1024
        for key in ('host/memory_available_bytes', 'host/memory_total_bytes'):
            self.assertEqual(points[key]['unit'], 'bytes')
            self.assertEqual(points[key]['source'], 'controlled-linux-meminfo-fixture')
            self.assertEqual(points[key]['config_id'], 'controlled-memavailable-bytes-v1')
            self.assertNotIn('measurement_semantics', points[key])
        self.assertEqual(frozen_input, original)
        self.assertEqual(fact['status'], 'UNKNOWN')

    def test_upstream_semantics_are_verbatim_and_missing_memory_not_replaced(self):
        rows, frozen_input = controlled_linux_fixture()
        point = frozen_input['snapshots']['controlled-host']['payload']['metrics']['host']['values']['memory_available_bytes']
        point['measurement_semantics'] = 'Controlled upstream MemAvailable estimate; already bytes'
        available = next(item for item in project(rows, frozen_input)['checks'][0]['measurements'] if item['metric']=='host/memory_available_bytes')
        self.assertEqual(available['measurement_semantics'], point['measurement_semantics'])
        for quality in ('MISSING', 'UNSUPPORTED'):
            point.update(value=None, quality=quality)
            measurements = project(rows, frozen_input)['checks'][0]['measurements']
            self.assertNotIn('host/memory_available_bytes', [item['metric'] for item in measurements])
            self.assertEqual(len(measurements), 2)  # no zero, free+inactive fallback or invented value


def controlled_linux_fixture():
    """External bytes contract only; no Linux system call, collection, ingest or new Run."""
    collected_at = '2026-01-01T00:00:01+00:00'
    payload = {'kind':'HOST', 'source':'controlled-linux-meminfo-fixture',
               'config_id':'controlled-memavailable-bytes-v1', 'sample_id':'controlled-sample',
               'metrics':{'host':{'values':{
                   'cpu_busy_ratio':{'value':0.25,'quality':'VALID','collected_at':collected_at},
                   'memory_available_bytes':{'value':4194304,'quality':'VALID','collected_at':collected_at},
                   'memory_total_bytes':{'value':16777216,'quality':'VALID','collected_at':collected_at},
               }}}}
    snapshot = {'asset_id':'controlled-host','snapshot_id':'controlled-snapshot','payload':payload,
                'window_start':'2026-01-01T00:00:00+00:00','window_end':collected_at,'frozen_at':collected_at}
    rows = [{'id':'controlled-check','asset_id':'controlled-host','inspection_item_code':'hardware.host_health',
             'status':'UNKNOWN','evidence':{'snapshot_id':'controlled-snapshot'}}]
    return rows, {'as_of':collected_at,'snapshots':{'controlled-host':snapshot}}

if __name__ == '__main__':
    unittest.main(verbosity=2)


class NewHostRuleProjectionTests(unittest.TestCase):
    def test_static_fail_survives_incomplete_coverage_and_raw_values_stay_frozen(self):
        rows=deepcopy(SYNTHETIC['check_results']);source=deepcopy(rows)
        check=rows[0];check['status']='FAIL'
        ev=check['evidence']['evaluation'];ev['plugin']={'id':'gpu-host-health','version':'2.0.0'};ev['status']='CRITICAL'
        ev['diagnostics']['host/cpu_static']={'status':'CRITICAL','current':.9,'unit':'ratio','rule_id':'host/cpu_static','rule_version':'2.0.0','rule':{'warning':.8,'critical':.9},'confirmation_points':3,'trigger_window_seconds':120,'reason':'CONFIRMED_STATIC_LIMIT','action':'Check CPU'}
        ev['reasons']=[{'key':'host/cpu_static','code':'HOST_CPU_STATIC_LIMIT','severity':'P1',**ev['diagnostics']['host/cpu_static']}]
        fact=project(rows)['checks'][0]
        abnormal=[x for x in fact['measurements'] if x.get('rule_id')]
        self.assertEqual((fact['status'],len(abnormal),abnormal[0]['current']),('FAIL',1,.9))
        self.assertEqual(abnormal[0]['rule'],{'warning':.8,'critical':.9})
        self.assertEqual(fact['host_diagnostics']['items'][0]['status'],'CRITICAL')
        self.assertIn('120',fact['host_diagnostics']['items'][0]['requirements'])
        self.assertEqual(source[0]['evidence']['evaluation']['plugin']['version'],'1.0.0')
        self.assertEqual(SYNTHETIC['check_results'][0]['evidence']['evaluation']['plugin']['version'],'1.0.0')
