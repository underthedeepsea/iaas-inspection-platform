"""Offline contracts for presenting frozen decisions, not re-running policy."""
from copy import deepcopy
from datetime import timedelta
import unittest
from apps.hardware_health.performance_profile import build_profile, HOST_PLUGIN
from tests.performance_profile.test_projection import NOW, asset, hw, cluster


def frozen(key, level='NORMAL'):
    row = hw(key, cpu=.95 if level == 'CRITICAL' else .85 if level == 'WARNING' else .5)
    context = {k: row['payload'].get(k) for k in ('source','config_id','host_id','identity','host_semantics')}
    diagnostics = {component+'/'+metric: {'status':'NORMAL','current':point['value']} for component,body in row['payload']['metrics'].items() for metric,point in body['values'].items()}
    for rule, current in [('host/cpu_static', row['payload']['metrics']['host']['values']['cpu_busy_ratio']['value']), ('host/memory_static',.5), ('host/cpu_busy_ratio',row['payload']['metrics']['host']['values']['cpu_busy_ratio']['value'])]:
        status = level if rule == 'host/cpu_static' else 'NORMAL'
        diagnostics[rule] = {'rule_id':rule,'rule_version':'2.0.0','rule':{'direction':'HIGH','warning':.8,'critical':.9} if rule.endswith('_static') else {},'status':status,'state':status,'current':current,'unit':'ratio','context':deepcopy(context),'frozen_context':deepcopy(context) if status != 'NORMAL' else None,'window_start':row['start'].isoformat(),'window_end':row['end'].isoformat(),'last_collected_at':row['end'].isoformat(),'confirmation_required':3,'confirmation_points':3 if status != 'NORMAL' else 0,'trigger_window_seconds':120,'reason':'CONFIRMED_STATIC_LIMIT' if status != 'NORMAL' else 'STATIC_LIMIT_NOT_REACHED'}
    diagnostics['host/decline']={'status':'NORMAL'}
    row['evaluation']={'plugin':deepcopy(HOST_PLUGIN),'diagnostics':diagnostics,'coverage':{'host':'READY','disk:sda':'READY'}}
    return row


def profile(assets, rows): return build_profile(assets, rows, [], now=NOW)


