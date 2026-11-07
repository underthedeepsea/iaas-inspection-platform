"""Standalone window admission regression; normal collection has no side effects."""
def main():
    import contextlib,copy,hashlib,importlib,json,sys,types
    from pathlib import Path
    from datetime import datetime,timezone
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
    def forbidden(*a,**k):raise AssertionError('DB/HTTP forbidden')
    class NoDB:
        def __getattr__(self,name):forbidden()
    class Atomic(contextlib.ContextDecorator):
        def __enter__(self):forbidden()
        def __exit__(self,*a):return False
    def atomic(fn=None):return Atomic() if fn is None else Atomic()(fn)
    for name in ['django','django.db','django.utils','django.utils.timezone','django.http']:sys.modules[name]=types.ModuleType(name)
    sys.modules['django.db'].IntegrityError=type('IntegrityError',(Exception,),{})
    sys.modules['django.db'].transaction=types.SimpleNamespace(atomic=atomic)
    sys.modules['django.utils.timezone'].now=lambda:datetime.now(timezone.utc)
    sys.modules['django.utils'].timezone=sys.modules['django.utils.timezone'];sys.modules['django.http'].JsonResponse=forbidden
    models=types.ModuleType('apps.core.models')
    for name in ['Environment','MappingBundle','MappingRevision','MappingValidation','MappingActivation','MappingCollection']:setattr(models,name,type(name,(),{'objects':NoDB()}))
    sys.modules['apps.core.models']=models
    from apps.core import mapping_services as store,mapping_simulation as sim,mapping_loop as loop
    from apps.hardware_health import schemas,evaluator
    from apps.api.http import APIRequestError
    modules=[store,sim,loop,schemas,evaluator,importlib.import_module('apps.inference_performance.schemas'),importlib.import_module('apps.api.http')]
    origins={m.__name__:{'origin':str(Path(m.__file__).resolve()),'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()} for m in modules}
    results=[];assertions=0
    def check(ok,message='assertion failed'):
        nonlocal assertions
        assertions+=1
        if not ok:raise AssertionError(message)
    def eq(a,b):check(a==b,f'{a!r} != {b!r}')
    def rejects(fn,*args):
        nonlocal assertions
        assertions+=1
        try:fn(*args)
        except (store.MappingInputError,APIRequestError):return
        raise AssertionError('Expected explicit contract rejection')
    def case(name,fn):
        before=assertions
        try:fn()
        except Exception as e:
            import traceback
            results.append({'case':name,'status':'FAIL','assertions':assertions-before,'error':str(e),'traceback':traceback.format_exc()})
        else:results.append({'case':name,'status':'PASS','assertions':assertions-before})
    fields=['host.cpu_busy_ratio','gpu.ecc_sbe_delta','gpu.xid_events']
    def package(span=301,step=60,selected=None):
        metrics=[]
        for field in selected or fields:
            source,unit,out,conversion=store.FIELD_SPECS[field]
            metrics.append({'standard_field':field,'source_metric':source,'source_type':store.source_type(field),'source_unit':unit,'output_unit':out,'conversion':conversion,'labels':{},'window_seconds':span,'step_seconds':step})
        return {'schema_version':store.SCHEMA_VERSION,'cluster':{'cluster_uid':'grid-cluster','monitor_cluster_id':'grid-monitor','display_name':'Grid fixture'},'metrics':metrics}
    def validated(span=301,step=60,selected=None):
        return store.validate_content(package(span,step,selected),cluster_uid='grid-cluster',monitor_cluster_id='grid-monitor')
    def bound(span=301,step=60,fixture='complete'):
        _,_,sha=validated(span,step)
        bundle=types.SimpleNamespace(environment_id='grid-env',source_ref='demo-monitor',cluster_uid='grid-cluster',monitor_cluster_id='grid-monitor')
        revision=types.SimpleNamespace(pk='grid-revision',content_hash=sha)
        return loop.binding(bundle,revision,fixture,1,1700000000,1700000000+span,step)
    def source_request(span=301,step=60,field='host.cpu_busy_ratio',fixture='complete'):
        return {'environment_id':'grid-env','source_ref':'demo-monitor','cluster_uid':'grid-cluster','monitor_cluster_id':'grid-monitor','fixture':fixture,'seed':1,'start':1700000000,'end':1700000000+span,'step':step,'counter':store.FIELD_SPECS[field][0]}
    if '--reproduce-old' in sys.argv:
        p,canonical,sha=validated();observed={}
        for name,fn,args in [('window',sim.window,(1700000000,1700000301,60)),('query',sim.query,(source_request(),)),('binding',bound,())]:
            try:fn(*args)
            except store.MappingInputError as e:observed[name]={'rejected':True,'type':type(e).__name__,'message':str(e)}
            else:observed[name]={'rejected':False}
        output={'classification':'EXPECTED_OLD_BUG_REPRODUCTION','content_structure_accepted':p==package(),'canonical_sha256':sha,'observed':observed,'modules':origins,'cli':[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--reproduce-old'],'cwd':str(Path.cwd())}
        print(json.dumps(output,indent=2));raise SystemExit(0 if output['content_structure_accepted'] and all(x['rejected'] for x in observed.values()) else 1)
    def consume(span=301,step=60,selected=None,fixture='complete'):
        p,_,_=validated(span,step,selected);binding=bound(span,step,fixture)
        raws,values=loop.fetch(binding,p)
        payloads=loop.hardware_payloads(types.SimpleNamespace(pk='grid',revision_id='grid-revision',binding=binding),values,p)
        parsed=[]
        for payload in payloads:
            body,start,end=schemas.parse_request(payload)
            parsed.append(types.SimpleNamespace(pk='grid',payload=body,window_start=start,window_end=end,evaluation=None))
        return binding,raws,values,parsed
    def all_paths(span=301,step=60):
        b,raws,values,rows=consume(span,step)
        expected=list(range(b['start'],b['end'],step));eq(sim.window(b['start'],b['end'],step),expected)
        gauge=next(r for r in raws if r['dstype']=='GAUGE');counter=next(r for r in raws if r['dstype']=='COUNTER');events=next(r for r in raws if r['dstype']=='EVENTS')
        eq([p['timestamp'] for p in gauge['series'][0]['points']],expected)
        eq([p['timestamp'] for p in counter['series'][0]['points']],expected+[b['end']])
        eq(values['gpu.ecc_sbe_delta']['value'],len(expected));eq(values['gpu.ecc_sbe_delta']['quality'],'VALID')
        eq(values['host.cpu_busy_ratio'],.41);eq(len(values['gpu.xid_events']),1)
        eq(events['series'][0]['events'][0]['timestamp'],b['start'])
        for row in rows:eq((row.window_end-row.window_start).total_seconds(),span)
        captured=[]
        def trace(frame,event,arg):
            if frame.f_code is evaluator.evaluate.__code__ and event=='return':captured.append(frame.f_locals.get('rate'))
            return trace
        row=next(row for row in rows if row.payload['kind']=='GPU')
        sys.settrace(trace)
        try:result=evaluator.evaluate(row,[])
        finally:sys.settrace(None)
        eq(captured,[len(expected)/span]);check(any(x['code']=='ECC_SBE_OCCASIONAL' for x in result['issues']))
    case('301-60-GAUGE-COUNTER-EVENTS-binding-default-chain-schema-rate',all_paths)
    case('300-60-original-divisible-positive-control',lambda:all_paths(300,60))
    def limit(span,step,field,points):
        _,raws,values,rows=consume(span,step,[field]);raw=raws[0]
        eq(len(raw['series'][0]['points']),points)
        check(all(p['timestamp']<raw['end'] for p in raw['series'][0]['points'][:-1]))
        if field=='host.cpu_busy_ratio':check(raw['series'][0]['points'][-1]['timestamp']<raw['end'])
        else:eq(raw['series'][0]['points'][-1]['timestamp'],raw['end']);eq(values[field]['value'],points-1)
        check(bool(rows))
    case('nondivisible-GAUGE-61-actual-grid-accepted',lambda:limit(361,6,'host.cpu_busy_ratio',61))
    case('nondivisible-GAUGE-62-actual-grid-rejected',lambda:rejects(sim.query,source_request(367,6)))
    case('nondivisible-COUNTER-61-total-accepted',lambda:limit(355,6,'gpu.ecc_sbe_delta',61))
    case('nondivisible-COUNTER-62-total-rejected',lambda:rejects(sim.query,source_request(361,6,'gpu.ecc_sbe_delta')))
    case('smallest-positive-window-with-two-counter-boundaries',lambda:all_paths(1,1))
    case('EVENTS-nondivisible61-grid-budget-accepted',lambda:check(bool(consume(361,6,['gpu.xid_events'])[2]['gpu.xid_events'])))
    case('EVENTS-62-grid-budget-rejected',lambda:rejects(sim.query,source_request(367,6,'gpu.xid_events')))
    for name,args in [('bool-start',(True,1700000301,60)),('bool-end',(1700000000,True,60)),('bool-step',(1700000000,1700000301,True)),('string-start',('1700000000',1700000301,60)),('float-end',(1700000000,1700000301.,60)),('float-step',(1700000000,1700000301,60.)),('zero-step',(1700000000,1700000301,0)),('negative-step',(1700000000,1700000301,-1)),('empty',(1700000000,1700000000,60)),('negative-span',(1700000301,1700000000,60)),('step-over-span',(1700000000,1700000301,302)),('over-hour',(1700000000,1700003601,60)),('future',(int(datetime.now(timezone.utc).timestamp())+10,int(datetime.now(timezone.utc).timestamp())+311,60))]:
        case('window-reject-'+name,lambda args=args:rejects(sim.window,*args))
    for name,span,step in [('window-bool',True,1),('step-bool',301,True),('window-float',301.,60),('step-string',301,'60')]:
        case('structure-reject-'+name,lambda span=span,step=step:rejects(validated,span,step))
    for field,fixture in [('host.cpu_busy_ratio','missing'),('host.cpu_busy_ratio','no-data'),('gpu.ecc_sbe_delta','counter-missing-start'),('gpu.ecc_sbe_delta','counter-missing-end'),('gpu.ecc_sbe_delta','counter-single-point')]:
        case('301-60-missing-never-filled-'+field+'-'+fixture,lambda field=field,fixture=fixture:rejects(consume,301,60,[field],fixture))
    def reset():
        _,_,values,rows=consume(301,60,['gpu.ecc_sbe_delta'],'counter-reset-end');eq(values['gpu.ecc_sbe_delta']['quality'],'RESET');eq(values['gpu.ecc_sbe_delta']['value'],None)
        result=evaluator.evaluate(rows[0],[]);eq(result['diagnostics']['gpu/ecc_sbe_delta']['status'],'RESET');eq(result['status'],'UNKNOWN')
    case('301-60-counter-end-reset-quality-preserved',reset)
    for kind in ['unit','scope','ordinary-end','quality','nonfinite']:
        def invalid(kind=kind):
            req=source_request();raw=sim.query(req);mapped=package()['metrics'][0]
            if kind=='unit':raw['unit']='bytes'
            elif kind=='scope':raw['environment_id']='other'
            elif kind=='ordinary-end':raw['series'][0]['points'][-1]['timestamp']=req['end']
            elif kind=='quality':raw['series'][0]['points'][-1]['quality']='MISSING'
            else:raw['series'][0]['points'][-1]['value']=float('nan')
            rejects(sim.normalize,raw,req,mapped)
        case('301-60-normalizer-existing-guard-'+kind,invalid)
    for mode in ['boundary-missing','extra-boundary']:
        def invalid_counter(mode=mode):
            req=source_request(field='gpu.ecc_sbe_delta');raw=sim.query(req);points=raw['series'][0]['points']
            if mode=='boundary-missing':points.pop()
            else:points.append(copy.deepcopy(points[-1]))
            rejects(sim.normalize,raw,req,package()['metrics'][1])
        case('301-60-counter-normalizer-'+mode,invalid_counter)
    after={m.__name__:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in modules};check(after=={name:r['sha256'] for name,r in origins.items()})
    report={'classification':'AUTHOR_REGRESSION_RUN','cwd':str(Path.cwd()),'cli':[sys.executable,'-I','-B',str(Path(__file__).resolve())],'modules':origins,'source_after':after,'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cases':results,'case_count':len(results),'passed':sum(r['status']=='PASS' for r in results),'failed':sum(r['status']=='FAIL' for r in results),'assertions':assertions,'isolation':{'settings_loaded':'django.conf' in sys.modules,'orm_http':'fail-closed import surfaces','algorithm_patches':[]}}
    print(json.dumps(report,indent=2));raise SystemExit(1 if report['failed'] else 0)
if __name__=='__main__':main()
