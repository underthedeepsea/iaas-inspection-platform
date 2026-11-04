"""New portrait contract, pure fixed records; no DB, network, samples or evaluation."""
from copy import deepcopy
from datetime import timedelta
import unittest
from apps.hardware_health.performance_profile import build_profile
from tests.performance_profile.test_projection import NOW,asset,hw,cluster

def project(assets,rows,llm=(),**options):
    return build_profile(assets,rows,list(llm),now=NOW,portrait_mode=True,**options)
def llm(source='prom',key='l',i=0,value=10):
    return {'id':source+str(i),'asset_id':key,'source':source,'engine_id':'engine/encoded','engine_type':'vllm','model_name':'org/model','start':NOW+timedelta(seconds=i*60-60),'end':NOW+timedelta(seconds=i*60),'metrics':{'ttft':{'p95_ms':value}},'evaluation':{}}
class PortraitTests(unittest.TestCase):
    def test_default_stays_byte_equal_and_series_only_on_selected_detail(self):
        rows=[hw('one',i) for i in (-2,-1,0)]+[hw('two')];assets=[cluster(),asset('one'),asset('two')]
        original=deepcopy((assets,rows));legacy=build_profile(assets,rows,[],now=NOW)
        listing=project(assets,rows)
        for before,after in zip(legacy['nodes'],listing['nodes']):self.assertEqual(before['metrics'],after['metrics'])
        detail=project(assets,rows,detail_kind='node',detail_id='one')
        self.assertEqual(len(detail['nodes'][0]['metrics'][0]['series']),3)
        self.assertNotIn('series',detail['nodes'][1]['metrics'][0])
        self.assertEqual(original,(assets,rows))
    def test_180_181_and_same_window_different_collection_times_card_chart_match(self):
        for age in (180,181):
            row=hw('one',-2.5);at=NOW-timedelta(seconds=age)
            row['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=at.isoformat()
            data=project([asset('one')],[row],detail_kind='node',detail_id='one');cpu=data['nodes'][0]['metrics'][0]
            point=cpu['series'][0];self.assertEqual(point['at'],cpu['observed_at']);self.assertEqual(point['unit'],cpu['unit']);self.assertEqual(point['value'],cpu['latest_observed'])
            self.assertEqual(point['is_current'],age==180);self.assertEqual(cpu['current'],.5 if age==180 else None)
            self.assertEqual(data['nodes'][0]['metrics'][2]['current'],100)
        one=hw('one');two=deepcopy(one);two['id']='second'
        two['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=(NOW-timedelta(seconds=30)).isoformat()
        points=project([asset('one')],[one,two],detail_kind='node',detail_id='one')['nodes'][0]['metrics'][0]['series']
        self.assertEqual(len({p['at'] for p in points}),2)
    def test_gap_future_context_isolation_and_local_missing(self):
        rows=[hw('one',-3,source='other'),hw('one',-2),hw('one',-1),hw('one')]
        rows[2]['payload']['metrics']['host']['values']['cpu_busy_ratio'].update(value=None,quality='MISSING')
        rows[-1]['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=(NOW+timedelta(seconds=1)).isoformat()
        result=project([asset('one')],rows,detail_kind='node',detail_id='one')['nodes'][0]
        cpu=result['metrics'][0];self.assertIsNone(cpu['current'])
        self.assertTrue(any(p['value'] is None for p in cpu['series']))
        self.assertTrue(all(p['source']=='collector' for p in cpu['series']))
        self.assertTrue(all(p['at'] is None or p['at']<=NOW.isoformat() for p in cpu['series']))
        self.assertEqual(result['metrics'][2]['current'],100)
        self.assertTrue(all(p['reference_bounds'] is None and p['continuity']=='UNKNOWN' for p in cpu['series']))
    def test_sources_same_legacy_engine_id_have_distinct_portraits_and_missing_assets_listed(self):
        assets=[asset('l',kind='LLM_INSTANCE'),asset('empty',kind='LLM_INSTANCE')]
        result=project(assets,[],[llm('one'),llm('two')]);objects=result['llm']
        self.assertEqual(len(objects),3);self.assertEqual(objects[0]['id'],objects[1]['id']);self.assertNotEqual(objects[0]['portrait_id'],objects[1]['portrait_id'])
        missing=next(o for o in objects if o['asset_id']=='empty');self.assertEqual(missing['freshness'],'MISSING');self.assertTrue(all(m['current'] is None for m in missing['metrics']))
        detail=project(assets,[],[llm('one'),llm('two')],detail_kind='llm',detail_id=objects[0]['portrait_id'])
        p=detail['llm'][0]['metrics'][0]['series'][0];self.assertEqual(p['source'],'one');self.assertIsNone(p['collected_at']);self.assertEqual(p['value_kind'],'WINDOW_STATISTIC');self.assertEqual(p['window_end'],NOW.isoformat());self.assertNotIn('series',detail['llm'][1]['metrics'][0])
    def test_real_point_cutoff_in_valid_60_second_window_matches_original_summary(self):
        cutoff=NOW-timedelta(days=14)
        for delta,expected in [(-15,False),(-1,False),(0,True)]:
            edge=hw('one');edge['id']='edge';edge['start']=cutoff-timedelta(seconds=30);edge['end']=cutoff+timedelta(seconds=30)
            for component in edge['payload']['metrics'].values():
                for value in component['values'].values():value['collected_at']=edge['end'].isoformat()
            at=cutoff+timedelta(seconds=delta)
            edge['payload']['metrics']['host']['values']['cpu_busy_ratio']['collected_at']=at.isoformat()
            self.assertTrue(edge['start']<=at<=edge['end'])
            self.assertTrue(0<=(edge['end']-at).total_seconds()<=180)
            metric=project([asset('one')],[edge,hw('one')],detail_kind='node',detail_id='one')['nodes'][0]['metrics'][0]
            self.assertEqual(any(point['snapshot_id']=='edge' for point in metric['series']),expected)
            self.assertEqual(metric['history']['n'],1 if expected else 0)
            self.assertEqual(metric['current'],.5)
            self.assertTrue(all(point['at'] is None or cutoff.isoformat()<=point['at']<=NOW.isoformat() for point in metric['series']))

    def test_bounded_series_preserves_invalid_markers_and_declares_truncation(self):
        rows=[hw('one',-i) for i in range(1005)]
        data=project([asset('one')],rows,detail_kind='node',detail_id='one')
        metric=data['nodes'][0]['metrics'][0]
        self.assertEqual(len(metric['series']),1000)
        self.assertTrue(metric['series_truncated'])
        self.assertTrue(metric['series'][-1]['is_current'])
        self.assertEqual(metric['series'][-1]['value'],metric['current'])

    def test_cluster_dedup_weights_unchanged_and_no_fabricated_series(self):
        assets=[cluster(),asset('one',cores=2,host='x',roles=['ETCD']),asset('duplicate',cores=2,host='x',roles=['API_SERVER']),asset('two',cores=6)]
        rows=[hw('one',cpu=.2,host='x'),hw('duplicate',cpu=.2,host='x'),hw('two',cpu=.8)]
        result=project(assets,rows,detail_kind='cluster',detail_id='cluster');group=result['clusters'][0]['total']
        self.assertEqual(group['node_count'],2);self.assertAlmostEqual(group['metrics'][0]['current'],.65)
        self.assertTrue(all(m['series']==[] for m in group['metrics']))
        self.assertEqual(len(result['clusters'][0]['relationships']),2)
