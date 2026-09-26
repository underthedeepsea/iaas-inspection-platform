"""Conservative device diagnostics; statistical readiness is separate from health."""
from datetime import timedelta
from statistics import median

PLUGIN = {'id':'gpu-host-health','version':'1.0.0'}
LOAD_FIELDS = [('traffic','qps'),('throughput','prompt_tps'),('throughput','generation_tps'),('requests','running'),('cache','kv_cache_hit_rate')]
MIN_EFFECT = {'temperature_celsius':5., 'utilization_ratio':.1, 'cpu_busy_ratio':.1, 'io_busy_ratio':.1,
              'read_latency_avg_ms':2., 'write_latency_avg_ms':2.}
# Capacity is evidence, not an anomaly: allocator preallocation is expected.
DRIFT_METRICS = set(MIN_EFFECT) | {'read_bytes_per_second','write_bytes_per_second'}


def value(row, component, metric):
    point=row.payload['metrics'].get(component,{}).get('values',{}).get(metric,{})
    return point.get('value') if point.get('quality')=='VALID' else None


def compatible(a,b):
    return all(a.payload.get(k)==b.payload.get(k) for k in ('identity','config_id','bindings'))


def load(row):
    """Frozen joined inference facts, not a live join during later run execution."""
    joined=row.payload.get('_inference',[])
    if not row.payload['bindings']['complete'] or not joined or len(joined)!=len(row.payload['bindings']['engines']): return None
    out={}
    for group,field in LOAD_FIELDS:
        numbers=[x['metrics'].get(group,{}).get(field) for x in joined]
        if any(v is None for v in numbers): return None
        out[field]=sum(numbers)/len(numbers) if field=='kv_cache_hit_rate' else sum(numbers)
    out['waiting']=sum(x['metrics']['requests']['waiting'] for x in joined)
    out['tpot']=max(x['metrics']['tpot']['p95_ms'] for x in joined)
    return out


def comparable(a,b, *, target=None):
    if not compatible(a,b): return False
    la,lb=load(a),load(b)
    if la is None or lb is None: return False
    for _,key in LOAD_FIELDS:
        if key==target: continue
        tolerance=.15 if key=='kv_cache_hit_rate' else max(1.,abs(la[key])*.3)
        if abs(la[key]-lb[key])>tolerance: return False
    return True


def contiguous(rows):
    """Chronological tail only; collection gaps cannot confirm a prior anomaly."""
    result=[]
    for row in reversed(rows):
        if result and (result[-1].window_start-row.window_end).total_seconds()>max(300,(row.window_end-row.window_start).total_seconds()*2): break
        result.append(row)
    return list(reversed(result))


def drift(series, history, floor, *, relative=.15):
    if len(history)<8 or not series:
        return {'status':'NOT_READY','sample_count':len(history),'reason':'INSUFFICIENT_COMPARABLE_HISTORY'}
    base=median(history); mad=median(abs(x-base) for x in history)
    scale=max(1.4826*mad, floor/3, abs(base)*relative/3, 1e-9)
    minimum=max(floor,abs(base)*relative)
    recent=series[-3:]
    directions=[1 if x-base>max(3*scale,minimum) else -1 if base-x>max(3*scale,minimum) else 0 for x in recent]
    positive=negative=0.
    for x in series[-12:]:
        z=(x-base)/scale
        positive=max(0.,positive+z-.5);negative=min(0.,negative+z+.5)
    confirmed=(directions[-1]!=0 and directions.count(directions[-1])>=2)
    slow=(abs(series[-1]-base)>=minimum and max(positive,-negative)>=5 and len(series)>=3)
    return {'status':'WARNING' if confirmed or slow else 'PENDING' if directions[-1] else 'NORMAL',
            'sample_count':len(history),'baseline_median':base,'mad':mad,'minimum_effect':minimum,
            'current':series[-1],'cusum_positive':positive,'cusum_negative':negative,
            'confirmation_points':len(recent),'direction':'UP' if series[-1]>base else 'DOWN'}


def slope(points):
    return median((y2-y1)/(t2-t1) for i,(t1,y1) in enumerate(points) for t2,y2 in points[i+1:] if t2>t1)


def declining(rows,component,metric):
    if len(rows)<6: return {'status':'NOT_READY','sample_count':len(rows)}
    points=[(r.window_end.timestamp(),value(r,component,metric)) for r in rows[-12:]]
    if any(v is None for _,v in points) or points[-1][0]-points[0][0]<300:
        return {'status':'NOT_READY','sample_count':len(points)}
    long,short=slope(points),slope(points[-4:])
    drop=points[0][1]-points[-1][1]
    consistent=long<0 and short<0 and .25<=short/long<=4 and drop>max(1024**2,abs(points[0][1])*.03)
    return {'status':'WARNING' if consistent else 'NORMAL','sample_count':len(points),'long_slope_bytes_per_second':long,
            'short_slope_bytes_per_second':short,'consistent_decline':consistent}


