"""Controlled pure fixtures only; no DB, API, live telemetry or OS assumption."""
from copy import deepcopy
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import unittest

from apps.hardware_health.evaluator import evaluate, declining, drift
from apps.hardware_health.host_policy import HOST_PLUGIN, HOST_SEMANTICS, POLICY, static_rules, retention_candidates, freshness_seconds, static_event_recovered, cpu_deviation

BASE=datetime(2026,1,1,tzinfo=timezone.utc)


def row(i, cpu=.4, memory=.5, *, quality='VALID', semantics=True, at=None):
    end=at or BASE+timedelta(seconds=i*60)
    def point(value): return {'value':value,'quality':'VALID','collected_at':end.isoformat()}
    values={'cpu_busy_ratio':point(cpu),'memory_available_bytes':point(memory*1000000000),'memory_total_bytes':point(1000000000)}
    if quality!='VALID': values['cpu_busy_ratio'].update(value=None,quality=quality)
    payload={'kind':'HOST','source':'controlled-linux-fixture','config_id':'fixed','host_id':'controlled-host','identity':{},'bindings':{'complete':False,'engines':[]},'metrics':{'host':{'identity':{},'values':values}}}
    if semantics: payload['host_semantics']=deepcopy(HOST_SEMANTICS)
    return SimpleNamespace(pk=str(i),payload=payload,window_start=end-timedelta(seconds=60),window_end=end,evaluation={})


def sequence(points):
    previous=[]
    for item in points:
        item.evaluation=evaluate(item,previous);previous.append(item)
    return previous


class StaticPolicyTests(unittest.TestCase):
    def test_exact_cpu_and_memory_trigger_boundaries_are_three_points(self):
        for cpu,mem,expected in ((.8,.2,'WARNING'),(.9,.1,'CRITICAL'),(.799,.201,'NORMAL')):
            rows=sequence([row(i,cpu,mem) for i in range(3)])
            for key in ('host/cpu_static','host/memory_static'):
                if expected!='NORMAL':
                    self.assertEqual(rows[1].evaluation['diagnostics'][key]['status'],'PENDING')
                self.assertEqual(rows[2].evaluation['diagnostics'][key]['status'],expected)
                self.assertEqual(rows[2].evaluation['diagnostics'][key]['trigger_window_seconds'],120)
            self.assertEqual(rows[-1].evaluation['status'],'CRITICAL' if expected=='CRITICAL' else 'WARNING' if expected=='WARNING' else 'UNKNOWN')
            self.assertEqual(rows[-1].evaluation['coverage']['disk'],'MISSING')

    def test_strict_recovery_five_points_and_severity_downgrade(self):
        rows=sequence([row(i,.9,.1) for i in range(3)]+[row(i,.85,.15) for i in range(3,8)])
        self.assertEqual(rows[-1].evaluation['status'],'CRITICAL')
        previous=rows
        for i in range(8,13):
            sample=row(i,.84,.16);sample.evaluation=evaluate(sample,previous);previous.append(sample)
            self.assertEqual(sample.evaluation['status'],'CRITICAL' if i<12 else 'WARNING')
        for i in range(13,18):
            sample=row(i,.75,.25);sample.evaluation=evaluate(sample,previous);previous.append(sample)
        self.assertEqual(previous[-1].evaluation['status'],'WARNING')
        for i in range(18,23):
            sample=row(i,.74,.26);sample.evaluation=evaluate(sample,previous);previous.append(sample)
            self.assertEqual(sample.evaluation['diagnostics']['host/cpu_static']['state'],'WARNING' if i<22 else 'NORMAL')
        recovered=[e for e in previous[-1].evaluation['host_rule_events'].values() if e['status']=='RECOVERED']
        self.assertEqual(len(recovered),2)
        self.assertTrue(all((datetime.fromisoformat(e['recovered_at'])-datetime.fromisoformat(e['recovery_window_start'])).total_seconds()==240 for e in recovered))

    def test_missing_gap_duplicate_and_source_change_break_confirmation(self):
        for interruption in ('missing','gap','duplicate','source'):
            samples=[row(0,.9),row(1,.9),row(2,.9),row(3,.9)]
            if interruption=='missing': samples[1].payload['metrics']['host']['values']['cpu_busy_ratio'].update(value=None,quality='MISSING')
            if interruption=='gap': samples[1]=row(1,.9,at=BASE+timedelta(seconds=61))
            if interruption=='duplicate': samples[1]=row(1,.9,at=BASE)
            if interruption=='source': samples[1].payload['source']='other'
            self.assertNotEqual(sequence(samples)[-1].evaluation['diagnostics']['host/cpu_static']['state'],'CRITICAL')
        samples=sequence([row(i,.9) for i in range(3)]+[row(i,.1) for i in range(3,7)]+[row(7,quality='MISSING')]+[row(8,.1)])
        self.assertEqual(samples[-1].evaluation['diagnostics']['host/cpu_static']['state'],'CRITICAL')
        self.assertEqual(samples[-1].evaluation['diagnostics']['host/cpu_static']['warning_recovery_points'],1)

    def test_reverify_requires_same_frozen_event_and_post_handle_recovery(self):
        rows=sequence([row(i,.9) for i in range(3)]+[row(i,.74) for i in range(3,8)])
        issue=rows[2].evaluation['issues'][0];evaluation=rows[-1].evaluation
        self.assertTrue(static_event_recovered(evaluation,issue,BASE+timedelta(seconds=121)))
        self.assertFalse(static_event_recovered(evaluation,issue,BASE+timedelta(seconds=180)))
        for field,replacement in (('rule_key','deleted-rule'),('rule_version','3.0.0'),('frozen_rule',{}),('status','ACTIVE'),('recovery_points',4)):
            changed=deepcopy(evaluation);changed['host_rule_events'][issue['event_id']][field]=replacement
            self.assertFalse(static_event_recovered(changed,issue,BASE))
        changed=deepcopy(evaluation);changed['host_rule_events']={}
        self.assertFalse(static_event_recovered(changed,issue,BASE))

    def test_semantics_and_independent_quality(self):
        unknown=sequence([row(i,.95,.05,semantics=False) for i in range(3)])[-1].evaluation
        self.assertEqual(unknown['diagnostics']['host/memory_static']['status'],'NOT_READY')
        samples=[row(i,.95,.05) for i in range(3)]
        for sample in samples: sample.payload['metrics']['host']['values']['memory_total_bytes'].update(value=None,quality='MISSING')
        result=sequence(samples)[-1].evaluation
        self.assertEqual(result['status'],'CRITICAL')
        self.assertEqual(result['diagnostics']['host/memory_static']['status'],'NOT_READY')
        self.assertEqual(result['diagnostics']['host/cpu_busy_ratio']['reason'],'INVALID_OR_INCOMPARABLE_POINT')
        self.assertEqual(result['plugin'],HOST_PLUGIN)
        self.assertEqual(POLICY['cpu_drift']['history_points'],30)

    def test_frozen_static_event_survives_config_change_and_missing(self):
        samples=sequence([row(i,.9) for i in range(3)])
        event=next(iter(samples[-1].evaluation['host_rule_events']))
        for i in range(3,7):
            sample=row(i,.1);sample.payload['config_id']='changed';sample.evaluation=evaluate(sample,samples);samples.append(sample)
        result=samples[-1].evaluation
        self.assertEqual(result['host_rule_events'][event]['status'],'ACTIVE')
        self.assertEqual(result['diagnostics']['host/cpu_static']['event_id'],event)
        self.assertEqual(result['host_rule_events'][event]['frozen_rule']['warning_exit'],.75)