class ControlRiskTests(unittest.TestCase):
    def test_one_critical_among_99_normal_is_one_host_not_average(self):
        assets=[cluster()]+[asset(str(i),roles=['API_SERVER']) for i in range(100)]
        result=profile(assets,[frozen(str(i),'CRITICAL' if i==0 else 'NORMAL') for i in range(100)])
        summary=result['clusters'][0]['classified']['risk']
        self.assertEqual(summary['counts'],{'CRITICAL':1,'WARNING':0,'UNKNOWN':0,'NORMAL':99})
        self.assertEqual(summary['risk_hosts'],1);self.assertEqual(summary['coverage'],{'covered':100,'total':100})
        self.assertEqual(result['nodes'][0]['risk']['triggers'][0]['confirmation_points'],3)
        self.assertNotIn('duration',result['nodes'][0]['risk']); self.assertNotIn('started_at',result['nodes'][0]['risk'])

    def test_two_triggers_one_host_and_partial_gaps_keep_highest_risk(self):
        for level in ['CRITICAL','WARNING']:
            row=frozen('one',level)
            memory=row['evaluation']['diagnostics']['host/memory_static'];memory.update(status='WARNING',state='WARNING',confirmation_points=3,frozen_context=deepcopy(memory['context']),reason='CONFIRMED_STATIC_LIMIT')
            risk=profile([cluster(),asset('one',roles=['API_SERVER'])],[row])['clusters'][0]['classified']['risk']
            self.assertEqual(risk['risk_hosts'],1)
            self.assertEqual(len(profile([asset('one')],[row])['nodes'][0]['risk']['triggers']),2)
            row['payload']['metrics']['disk:sda']['values']['io_busy_ratio'].update(value=None,quality='MISSING')
            result=profile([cluster(),asset('one',roles=['API_SERVER'])],[row]);risk=result['nodes'][0]['risk']
            self.assertEqual(risk['level'],level);self.assertTrue(risk['incomplete'])
            self.assertEqual(result['clusters'][0]['classified']['risk']['coverage']['covered'],0)
            self.assertEqual(result['clusters'][0]['classified']['risk']['metric_coverage']['disk:sda/io_busy_ratio']['covered'],0)
            self.assertEqual(result['clusters'][0]['classified']['risk']['metric_coverage']['host/cpu_static']['covered'],1)

    def test_no_evidence_pending_stale_bad_window_and_old_plugin_never_normal_or_current_risk(self):
        for change in ['none','stale','window','plugin','point','context','confirm','reason']:
            row=frozen('one','CRITICAL')
            if change=='none':row['evaluation']={}
            if change=='stale':row['end']=NOW-timedelta(seconds=181);row['start']=row['end']-timedelta(seconds=60)
            if change=='window':row['evaluation']['diagnostics']['host/cpu_static']['window_end']=(NOW-timedelta(seconds=60)).isoformat()
            if change=='plugin':row['evaluation']['plugin']['version']='1.0.0'
            if change=='point':row['payload']['metrics']['host']['values']['cpu_busy_ratio']['quality']='MISSING'
            if change=='context':row['evaluation']['diagnostics']['host/cpu_static']['frozen_context']={}
            if change=='confirm':row['evaluation']['diagnostics']['host/cpu_static']['confirmation_points']=1
            if change=='reason':row['evaluation']['diagnostics']['host/cpu_static']['reason']='EVENT_CONTEXT_MISMATCH'
            risk=profile([asset('one')],[row])['nodes'][0]['risk']
            self.assertEqual(risk['level'],'UNKNOWN',change);self.assertTrue(risk['missing'])
        row=frozen('one');row['evaluation']['diagnostics']['host/cpu_busy_ratio']['status']='PENDING'
        self.assertEqual(profile([asset('one')],[row])['nodes'][0]['risk']['level'],'UNKNOWN')

    def test_active_event_retains_confirmed_state_during_recovery_but_rejects_other_context(self):
        row=frozen('one','WARNING');d=row['evaluation']['diagnostics']['host/cpu_static']
        d.update(confirmation_points=0,reason='RECOVERY_PENDING',event_id='event')
        row['evaluation']['host_rule_events']={'event':{'status':'ACTIVE','rule_key':d['rule_id'],'rule_version':d['rule_version'],'frozen_rule':deepcopy(d['rule']),'frozen_context':deepcopy(d['context'])}}
        self.assertEqual(profile([asset('one')],[row])['nodes'][0]['risk']['level'],'WARNING')
        row['evaluation']['host_rule_events']['event']['frozen_context']={}
        self.assertEqual(profile([asset('one')],[row])['nodes'][0]['risk']['level'],'UNKNOWN')

    def test_exclusive_environment_identity_unknown_other_and_total_scope(self):
        assets=[cluster(),asset('api',roles=['API_SERVER','WORKER']),asset('duplicate',host='api',roles=['ETCD']),asset('etcd',roles=['ETCD','WORKER']),asset('worker'),asset('unknown',roles=['UNKNOWN']),asset('foreign',env='other',host='api',roles=['API_SERVER'])]
        result=profile(assets,[frozen('api'),hw('duplicate',host='api'),frozen('etcd'),frozen('worker')]);c=result['clusters'][0]
        self.assertEqual(c['total']['node_count'],4);self.assertEqual(c['classified']['node_count'],2)
        self.assertEqual([g['node_count'] for g in c['groups']],[0,1,1,1,1])
        self.assertEqual(len(result['nodes']),5)
        single=profile([cluster(),asset('api',roles=['API_SERVER','WORKER'])],[frozen('api')])['clusters'][0]
        self.assertEqual([g['node_count'] for g in single['groups']],[1,0,0,0,0])
        self.assertEqual(single['classified']['node_count'],1)

    def test_classified_metrics_keep_null_window_and_original_total(self):
        rows=[frozen('api'),frozen('worker')];rows[0]['payload']['metrics']['host']['values']['memory_total_bytes']['quality']='MISSING'
        c=profile([cluster(),asset('api',roles=['API_SERVER']),asset('worker')],rows)['clusters'][0]
        self.assertEqual(c['total']['node_count'],2);self.assertIsNone(c['classified']['metrics'][1]['current'])
        self.assertEqual(c['classified']['metrics'][0]['current'],.5)
        self.assertEqual(c['classified']['metrics'][1]['coverage'],{'covered':0,'total':1})
        shifted=frozen('other');shifted['start']-=timedelta(seconds=60);shifted['end']-=timedelta(seconds=60)
        c=profile([cluster(),asset('api',roles=['API_SERVER']),asset('other',roles=['ETCD'])],[frozen('api'),shifted])['clusters'][0]
        self.assertFalse(c['classified']['window_aligned']);self.assertTrue(all(m['current'] is None for m in c['classified']['metrics']))
