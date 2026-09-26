from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import pytest
from django.core.management import call_command
from django.utils import timezone
from apps.api.http import APIRequestError
from apps.assets.models import Asset
from apps.core.models import Environment
from apps.hardware_health.schemas import FIELDS, parse_request
from apps.hardware_health.services import ingest
from apps.hardware_health.models import HardwareSnapshot
from apps.hardware_health.evaluator import evaluate, drift
from apps.inference_performance.services.ingest import IdempotencyConflict
from apps.inspections.services.trigger import create_manual_inspection_run
from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
from apps.inspections.models import CheckResult, Finding
from apps.risks.models import Risk, Evidence, RiskObservation, RiskStatusHistory
from apps.risks.services.reverify import _valid_hardware_pass

pytestmark=pytest.mark.django_db


def payload(env='hw-test', *, end=None, kind='GPU', sample='sample-1'):
    end=end or timezone.now()-timedelta(seconds=1);start=end-timedelta(minutes=1)
    def point(value): return {'value':value,'quality':'VALID','collected_at':end.isoformat()}
    if kind=='GPU':
        values={'utilization_ratio':.8,'memory_used_bytes':90,'memory_total_bytes':100,'temperature_celsius':60,'xid_events':[],'ecc_sbe_delta':0,'ecc_dbe_delta':0}
        metrics={'gpu':{'identity':{},'values':{k:point(v) for k,v in values.items()}}}
        for key,sem in [('ecc_sbe_delta','SINGLE_BIT'),('ecc_dbe_delta','DOUBLE_BIT')]:
            metrics['gpu']['values'][key].update(source_metric='attested_'+key,semantics=sem,scope='DRAM')
    else:
        metrics={'host':{'identity':{},'values':{k:point(v) for k,v in {'cpu_busy_ratio':.4,'memory_available_bytes':8*1024**3,'memory_total_bytes':16*1024**3}.items()}},
            'filesystem:root':{'identity':{'filesystem':'ext4','mountpoint':'/','block_device':'dev0'},'values':{'available_bytes':point(50*1024**3),'size_bytes':point(100*1024**3)}},
            'disk:root':{'identity':{'block_device':'dev0'},'values':{k:point(.2 if k=='io_busy_ratio' else 10) for k in FIELDS['disk']}}}
    return {'source':'test-monitor','environment_id':env,'sample_id':sample,'window_start':start.isoformat(),'window_end':end.isoformat(),
            'host_id':'host-stable-1','config_id':'config-1','kind':kind,'identity':{'gpu_uuid':'gpu-1','model':'TestGPU'} if kind=='GPU' else {},
            'metrics':metrics,'bindings':{'complete':False,'engines':[]}}


@pytest.fixture
def env(): return Environment.objects.create(name='HW test',slug='hw-test')


def test_schema_requires_quality_semantics_and_event_identity():
    raw=payload(); raw['metrics']['gpu']['values']['ecc_sbe_delta']['semantics']='CORRECTED'
    with pytest.raises(APIRequestError): parse_request(raw)
    raw=payload();raw['metrics']['gpu']['values']['temperature_celsius'].update(quality='UNSUPPORTED',value=0)
    with pytest.raises(APIRequestError): parse_request(raw)
    raw=payload(); raw['metrics']['gpu']['values']['temperature_celsius'].update(quality='UNSUPPORTED',value=None)
    assert parse_request(raw)[0]['metrics']['gpu']['values']['temperature_celsius']['value'] is None