class WindowPolicyTests(unittest.TestCase):
    def test_decline_minimum_maximum_and_gap(self):
        samples=[row(i,memory=.8-i*.01) for i in range(40)]
        self.assertEqual(declining(samples[:10],'host','memory_available_bytes')['status'],'NOT_READY')
        ready=declining(samples[:11],'host','memory_available_bytes')
        self.assertEqual((ready['status'],ready['sample_count'],ready['window_seconds']),('WARNING',11,600))
        longest=declining(samples,'host','memory_available_bytes')
        self.assertEqual((longest['sample_count'],longest['window_seconds']),(31,1800))
        samples[9].payload['metrics']['host']['values']['memory_available_bytes']['collected_at']=(samples[9].window_end-timedelta(seconds=1)).isoformat()
        self.assertEqual(declining(samples[:11],'host','memory_available_bytes')['status'],'NOT_READY')

    def test_decline_strict_drop_floor_and_direction(self):
        samples=[row(i,memory=.001-i*(1024**2/10/1000000000)) for i in range(11)]
        # Exact 1MiB must not trigger. Larger absolute values also require >3%.
        for i,sample in enumerate(samples): sample.payload['metrics']['host']['values']['memory_available_bytes']['value']=2*1024**2-i*(1024**2/10)
        self.assertEqual(declining(samples,'host','memory_available_bytes')['status'],'NORMAL')
        for sample in samples: sample.payload['metrics']['host']['values']['memory_available_bytes']['value']=100000000
        self.assertEqual(declining(samples,'host','memory_available_bytes')['status'],'NORMAL')
        for i,sample in enumerate(samples): sample.payload['metrics']['host']['values']['memory_available_bytes']['value']=100000000-i*300000
        self.assertEqual(declining(samples,'host','memory_available_bytes')['status'],'NORMAL')
        for i,sample in enumerate(samples): sample.payload['metrics']['host']['values']['memory_available_bytes']['value']=100000000-i*310000
        self.assertEqual(declining(samples,'host','memory_available_bytes')['status'],'WARNING')

    def test_run_rule_180_second_boundary_and_old_frozen_compatibility(self):
        from apps.inspections.rules.hardware_health import check_hardware_health
        asset=SimpleNamespace(pk='asset',environment_id='env')
        sample=sequence([row(i,.9) for i in range(3)])[-1]
        frozen={'snapshot_id':sample.pk,'asset_id':'asset','environment_id':'env','window_start':sample.window_start.isoformat(),'window_end':sample.window_end.isoformat(),'created_at':sample.window_end.isoformat(),'payload':sample.payload,'evaluation':sample.evaluation}
        reader=SimpleNamespace(hardware_input=lambda _:frozen)
        for age,expected in ((180,'FAIL'),(181,'UNKNOWN')):
            frozen['frozen_at']=(sample.window_end+timedelta(seconds=age)).isoformat()
            self.assertEqual(check_hardware_health(reader=reader,assets=[asset],config={})[0].status,expected)
        frozen['evaluation']=deepcopy(sample.evaluation);frozen['evaluation']['plugin']={'id':'gpu-host-health','version':'1.0.0'}
        frozen['frozen_at']=(sample.window_end+timedelta(seconds=300)).isoformat()
        self.assertEqual(check_hardware_health(reader=reader,assets=[asset],config={})[0].status,'FAIL')

    def test_schema_explicit_linux_and_180_seconds_without_unit_conversion(self):
        from apps.hardware_health.schemas import parse_request
        from apps.api.http import APIRequestError
        sample=row(0)
        raw=deepcopy(sample.payload);raw.update(environment_id='fixture-env',sample_id='fixture',window_start=sample.window_start.isoformat(),window_end=sample.window_end.isoformat())
        raw['metrics']['host']['values']['memory_available_bytes']['value']=4194304
        with patch('apps.hardware_health.schemas.timezone.now',return_value=sample.window_end+timedelta(seconds=180)):
            self.assertEqual(parse_request(raw)[0]['metrics']['host']['values']['memory_available_bytes']['value'],4194304)
        with patch('apps.hardware_health.schemas.timezone.now',return_value=sample.window_end+timedelta(seconds=181)):
            with self.assertRaises(APIRequestError):parse_request(raw)
        bad=deepcopy(raw);bad['host_semantics']['memory_available']='free+inactive'
        with patch('apps.hardware_health.schemas.timezone.now',return_value=sample.window_end):
            with self.assertRaises(APIRequestError):parse_request(bad)
            del raw['host_semantics'];self.assertEqual(parse_request(raw)[0]['source'],'controlled-linux-fixture')

    def test_retention_cutoff_and_freshness_versions(self):
        now=BASE+timedelta(days=40)
        samples=[row(1,at=now-timedelta(days=30,seconds=1)),row(2,at=now-timedelta(days=30)),row(3,at=now)]
        self.assertEqual(retention_candidates(samples,as_of=now),['1'])
        self.assertEqual(freshness_seconds({'plugin':HOST_PLUGIN}),180)
        self.assertEqual(freshness_seconds({'plugin':{'id':'gpu-host-health','version':'1.0.0'}}),300)
        self.assertEqual(drift([67,67,67],[60]*8,5.,relative=.05)['status'],'WARNING')