def evaluate(snapshot, previous):
    all_history=list(previous)
    history=[r for r in all_history if compatible(snapshot,r) and r.window_end>=snapshot.window_start-timedelta(days=14)]
    tail=contiguous(history+[snapshot])
    current=snapshot.payload; diagnostics={};issues=[]; coverage={};pending=False
    def issue(key,code,severity='P2',**facts):
        issues.append({'key':key,'code':code,'severity':severity,**facts})
    if current['kind']=='HOST':
        for family in ('filesystem','disk'):
            if not any(key.startswith(family+':') for key in current['metrics']): coverage[family]='MISSING'
    previous_components={k:body['identity'] for row in all_history for k,body in row.payload['metrics'].items()}
    # Inventory disappearance is never evidence that an earlier dimension recovered.
    for component,ids in previous_components.items():
        if component not in current['metrics'] or current['metrics'][component]['identity']!=ids:
            coverage[component]='MISSING_OR_REPLACED'
    for component,body in current['metrics'].items():
        family=component.split(':')[0]
        valid=all(point['quality']=='VALID' for point in body['values'].values())
        coverage[component]='READY' if valid and coverage.get(component)!='MISSING_OR_REPLACED' else coverage.get(component,'INCOMPLETE')
        component_rows=[]
        for r in reversed(tail):
            if r.payload['metrics'].get(component,{}).get('identity')!=body['identity']: break
            component_rows.append(r)
        component_rows.reverse()
        for metric,point in body['values'].items():
            key=component+'/'+metric
            if point['quality']!='VALID':
                diagnostics[key]={'status':point['quality'],'sample_count':0};continue
            diagnostics[key]={'status':'NORMAL','current':point['value']}
            if metric not in DRIFT_METRICS: continue
            eligible=[r for r in history if comparable(snapshot,r) and r.payload['metrics'].get(component,{}).get('identity')==body['identity']]
            # Hold out the recent tail so a slow drift cannot immediately redefine normal.
            recent=component_rows[-6:]
            cutoff=recent[0].window_start
            baseline=[value(r,component,metric) for r in eligible if r.window_end<=cutoff]
            baseline=[x for x in baseline if x is not None]
            series=[]
            for r in recent:
                v=value(r,component,metric)
                if v is None or not comparable(snapshot,r): series=[]
                else: series.append(v)
            result=drift(series,baseline,MIN_EFFECT.get(metric,1024**2),relative=.05 if metric=='temperature_celsius' else .15)
            diagnostics[key]=result
            if result['status']=='WARNING': issue(key,'CONDITIONAL_DRIFT',metric=metric,**result)
            pending |= result['status']=='PENDING'
        if family in {'filesystem','host'}:
            metric='available_bytes' if family=='filesystem' else 'memory_available_bytes'
            key=component+'/decline'
            diagnostics[key]=declining(component_rows,component,metric)
            result=diagnostics[key]
            if result['status']=='WARNING':
                if family=='filesystem':
                    capacity=value(snapshot,component,'size_bytes')
                    if capacity:
                        reserve=capacity*.1
                        result['reserve_bytes']=reserve
                        result['seconds_to_reserve']=max(0.,(value(snapshot,component,metric)-reserve)/-result['long_slope_bytes_per_second'])
                issue(key,'SPACE_DECLINE' if family=='filesystem' else 'MEMORY_SUSTAINED_DECLINE',**result)
    # Sticky hardware event state is independent of baseline horizon/config changes.
    hardware=dict((all_history[-1].evaluation or {}).get('pending_hardware_events',{})) if all_history else {}
    att=current.get('hardware_reverification',{})
    for event_id in att.get('event_ids',[]): hardware.pop(event_id,None)
    if current['kind']=='GPU':
        events=value(snapshot,'gpu','xid_events')
        for event in events or []:
            code=event['code'];eid='xid:'+event['event_id']
            category='MEMORY_ERROR' if code in {48,63,64,92,94,95} else 'DEVICE_LOST' if code==79 else 'GSP_ERROR' if code in {119,120} else 'APPLICATION_OR_DRIVER' if code in {13,31,43} else 'UNCLASSIFIED'
            hardware[eid]={'key':'gpu/xid_events','code':'XID_'+category,'severity':'P1' if code in {48,79,94,95,119,120} else 'P2','event_id':eid,'xid_code':code,'occurred_at':event['occurred_at']}
        for metric in ('ecc_sbe_delta','ecc_dbe_delta'):
            delta=value(snapshot,'gpu',metric)
            key='gpu/'+metric
            if delta is not None and delta>0:
                eid='ecc:'+str(snapshot.pk)+':'+metric
                rate=delta/(snapshot.window_end-snapshot.window_start).total_seconds()
                recent=[]
                for row in reversed(tail[:-1]):
                    v=value(row,'gpu',metric)
                    if v is None: break
                    recent.append(v/(row.window_end-row.window_start).total_seconds())
                    if len(recent)==3: break
                code='ECC_DBE_NEW' if metric=='ecc_dbe_delta' else 'ECC_SBE_ACCELERATING' if len(recent)>=2 and rate>recent[0]>recent[1]>0 else 'ECC_SBE_RECURRENT' if any(v>0 for v in recent) else 'ECC_SBE_OCCASIONAL'
                hardware[eid]={'key':key,'code':code,'severity':'P1' if metric=='ecc_dbe_delta' else 'P2','event_id':eid,'current':delta,'occurred_at':snapshot.window_end.isoformat()}
        for event in hardware.values():
            issue(**event)
            diagnostics[event['key']]={'status':'WARNING','reason':'HARDWARE_REVERIFICATION_REQUIRED'}
    correlations=[]
    for key,diagnostic in diagnostics.items():
        if key.endswith('/decline') and diagnostic.get('status')=='WARNING':
            correlations.append({'code':'SUSPECT_MEMORY_CONSUMPTION' if key.startswith('host/') else 'SPACE_RESERVE_TREND','metric':key})
        if key.endswith(('read_latency_avg_ms','write_latency_avg_ms')) and diagnostic.get('status')=='WARNING' and diagnostic.get('direction')=='UP':
            correlations.append({'code':'SUSPECT_IO_LATENCY_DEGRADATION','metric':key,'current':diagnostic['current'],'baseline_median':diagnostic['baseline_median']})
    if current['kind']=='GPU':
        now_load=load(snapshot)
        eligible=[r for r in history if comparable(snapshot,r,target='generation_tps')]
        recent=tail[-6:]; cutoff=recent[0].window_start
        base=[load(r)['generation_tps'] for r in eligible if r.window_end<=cutoff]
        output_series=[]
        for r in recent:
            lr=load(r)
            if lr is None or not comparable(snapshot,r,target='generation_tps'): output_series=[]
            else: output_series.append(lr['generation_tps'])
        output=drift(output_series,base,1.)
        diagnostics['gpu/output']=output
        pending |= output['status']=='PENDING'
        util=value(snapshot,'gpu','utilization_ratio')
        if now_load and util is not None:
            if output['status']=='WARNING' and output['direction']=='DOWN' and util>=.7:
                correlations.append({'code':'SUSPECT_GPU_BUSY_OUTPUT_DOWN','metric':'generation_tps','current':now_load['generation_tps'],'baseline_median':output['baseline_median']})
                issue('gpu/output','SUSPECT_GPU_BUSY_OUTPUT_DOWN',**output)
            if now_load['waiting']>0 and util<.2:
                points=[r for r in tail[-3:] if load(r) and load(r)['waiting']>0 and value(r,'gpu','utilization_ratio') is not None and value(r,'gpu','utilization_ratio')<.2]
                if len(points)>=2:
                    correlations.append({'code':'SUSPECT_QUEUE_WITH_IDLE_GPU','current':now_load['waiting']})
                    issue('gpu/queue_idle','SUSPECT_QUEUE_WITH_IDLE_GPU')
                diagnostics['gpu/queue_idle']={'status':'WARNING' if len(points)>=2 else 'PENDING'}
                pending |= len(points)<2
            else: diagnostics['gpu/queue_idle']={'status':'NORMAL'}
            temp=diagnostics.get('gpu/temperature_celsius',{})
            if temp.get('status')=='WARNING' and temp.get('direction')=='UP': correlations.append({'code':'SUSPECT_TEMPERATURE_AT_COMPARABLE_LOAD','current':temp['current']})
            if hardware and any(x.get('evaluation',{}).get('status') in {'WARNING','CRITICAL'} for x in current.get('_inference',[])):
                correlations.append({'code':'SUSPECT_HARDWARE_WITH_SERVICE_DEGRADATION'})
        else:
            diagnostics['gpu/queue_idle']={'status':'NOT_READY','reason':'INCOMPLETE_BINDING_OR_INFERENCE'}
    critical=any(x['severity']=='P1' for x in issues)
    incomplete=any(x!='READY' for x in coverage.values())
    status='CRITICAL' if critical else 'WARNING' if issues else 'UNKNOWN' if incomplete or pending else 'NORMAL'
    return {'plugin':PLUGIN,'input':{'snapshot_id':str(snapshot.pk)},'status':status,
            'quality':{'state':'INCOMPLETE' if incomplete else 'READY','pending_confirmation':pending},
            'coverage':coverage,'diagnostics':diagnostics,'issues':issues,'pending_hardware_events':hardware,
            'correlations':correlations,'reasons':[{**x,'window_start':snapshot.window_start.isoformat(),'window_end':snapshot.window_end.isoformat()} for x in issues+correlations],
            'limitations':['疑似相关性不等同根因；无频率/功耗不能诊断热降频；无IOPS/IO大小不能确诊存储退化。',
                            '8点仅最低计算门槛，NOT_READY不表示该诊断健康。','共享或归属不完整的设备仅报告设备级现象。']}
