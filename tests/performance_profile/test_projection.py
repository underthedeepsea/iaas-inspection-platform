"""Pure controlled records; no DB, HTTP or real telemetry."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from apps.hardware_health.performance_profile import build_profile, LINUX_MEMORY

NOW=datetime(2026,10,29,4,tzinfo=timezone.utc)

def asset(key, *, kind='HOST', host=None, roles=None, cores=4, parent='cluster', env='env'):
    return {'id':key,'environment_id':env,'asset_type':kind,'name':key,'external_key':key,'parent_id':parent,
            'labels':{'host_id':host or key,'roles':roles or ['WORKER'],'cpu_cores':cores},'topology':{}}

def hw(key, i=0, cpu=.5, *, total=100, available=50, host=None, linux=True, source='collector', config='cfg'):
    end=NOW+timedelta(seconds=i*60)
    def p(v):return {'quality':'VALID','value':v,'collected_at':end.isoformat()}
    return {'id':key+str(i),'asset_id':key,'source':source,'start':end-timedelta(seconds=60),'end':end,'evaluation':{},
            'payload':{'host_id':host or key,'source':source,'config_id':config,'identity':{},'host_semantics':deepcopy(LINUX_MEMORY) if linux else None,
                       'metrics':{'host':{'values':{'cpu_busy_ratio':p(cpu),'memory_total_bytes':p(total),'memory_available_bytes':p(available)}},'disk:sda':{'values':{'io_busy_ratio':p(.8),'read_bytes_per_second':p(10),'write_bytes_per_second':p(20)}}}}}

def project(assets, rows, llm=()):return build_profile(assets,rows,list(llm),now=NOW)
def cluster():return asset('cluster',kind='CLUSTER',parent=None)

class ProfileTests(unittest.TestCase):
    def test_mixed_same_stable_identity_counted_once_with_both_roles(self):
        c=cluster();c['labels']['control_plane_deployment']='MIXED'
        assets=[c,asset('api',host='node',roles=['API_SERVER']),asset('etcd',host='node',roles=['ETCD'])]
        result=project(assets,[hw('api',host='node'),hw('etcd',host='node')])
        self.assertEqual(result['clusters'][0]['total']['node_count'],1)
        self.assertEqual(result['nodes'][0]['roles'],['API_SERVER','ETCD'])
        self.assertEqual([g['node_count'] for g in result['clusters'][0]['groups']],[0,0,1,0,0])
        self.assertEqual(len(result['clusters'][0]['shared_nodes']),1)
    def test_dedicated_and_partial_mixed_respect_actual_roles(self):
        for mode in ['MIXED','DEDICATED']:
            c=cluster();c['labels']['control_plane_deployment']=mode
            result=project([c,asset('one',roles=['API_SERVER','ETCD']),asset('two',roles=['ETCD'])],[hw('one'),hw('two')])
            self.assertEqual(result['clusters'][0]['total']['node_count'],2)
            self.assertEqual([g['node_count'] for g in result['clusters'][0]['groups']],[0,1,1,0,0])
        result=project([cluster(),asset('one',roles=['API_SERVER']),asset('two',roles=['ETCD'])],[hw('one'),hw('two')])
        self.assertEqual(result['clusters'][0]['total']['node_count'],2)
        self.assertEqual([g['node_count'] for g in result['clusters'][0]['groups']],[1,1,0,0,0])
        self.assertEqual(result['clusters'][0]['control_plane_deployment'],'UNKNOWN')
    def test_capacity_weighting_with_different_specs(self):
        result=project([cluster(),asset('one',cores=2),asset('two',cores=6)],[hw('one',cpu=.2,total=100,available=50),hw('two',cpu=.8,total=300,available=60)])
        m=result['clusters'][0]['total']['metrics']
        self.assertAlmostEqual(m[0]['current'],.65)
        self.assertAlmostEqual(m[1]['current'],.725)
        self.assertAlmostEqual(m[2]['current'],.275)
    def test_missing_weights_only_blocks_corresponding_aggregate(self):
        result=project([cluster(),asset('one',cores=None),asset('two')],[hw('one'),hw('two')])
        metrics=result['clusters'][0]['total']['metrics']
        self.assertIsNone(metrics[0]['current']);self.assertEqual(metrics[1]['current'],.5)
        self.assertEqual(result['nodes'][0]['metrics'][0]['current'],.5)
    def test_no_binding_or_component_qps_needed_for_basics(self):
        result=project([asset('node')],[hw('node')])
        self.assertEqual(result['nodes'][0]['metrics'][0]['current'],.5)
        self.assertEqual(result['llm'],[])
        self.assertTrue(result['nodes'][0]['metrics'][-1]['current'] is not None)
    def test_stale_mac_memory_cannot_be_linux_or_current_cluster(self):
        result=project([cluster(),asset('node')],[hw('node',-10,linux=False)])
        node=result['nodes'][0]
        self.assertEqual(node['freshness'],'STALE');self.assertEqual(node['memory_semantics'],'SOURCE_REPORTED_NOT_LINUX_MEMAVAILABLE')
        self.assertIsNone(node['metrics'][1]['current']);self.assertEqual(node['metrics'][1]['latest_observed'],50)
        self.assertTrue(all(m['current'] is None for m in result['clusters'][0]['total']['metrics']))
        self.assertEqual(node['frozen_diagnostics'],{})
    def test_two_preceding_observations_required_and_source_config_do_not_mix(self):
        rows=[hw('node',-4,.1,config='other'),hw('node',-3,.2,source='other'),hw('node',-2,.3),hw('node',-1,.5),hw('node',0,.6)]
        metric=project([asset('node')],rows)['nodes'][0]['metrics'][0]
        self.assertEqual(metric['history']['n'],2);self.assertAlmostEqual(metric['history']['median'],.4)
        self.assertAlmostEqual(metric['difference'],.2)
        self.assertIn('historical_roles',metric['missing_context'])
        only_one=project([asset('node')],rows[-2:])['nodes'][0]['metrics'][0]
        self.assertIsNone(only_one['history']['min']);self.assertIsNone(only_one['difference'])
    def test_mutable_labels_cannot_reconstruct_historical_configuration(self):
        a=asset('node');a['labels'].update(quantization='int4',model_version='v9',roles=['ETCD'])
        result=project([a],[hw('node',-2),hw('node',-1),hw('node')])['nodes'][0]
        self.assertNotIn('roles',result['context']);self.assertIn('historical_roles',result['missing_context'])
        self.assertNotIn('model_version',result['context'])
    def test_llm_window_p95_and_item_coverage_remain_explicit(self):
        rows=[{'id':str(i),'source':'prom','engine_id':'engine','engine_type':'vllm','model_name':'model','start':NOW+timedelta(seconds=i*60-60),'end':NOW+timedelta(seconds=i*60),'metrics':{'ttft':{'p95_ms':value}},'evaluation':{}} for i,value in [(-2,10),(-1,100),(0,50)]]
        result=project([],[],rows)['llm'][0]
        self.assertEqual(result['metrics'][0]['history']['median'],55)
        self.assertIn('窗口p95',result['metrics'][0]['label'])
        self.assertIn('quantization',result['missing_context']);self.assertIsNone(result['metrics'][1]['current'])
        self.assertEqual(result['metrics'][1]['history']['n'],0)
        self.assertIn('不是总体请求p95',result['note'])
    def test_io_percent_and_p95_are_not_aggregated(self):
        result=project([cluster(),asset('one'),asset('two')],[hw('one'),hw('two')])
        self.assertFalse(any('io_busy' in m['key'].split('.')[-1] or 'p95' in m['key'] for m in result['clusters'][0]['total']['metrics']))
        self.assertEqual(len([m for n in result['nodes'] for m in n['metrics'] if 'io_busy_ratio' in m['key']]),2)
    def test_unaligned_or_missing_nodes_do_not_form_current_total(self):
        for rows in [[hw('one'),hw('two',-1)],[hw('one')]]:
            result=project([cluster(),asset('one'),asset('two')],rows)
            self.assertTrue(all(m['current'] is None for m in result['clusters'][0]['total']['metrics']))
        self.assertEqual(len(result['nodes'][1]['metrics']),3)
    def test_cluster_memory_history_uses_frozen_capacity_without_averaging_ratios(self):
        rows=[hw(node,i,total=total,available=available) for node,total,available in [('one',100,50),('two',300,60)] for i in [-2,-1,0]]
        result=project([cluster(),asset('one'),asset('two')],rows)['clusters'][0]['total']['metrics']
        self.assertEqual(result[0]['history']['n'],0)
        self.assertEqual(result[1]['history']['n'],2);self.assertAlmostEqual(result[1]['history']['median'],.725)
    def test_frozen_diagnostics_not_recomputed_and_input_unchanged(self):
        row=hw('node');row['evaluation']={'plugin':{'id':'gpu-host-health','version':'2.0.0'},'diagnostics':{'host/cpu_static':{'status':'WARNING'}},'status':'NORMAL'}
        before=deepcopy(row);result=project([asset('node')],[row])
        self.assertEqual(row,before);self.assertEqual(result['nodes'][0]['frozen_diagnostics'],row['evaluation']['diagnostics'])
        self.assertNotIn('status',result['nodes'][0])

class FreshnessTests(unittest.TestCase):
    def test_actual_point_180_boundary_missing_time_and_210_150_counterexample(self):
        for age,expected in [(180,.5),(180.001,None),(210,None)]:
            row=hw('node',-2.5);when=NOW-timedelta(seconds=age)
            row['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=when.isoformat()
            result=project([asset('node')],[row])['nodes'][0];metric=result['metrics'][0]
            self.assertEqual(metric['current'],expected);self.assertEqual(metric['latest_observed'],.5)
            self.assertEqual(metric['observed_at'],when.isoformat());self.assertEqual(metric['collected_at'],when.isoformat())
            self.assertEqual(result['metrics'][2]['current'],100)
            if expected is None:self.assertEqual(result['freshness'],'MIXED')
        for when in [None,'not-time',NOW.replace(tzinfo=None).isoformat()]:
            row=hw('node');row['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=when
            metric=project([asset('node')],[row])['nodes'][0]['metrics'][0]
            self.assertIsNone(metric['current']);self.assertIsNone(metric['observed_at']);self.assertEqual(metric['latest_observed'],.5)
    def test_old_disk_point_does_not_hide_current_throughput(self):
        row=hw('node',-2.5);row['payload']['metrics']['disk:sda']['values']['io_busy_ratio']['collected_at']=(NOW-timedelta(seconds=210)).isoformat()
        metrics={m['key']:m for m in project([asset('node')],[row])['nodes'][0]['metrics']}
        self.assertIsNone(metrics['disk:sda.io_busy_ratio']['current'])
        self.assertEqual(metrics['disk:sda.io_busy_ratio']['latest_observed'],.8)
        self.assertEqual(metrics['disk:sda.read_bytes_per_second']['current'],10)
    def test_cluster_checks_cpu_and_both_memory_points_independently(self):
        for stale in ['cpu_busy_ratio','memory_total_bytes','memory_available_bytes']:
            rows=[hw('one',-2.5),hw('two',-2.5)]
            rows[0]['payload']['metrics']['host']['values'][stale]['collected_at']=(NOW-timedelta(seconds=210)).isoformat()
            metrics=project([cluster(),asset('one'),asset('two')],rows)['clusters'][0]['total']['metrics']
            self.assertEqual(metrics[0]['current'],None if stale=='cpu_busy_ratio' else .5)
            self.assertEqual(metrics[1]['current'],.5 if stale=='cpu_busy_ratio' else None)
            self.assertEqual(metrics[2]['current'],.5 if stale=='cpu_busy_ratio' else None)
            target=metrics[0] if stale=='cpu_busy_ratio' else metrics[1]
            self.assertEqual(target['latest_observed'],.5)
            self.assertIn((NOW-timedelta(seconds=210)).isoformat(),target['participating_collected_at'])
    def test_history_uses_real_point_times_but_excludes_latest_window(self):
        rows=[hw('node',i,cpu=value) for i,value in [(-2,.1),(-1,.2),(0,.3)]]
        for row in rows:row['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=(row['end']-timedelta(seconds=30)).isoformat()
        metric=project([asset('node')],rows)['nodes'][0]['metrics'][0]
        self.assertEqual(metric['history']['n'],2)
        self.assertEqual(metric['history']['start'],(NOW-timedelta(seconds=150)).isoformat())
        self.assertEqual(metric['history']['end'],(NOW-timedelta(seconds=90)).isoformat())
        self.assertEqual(metric['high_observation']['at'],(NOW-timedelta(seconds=30)).isoformat())
    def test_llm_is_explicit_window_statistic_with_180_second_age(self):
        row={'id':'llm','source':'prom','engine_id':'e','engine_type':'vllm','model_name':'m','start':NOW-timedelta(seconds=240),'end':NOW-timedelta(seconds=180),'metrics':{'ttft':{'p95_ms':10}},'evaluation':{'resolved_policy':{'quality':{'max_age_seconds':300}}}}
        result=project([],[],[row])['llm'][0];metric=result['metrics'][0]
        self.assertEqual(metric['value_kind'],'WINDOW_STATISTIC');self.assertEqual(metric['state'],'CURRENT_WINDOW_STATISTIC')
        self.assertIsNone(metric['collected_at']);self.assertEqual(metric['current'],10)
        self.assertEqual(metric['window_start'],row['start'].isoformat());self.assertEqual(metric['window_end'],row['end'].isoformat())
        row['end']=NOW-timedelta(seconds=181)
        self.assertIsNone(project([],[],[row])['llm'][0]['metrics'][0]['current'])
        row['start']=None
        metric=project([],[],[row])['llm'][0]['metrics'][0]
        self.assertIsNone(metric['current']);self.assertIsNone(metric['observed_at']);self.assertEqual(metric['latest_observed'],10)

if __name__=='__main__':unittest.main()