if __name__=='__main__': unittest.main()


def bound_load(sample):
    sample.payload['bindings']={'complete':True,'engines':[{'engine_id':'engine','engine_type':'vllm','model_name':'model'}]}
    sample.payload['_inference']=[{'metrics':{'traffic':{'qps':10},'throughput':{'prompt_tps':100,'generation_tps':100},'requests':{'running':10,'waiting':0},'cache':{'kv_cache_hit_rate':.5},'tpot':{'p95_ms':10}},'evaluation':{'status':'NORMAL'}}]
    return sample


class CpuDriftTests(unittest.TestCase):
    def test_paths_each_require_three_full_points_and_effect_equality(self):
        self.assertEqual(cpu_deviation([.5,.5],[.1]*30)['status'],'PENDING')
        direct=cpu_deviation([.5,.5,.5],[.1]*30)
        self.assertIn('DIRECT',direct['branches'])
        self.assertEqual(cpu_deviation([.2]*3,[0.]*30)['cusum_confirmation_points'],2)
        self.assertIn('CUSUM',cpu_deviation([.2]*4,[0.]*30)['branches'])
        self.assertEqual(cpu_deviation([.1999]*12,[0.]*30)['status'],'NORMAL')
        self.assertEqual(cpu_deviation([.5]*3,[.1]*29)['status'],'NOT_READY')
        self.assertNotEqual(cpu_deviation([.5,-.5,.5],[0.]*30)['status'],'WARNING')

    def test_cusum_needs_twelve_points_without_direct_wave_gate(self):
        baseline=[.1652,.3,.4348]*10
        self.assertNotEqual(cpu_deviation([.5]*11,baseline)['status'],'WARNING')
        result=cpu_deviation([.5]*12,baseline)
        self.assertEqual(set(result['branches']),{'CUSUM'})
        self.assertEqual(result['cusum_confirmation_points'],3)
        self.assertAlmostEqual(result['branches']['CUSUM']['threshold'],.2)
        self.assertGreater(3*result['robust_scale'],.5-result['baseline_median'])
        samples=[bound_load(row(i,[.1652,.3,.4348][i%3])) for i in range(60)]
        samples += [bound_load(row(i,.5)) for i in range(60,72)]
        result=sequence(samples)[-1].evaluation['diagnostics']['host/cpu_busy_ratio']
        self.assertEqual((result['status'],result['series_points']),('WARNING',12))
        self.assertEqual(set(result['branches']),{'CUSUM'})

    def test_freezes_branch_thresholds_and_missing_cannot_recover(self):
        samples=[bound_load(row(i,[.24,.3,.36][i%3])) for i in range(60)]+[bound_load(row(i,1.)) for i in range(60,63)]
        samples=sequence(samples);issue=next(x for x in samples[-1].evaluation['issues'] if x['key']=='host/cpu_busy_ratio')
        eid=issue['event_id'];event=deepcopy(samples[-1].evaluation['host_rule_events'][eid])
        self.assertEqual(set(event['branches']),{'DIRECT','CUSUM'})
        self.assertEqual(event['branches']['CUSUM']['threshold'],.2)
        self.assertGreater(event['branches']['DIRECT']['threshold'],.2)
        for i in range(63,68):
            item=bound_load(row(i,.45));item.evaluation=evaluate(item,samples);samples.append(item)
        self.assertEqual(samples[-1].evaluation['host_rule_events'][eid]['status'],'ACTIVE')
        for i in range(68,72):
            item=bound_load(row(i,.44));item.evaluation=evaluate(item,samples);samples.append(item)
        missing=bound_load(row(72,quality='MISSING'));missing.evaluation=evaluate(missing,samples);samples.append(missing)
        self.assertEqual(missing.evaluation['host_rule_events'][eid]['status'],'ACTIVE')
        for i in range(73,78):
            item=bound_load(row(i,.44));item.evaluation=evaluate(item,samples);samples.append(item)
        final=samples[-1].evaluation['host_rule_events'][eid]
        self.assertEqual(final['status'],'RECOVERED')
        self.assertEqual(final['branches'],event['branches'])
        self.assertTrue(static_event_recovered(samples[-1].evaluation,issue,BASE+timedelta(seconds=72*60)))

    def test_filesystem_reserve_uses_ten_percent_with_approved_decline_window(self):
        samples=[row(i) for i in range(11)]
        for i,sample in enumerate(samples):
            end=sample.window_end.isoformat()
            sample.payload['metrics']['filesystem:root']={'identity':{'filesystem':'ext4','mountpoint':'/','block_device':'dev0'},'values':{'available_bytes':{'value':100000000-i*2000000,'quality':'VALID','collected_at':end},'size_bytes':{'value':200000000,'quality':'VALID','collected_at':end}}}
        result=sequence(samples)[-1].evaluation['diagnostics']['filesystem:root/decline']
        self.assertEqual(result['reserve_bytes'],20000000)
        self.assertEqual(result['sample_count'],11)
        self.assertGreater(result['seconds_to_reserve'],0)

    def test_history_horizon_load_and_missing_break_confirmation(self):
        samples=[bound_load(row(i,.1)) for i in range(60)]+[bound_load(row(i,.5)) for i in range(60,63)]
        samples[-2].payload['metrics']['host']['values']['cpu_busy_ratio'].update(value=None,quality='MISSING')
        self.assertNotEqual(sequence(samples)[-1].evaluation['diagnostics']['host/cpu_busy_ratio']['status'],'WARNING')
        samples[-1].payload['_inference'][0]['metrics']['traffic']['qps']=100
        self.assertEqual(evaluate(samples[-1],samples[:-1])['diagnostics']['host/cpu_busy_ratio']['status'],'NOT_READY')
        old=[bound_load(row(i,.1,at=BASE-timedelta(days=15)+timedelta(seconds=i*60))) for i in range(60)]
        now=bound_load(row(0,.5))
        self.assertEqual(evaluate(now,old)['diagnostics']['host/cpu_busy_ratio']['sample_count'],0)