def test_environment_idempotency_and_atomic_batch(client,env):
    raw=payload();one,created=ingest(raw); assert created
    repeated,created=ingest(raw);assert not created and repeated.pk==one.pk
    changed=deepcopy(raw);changed['metrics']['gpu']['values']['temperature_celsius']['value']=65
    with pytest.raises(IdempotencyConflict): ingest(changed)
    other=Environment.objects.create(name='Other',slug='other');raw2=deepcopy(raw);raw2['environment_id']=str(other.pk)
    second,_=ingest(raw2);assert second.asset_id!=one.asset_id
    later=payload(sample='second',end=one.window_end+timedelta(minutes=1))
    # Use older batch timestamps so future-window validation is irrelevant.
    past=payload(sample='past',end=timezone.now()-timedelta(hours=1));past['host_id']='host-2'
    response=client.post('/api/v1/hardware-health/snapshots/batch',{'samples':[past,changed]},content_type='application/json')
    assert response.status_code==409
    assert not HardwareSnapshot.objects.filter(sample_id='past').exists()
    assert HardwareSnapshot.objects.count()==2


def test_dbe_dominates_missing_and_zero_does_not_clear_event(env):
    end=timezone.now()-timedelta(minutes=2)
    raw=payload(end=end);raw['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1
    raw['metrics']['gpu']['values']['temperature_celsius'].update(quality='MISSING',value=None)
    first,_=ingest(raw);assert first.evaluation['status']=='CRITICAL'
    raw2=payload(end=end+timedelta(minutes=1),sample='s2')
    second,_=ingest(raw2);assert second.evaluation['status']=='CRITICAL'
    assert second.evaluation['pending_hardware_events']==first.evaluation['pending_hardware_events']
    assert first.evaluation['quality']['state']=='INCOMPLETE'


def test_xid_window_dedup_and_reset_breaks_sbe_acceleration(env):
    end=timezone.now()-timedelta(minutes=5)
    first=payload(end=end);event={'event_id':'journal-1','code':79,'occurred_at':(end-timedelta(seconds=20)).isoformat()}
    first['metrics']['gpu']['values']['xid_events']['value']=[event]
    row,_=ingest(first);assert row.evaluation['status']=='CRITICAL'
    assert ingest(first)[1] is False
    retry=payload(end=end+timedelta(minutes=1),sample='s2');retry['metrics']['gpu']['values']['xid_events']['value']=[{**event,'occurred_at':(end+timedelta(seconds=20)).isoformat()}]
    with pytest.raises(IdempotencyConflict): ingest(retry)
    reset=payload(end=end+timedelta(minutes=1),sample='reset');reset['metrics']['gpu']['values']['ecc_sbe_delta'].update(quality='RESET',value=None)
    ingest(reset)
    after=payload(end=end+timedelta(minutes=2),sample='after');after['metrics']['gpu']['values']['ecc_sbe_delta']['value']=3
    row,_=ingest(after);assert any(i['code']=='ECC_SBE_OCCASIONAL' for i in row.evaluation['issues'])


def fake_row(raw,index):
    _,start,end=parse_request(raw)
    raw=deepcopy(raw)
    raw['bindings']={'complete':True,'engines':[{'engine_id':'e','engine_type':'vllm','model_name':'m'}]}
    raw['_inference']=[{'metrics':{'traffic':{'qps':10},'throughput':{'prompt_tps':100,'generation_tps':100},'requests':{'running':10,'waiting':0},'cache':{'kv_cache_hit_rate':.5},'tpot':{'p95_ms':10}},'evaluation':{'status':'NORMAL'}}]
    return SimpleNamespace(pk=index,payload=raw,window_start=start,window_end=end,evaluation={})


def test_conditional_drift_below_fixed_threshold_and_preallocation_is_normal():
    end=timezone.now()-timedelta(minutes=30)
    history=[]
    for i in range(18):
        row=fake_row(payload(end=end+timedelta(minutes=i),sample=str(i)),i)
        if i>=12: row.payload['metrics']['gpu']['values']['temperature_celsius']['value']=67
        row.evaluation=evaluate(row,history);history.append(row)
    assert history[-1].evaluation['diagnostics']['gpu/temperature_celsius']['status']=='WARNING'
    assert all(i['key']!='gpu/memory_used_bytes' for i in history[-1].evaluation['issues'])
    steady=[fake_row(payload(end=end+timedelta(minutes=i),sample=str(i)),i) for i in range(18)]
    assert evaluate(steady[-1],steady[:-1])['status']=='NORMAL'
    assert drift([100,102,104,105,106,107], [100]*10, 1,relative=.05)['status']=='WARNING'


def test_output_target_is_not_matched_away_and_different_input_load_not_compared():
    end=timezone.now()-timedelta(minutes=30)
    rows=[fake_row(payload(end=end+timedelta(minutes=i),sample=str(i)),i) for i in range(18)]
    for row in rows[-6:]: row.payload['_inference'][0]['metrics']['throughput']['generation_tps']=60
    result=evaluate(rows[-1],rows[:-1])
    assert any(x['code']=='SUSPECT_GPU_BUSY_OUTPUT_DOWN' for x in result['correlations'])
    rows[-1].payload['_inference'][0]['metrics']['throughput']['prompt_tps']=1000
    result=evaluate(rows[-1],rows[:-1]);assert result['diagnostics']['gpu/output']['status']=='NOT_READY'


def test_capacity_trend_requires_consistency_and_memory_has_no_exhaustion_eta():
    end=timezone.now()-timedelta(minutes=30);rows=[]
    for i in range(12):
        row=fake_row(payload(kind='HOST',end=end+timedelta(minutes=i),sample=str(i)),i)
        row.payload['metrics']['filesystem:root']['values']['available_bytes']['value']=(50-i)*1024**3
        row.payload['metrics']['host']['values']['memory_available_bytes']['value']=(8-i*.1)*1024**3
        rows.append(row)
    result=evaluate(rows[-1],rows[:-1])
    assert result['diagnostics']['filesystem:root/decline']['seconds_to_reserve']>0
    assert 'seconds_to_reserve' not in result['diagnostics']['host/decline']
    rows[-1].payload['metrics']['filesystem:root']['values']['available_bytes']['value']=60*1024**3
    rows[-2].payload['metrics']['filesystem:root']['values']['available_bytes']['value']=55*1024**3
    assert 'seconds_to_reserve' not in evaluate(rows[-1],rows[:-1])['diagnostics']['filesystem:root/decline']


def test_formal_run_freezes_evidence_and_duplicate_execution(env):
    call_command('seed_launch')
    raw=payload(end=timezone.now()-timedelta(minutes=2));raw['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1
    first,_=ingest(raw)
    run=create_manual_inspection_run(environment=env,resource_type_codes=['GPU_POOL','HOST'])
    later=payload(sample='later',end=first.window_end+timedelta(minutes=1));ingest(later)
    result=start_manual_inspection_run(run.pk)
    check=CheckResult.objects.get(inspection_run=run,asset=first.asset)
    assert check.evidence['snapshot_id']==str(first.pk) and check.status=='FAIL'
    assert Evidence.objects.get(inspection_run=run).source=='hardware_snapshot'
    before=(CheckResult.objects.count(),Finding.objects.count(),RiskObservation.objects.count())
    start_manual_inspection_run(run.pk)
    assert before==(CheckResult.objects.count(),Finding.objects.count(),RiskObservation.objects.count())
    assert result.status=='SUCCEEDED'


def test_gpu_assets_are_separate_and_host_missing_component_is_unknown(env):
    raw=payload();one,_=ingest(raw)
    two=deepcopy(raw);two['sample_id']='gpu2';two['identity']['gpu_uuid']='gpu-2';second,_=ingest(two)
    assert one.asset_id!=second.asset_id
    end=timezone.now()-timedelta(minutes=2)
    host=payload(kind='HOST',end=end,sample='host');ingest(host)
    later=payload(kind='HOST',end=end+timedelta(minutes=1),sample='host2');del later['metrics']['disk:root']
    result,_=ingest(later);assert result.evaluation['status']=='UNKNOWN'
    assert result.evaluation['coverage']['disk:root']=='MISSING_OR_REPLACED'


def test_mixed_run_freezes_each_source_and_isolation(env):
    from apps.inference_performance.schemas import parse_snapshot_request
    from apps.inference_performance.services.ingest import ingest_snapshot
    from tests.inference_performance.helpers import payload as inference_payload
    call_command('seed_launch');end=timezone.now()-timedelta(minutes=2)
    llm,_=ingest_snapshot(parse_snapshot_request(inference_payload(str(env.pk),end=end)))
    raw=payload(end=end);raw['bindings']={'complete':True,'engines':[{'engine_id':llm.engine_id,'engine_type':llm.engine_type,'model_name':llm.model_name}]}
    gpu,_=ingest(raw)
    run=create_manual_inspection_run(environment=env,resource_type_codes=['LLM_RUNTIME','GPU_POOL'])
    assert run.config_snapshot['input']['source_type']=='EXTERNAL_SNAPSHOTS'
    frozen=deepcopy(run.config_snapshot['input'])
    later=payload(sample='next',end=end+timedelta(minutes=1));later['bindings']=raw['bindings'];later['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1
    ingest(later)
    start_manual_inspection_run(run.pk);run.refresh_from_db()
    assert run.config_snapshot['input']==frozen
    assert CheckResult.objects.filter(inspection_run=run).count()==2
    assert CheckResult.objects.get(inspection_run=run,asset=gpu.asset).status=='PASS'
    assert CheckResult.objects.get(inspection_run=run,asset=llm.asset).evidence['snapshot_id']==str(llm.pk)


def test_hardware_reverification_requires_post_handling_evidence_and_all_dimensions(env):
    from apps.risks.services.lifecycle import mark_handled
    call_command('seed_launch');end=timezone.now()-timedelta(minutes=4)
    raw=payload(end=end);raw['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1
    first,_=ingest(raw);run=create_manual_inspection_run(environment=env,resource_type_codes=['GPU_POOL']);start_manual_inspection_run(run.pk)
    risk=Risk.objects.get(primary_asset=first.asset)
    mark_handled(risk,reason='device diagnostics and recovery completed')
    handled=RiskStatusHistory.objects.filter(risk=risk,to_status='PENDING_REVERIFY').latest('created_at')
    # Move handling timestamp into the past while keeping test windows real.
    cutoff=end+timedelta(seconds=10);RiskStatusHistory.objects.filter(pk=handled.pk).update(created_at=cutoff);handled.refresh_from_db()
    follow=payload(sample='verified',end=end+timedelta(minutes=2));follow['hardware_reverification']={
        'event_ids':list(first.evaluation['pending_hardware_events']),'performed_at':(end+timedelta(minutes=1,seconds=30)).isoformat(),'method':'driver diagnostic self-test after service restart','result':'PASSED'}
    RiskObservation.objects.filter(risk=risk,detected=True).update(created_at=end)
    current,_=ingest(follow); assert current.evaluation['status']=='NORMAL'
    second=create_manual_inspection_run(environment=env,resource_type_codes=['GPU_POOL']);start_manual_inspection_run(second.pk)
    check=CheckResult.objects.get(inspection_run=second,asset=first.asset)
    risk.refresh_from_db(); assert risk.status=='RECOVERED'
    # The old observation was created now, so move it before synthetic handling too.
    RiskObservation.objects.filter(risk=risk,detected=True).update(created_at=end)
    assert _valid_hardware_pass(risk,check,handled)
    old=deepcopy(check.evidence)
    check.evidence['hardware_reverification']=None
    assert not _valid_hardware_pass(risk,check,handled)
    check.evidence=old;check.evidence['evaluation']['diagnostics']['gpu/ecc_dbe_delta']['status']='NOT_READY'
    assert not _valid_hardware_pass(risk,check,handled)
    check.evidence=deepcopy(old);check.evidence['components']['gpu']={'replacement':'new'}
    assert not _valid_hardware_pass(risk,check,handled)


def test_sbe_recurrence_acceleration_and_missing_data_breaks_confirmation():
    end=timezone.now()-timedelta(minutes=10);rows=[]
    for i,delta in enumerate([1,2,4]):
        raw=payload(end=end+timedelta(minutes=i),sample=str(i));raw['metrics']['gpu']['values']['ecc_sbe_delta']['value']=delta
        row=fake_row(raw,i);row.evaluation=evaluate(row,rows);rows.append(row)
    codes={issue['code'] for issue in rows[-1].evaluation['issues']}
    assert {'ECC_SBE_OCCASIONAL','ECC_SBE_RECURRENT','ECC_SBE_ACCELERATING'}<=codes
    assert drift([80,80,80],[100]*8,1)['direction']=='DOWN'


def test_api_profiles_are_scoped_and_unknown_for_stale(client,env):
    row,_=ingest(payload(end=timezone.now()-timedelta(minutes=10)))
    response=client.get('/api/v1/hardware-health/profiles',{'environment_id':str(env.pk)})
    assert response.status_code==200
    assert response.json()['profiles'][0]['status']=='UNKNOWN'
    assert response.json()['profiles'][0]['freshness']=='STALE'
    assert client.get('/api/v1/hardware-health/profiles').status_code==400
    other=Environment.objects.create(name='Other',slug='empty')
    assert client.get('/api/v1/hardware-health/profiles',{'environment_id':str(other.pk)}).json()['profiles']==[]


def test_correlations_queue_idle_io_and_hardware_with_service():
    end=timezone.now()-timedelta(minutes=30)
    rows=[fake_row(payload(end=end+timedelta(minutes=i),sample=str(i)),i) for i in range(18)]
    for row in rows[-3:]:
        row.payload['metrics']['gpu']['values']['utilization_ratio']['value']=.1
        row.payload['_inference'][0]['metrics']['requests']['waiting']=4
    rows[-1].payload['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1
    rows[-1].payload['_inference'][0]['evaluation']['status']='WARNING'
    result=evaluate(rows[-1],rows[:-1])
    assert {'SUSPECT_QUEUE_WITH_IDLE_GPU','SUSPECT_HARDWARE_WITH_SERVICE_DEGRADATION'}<={x['code'] for x in result['correlations']}
    hosts=[fake_row(payload(kind='HOST',end=end+timedelta(minutes=i),sample=str(i)),i) for i in range(18)]
    for row in hosts[-6:]:row.payload['metrics']['disk:root']['values']['read_latency_avg_ms']['value']=14
    result=evaluate(hosts[-1],hosts[:-1])
    assert any(x['code']=='SUSPECT_IO_LATENCY_DEGRADATION' for x in result['correlations'])
    # A changed request token load is not comparable even at unchanged QPS.
    hosts[-1].payload['_inference'][0]['metrics']['throughput']['prompt_tps']=1000
    assert evaluate(hosts[-1],hosts[:-1])['diagnostics']['disk:root/read_latency_avg_ms']['status']=='NOT_READY'


def test_internal_hardware_batch_stage_replay_and_scope_conflict(client,env,monkeypatch):
    monkeypatch.setenv('AIRFLOW_INTERNAL_TOKEN','hardware-token');call_command('seed_launch')
    raw=payload();raw['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1;ingest(raw)
    body={'environment_id':str(env.pk),'run_date':timezone.localdate().isoformat(),'dag_run_id':'hardware-scheduled','source_type':'HARDWARE_SNAPSHOT','resource_types':['GPU_POOL','HOST']}
    def post(path,data=None): return client.post('/api/internal/v1/batch'+path,data or {},content_type='application/json',HTTP_X_AIRFLOW_TOKEN='hardware-token')
    response=post('/inspection-runs/',body);assert response.status_code==200,response.content
    run_id=response.json()['inspection_run_id'];assert post('/inspection-runs/',body).json()['inspection_run_id']==run_id
    assert post('/inspection-runs/',{**body,'resource_types':['GPU_POOL']}).status_code==409
    for stage in ('execute','correlate-risks','reverify','resource-summaries','snapshot','complete'):
        assert post(f'/inspection-runs/{run_id}/{stage}/').status_code==200
        assert post(f'/inspection-runs/{run_id}/{stage}/').status_code==200
    assert CheckResult.objects.filter(inspection_run_id=run_id).count()==1
    assert Finding.objects.filter(inspection_item_run__inspection_run_id=run_id).count()==1
    assert RiskObservation.objects.filter(inspection_run_id=run_id).count()==1


def test_prior_diagnostic_or_component_absence_cannot_reverify_host(env):
    from apps.risks.services.lifecycle import mark_handled
    call_command('seed_launch');end=timezone.now()-timedelta(minutes=3)
    first,_=ingest(payload(kind='HOST',end=end))
    # Freeze an observed advanced diagnostic, then exercise the formal risk path.
    first.evaluation['status']='WARNING'
    first.evaluation['issues']=[{'key':'disk:root/read_latency_avg_ms','code':'CONDITIONAL_DRIFT','severity':'P2'}]
    first.save(update_fields=['evaluation'])
    run=create_manual_inspection_run(environment=env,resource_type_codes=['HOST']);start_manual_inspection_run(run.pk)
    risk=Risk.objects.get(primary_asset=first.asset);mark_handled(risk)
    handled=RiskStatusHistory.objects.filter(risk=risk,to_status='PENDING_REVERIFY').latest('created_at')
    RiskStatusHistory.objects.filter(pk=handled.pk).update(created_at=end+timedelta(seconds=1));handled.refresh_from_db()
    RiskObservation.objects.filter(risk=risk).update(created_at=end)
    later,_=ingest(payload(kind='HOST',sample='healthy',end=end+timedelta(minutes=2)))
    second=create_manual_inspection_run(environment=env,resource_type_codes=['HOST']);start_manual_inspection_run(second.pk)
    check=CheckResult.objects.get(inspection_run=second,asset=first.asset)
    assert check.status=='PASS' # basic data valid, but historical advanced diagnosis not ready
    assert not _valid_hardware_pass(risk,check,handled)
    check.evidence['evaluation']['diagnostics']['disk:root/read_latency_avg_ms']={'status':'NORMAL'}
    assert _valid_hardware_pass(risk,check,handled)
    del check.evidence['components']['disk:root']
    assert not _valid_hardware_pass(risk,check,handled)


def test_binding_cannot_resolve_an_engine_from_another_environment(env):
    from apps.inference_performance.schemas import parse_snapshot_request
    from apps.inference_performance.services.ingest import ingest_snapshot
    from tests.inference_performance.helpers import payload as inference_payload
    other=Environment.objects.create(name='Private',slug='private')
    llm,_=ingest_snapshot(parse_snapshot_request(inference_payload(str(other.pk),end=timezone.now()-timedelta(minutes=1))))
    raw=payload();raw['bindings']={'complete':True,'engines':[{'engine_id':llm.engine_id,'engine_type':llm.engine_type,'model_name':llm.model_name}]}
    with pytest.raises(APIRequestError):ingest(raw)
    assert not HardwareSnapshot.objects.filter(environment=env).exists()


def test_quality_gap_and_changed_configuration_do_not_confirm_drift():
    end=timezone.now()-timedelta(minutes=30)
    rows=[fake_row(payload(end=end+timedelta(minutes=i),sample=str(i)),i) for i in range(18)]
    for row in rows[-5:-1]: row.payload['metrics']['gpu']['values']['temperature_celsius'].update(quality='MISSING',value=None)
    rows[-1].payload['metrics']['gpu']['values']['temperature_celsius']['value']=70
    result=evaluate(rows[-1],rows[:-1])
    assert result['diagnostics']['gpu/temperature_celsius']['status']=='PENDING'
    assert result['status']=='UNKNOWN'
    rows[-1].payload['config_id']='changed'
    assert evaluate(rows[-1],rows[:-1])['diagnostics']['gpu/temperature_celsius']['status']=='NOT_READY'


@pytest.mark.parametrize('deltas,expected', [([1,2,4],'ECC_SBE_RECURRENT'),([1,4,16],'ECC_SBE_ACCELERATING')])
def test_sbe_acceleration_uses_event_rate_for_variable_windows(deltas,expected):
    start=timezone.now()-timedelta(minutes=20);rows=[]
    for i,(minutes,delta) in enumerate(zip([1,2,4],deltas)):
        end=start+timedelta(minutes=minutes)
        raw=payload(end=end,sample=str(i));raw['window_start']=start.isoformat()
        raw['metrics']['gpu']['values']['ecc_sbe_delta']['value']=delta
        row=fake_row(raw,i);row.evaluation=evaluate(row,rows);rows.append(row);start=end
    newest=next(issue for issue in rows[-1].evaluation['issues'] if issue.get('event_id')=='ecc:2:ecc_sbe_delta')
    assert newest['code']==expected and newest['current']==deltas[-1]
    assert rows[0].evaluation['issues'][0]['code']=='ECC_SBE_OCCASIONAL'


@pytest.mark.parametrize('quality',['RESET','MISSING'])
def test_variable_window_sbe_rate_sequence_breaks_at_invalid_quality(quality):
    start=timezone.now()-timedelta(minutes=20);rows=[]
    for i,(minutes,delta) in enumerate(zip([1,2,4],[1,4,16])):
        end=start+timedelta(minutes=minutes)
        raw=payload(end=end,sample=str(i));raw['window_start']=start.isoformat()
        point=raw['metrics']['gpu']['values']['ecc_sbe_delta'];point['value']=delta
        if i==1: point.update(quality=quality,value=None)
        if i==2: raw['metrics']['gpu']['values']['ecc_dbe_delta']['value']=1
        row=fake_row(raw,i);row.evaluation=evaluate(row,rows);rows.append(row);start=end
    newest=next(issue for issue in rows[-1].evaluation['issues'] if issue.get('event_id')=='ecc:2:ecc_sbe_delta')
    assert newest['code']=='ECC_SBE_OCCASIONAL'
    assert rows[-1].evaluation['status']=='CRITICAL'
    assert any(issue['code']=='ECC_DBE_NEW' and issue['current']==1 for issue in rows[-1].evaluation['issues'])


@pytest.mark.parametrize('field,limit',[('source',64),('sample_id',192)])
@pytest.mark.parametrize('shape',['spaces','plain'])
def test_raw_text_length_rejected_as_api400_without_residue(client,env,field,limit,shape):
    raw=payload();raw[field]=(' '*limit+'s') if shape=='spaces' else 's'*(limit+1)
    before=(HardwareSnapshot.objects.count(),Asset.objects.count())
    response=client.post('/api/v1/hardware-health/snapshots',raw,content_type='application/json')
    assert response.status_code==400,response.content
    assert response.json()['error']['code']=='VALIDATION_ERROR'
    assert (HardwareSnapshot.objects.count(),Asset.objects.count())==before
    valid=payload(sample='batch-good');valid['host_id']='another-host'
    response=client.post('/api/v1/hardware-health/snapshots/batch',{'samples':[valid,raw]},content_type='application/json')
    assert response.status_code==400,response.content
    assert (HardwareSnapshot.objects.count(),Asset.objects.count())==before


def test_raw_text_exact_storage_boundaries_preserve_idempotency(client,env):
    raw=payload();raw.update(source='s'*64,sample_id='i'*192)
    first=client.post('/api/v1/hardware-health/snapshots',raw,content_type='application/json')
    second=client.post('/api/v1/hardware-health/snapshots',raw,content_type='application/json')
    assert (first.status_code,second.status_code)==(201,200)
    assert first.json()['profile']['snapshot_id']==second.json()['profile']['snapshot_id']
    stored=HardwareSnapshot.objects.get()
    assert stored.source==raw['source'] and stored.sample_id==raw['sample_id']
    assert HardwareSnapshot.objects.count()==1 and Asset.objects.count()==1
