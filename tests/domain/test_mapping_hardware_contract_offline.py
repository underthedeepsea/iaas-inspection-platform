"""Standalone S19 real-module checks; collection has no environment side effects."""
def main():
    import contextlib,copy,hashlib,importlib,json,sys,types
    from datetime import datetime,timezone
    from pathlib import Path
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
    def forbidden(*args,**kwargs):raise AssertionError('DB/HTTP forbidden in offline S19')
    class NoDB:
        def __getattr__(self,name):forbidden()
    class Atomic(contextlib.ContextDecorator):
        def __enter__(self):forbidden()
        def __exit__(self,*args):return False
    def atomic(fn=None):return Atomic() if fn is None else Atomic()(fn)
    for name in ['django','django.db','django.utils','django.utils.timezone','django.http']:sys.modules[name]=types.ModuleType(name)
    sys.modules['django.db'].IntegrityError=type('IntegrityError',(Exception,),{})
    sys.modules['django.db'].transaction=types.SimpleNamespace(atomic=atomic)
    sys.modules['django.utils.timezone'].now=lambda:datetime.now(timezone.utc)
    sys.modules['django.utils'].timezone=sys.modules['django.utils.timezone']
    sys.modules['django.http'].JsonResponse=forbidden
    models=types.ModuleType('apps.core.models')
    for name in ['Environment','MappingBundle','MappingRevision','MappingValidation','MappingActivation','MappingCollection']:setattr(models,name,type(name,(),{'objects':NoDB()}))
    sys.modules['apps.core.models']=models
    from apps.core import mapping_services as store,mapping_simulation as sim,mapping_loop as loop
    from apps.hardware_health import schemas,evaluator
    from apps.api.http import APIRequestError
    modules=[store,sim,loop,schemas,evaluator,importlib.import_module('apps.inference_performance.schemas'),importlib.import_module('apps.api.http')]
    origins={m.__name__:{'origin':str(Path(m.__file__).resolve()),'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()} for m in modules}
    bound={'environment_id':'offline-s19','source_ref':'demo-monitor','cluster_uid':'s19-cluster','monitor_cluster_id':'s19-monitor','fixture':'complete','seed':1,'start':1700000000,'end':1700000300,'step':60}
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
        except Exception as exc:
            import traceback
            results.append({'case':name,'status':'FAIL','assertions':assertions-before,'error':str(exc),'traceback':traceback.format_exc()})
        else:results.append({'case':name,'status':'PASS','assertions':assertions-before})
    def metric(field):
        source,unit,out,conversion=store.FIELD_SPECS[field]
        labels=dict(store.MOCK_FILESYSTEM_IDENTITY) if field.startswith('filesystem.') else {'block_device':'nvme0n1'} if field.startswith('disk.') else {}
        return {'standard_field':field,'source_metric':source,'source_type':store.source_type(field),'source_unit':unit,'output_unit':out,'conversion':conversion,'labels':labels,'window_seconds':300,'step_seconds':60}
    def package(fields=None):return {'schema_version':store.SCHEMA_VERSION,'cluster':{'cluster_uid':'s19-cluster','monitor_cluster_id':'s19-monitor','display_name':'S19 fixture'},'metrics':[metric(f) for f in (fields if fields is not None else store.FIELD_SPECS)]}
    def validate(p):return store.validate_content(p,cluster_uid='s19-cluster',monitor_cluster_id='s19-monitor')
    def spec(field,fixture='complete'):
        value={**bound,'counter':store.FIELD_SPECS[field][0],'fixture':fixture}
        if field.startswith(('disk.','filesystem.')):value['resource_labels']=metric(field)['labels']
        return value
    def raw_and_metric(field):
        request=spec(field);return sim.query(request),request,metric(field)
    def consume(fields=None,fixture='complete'):
        p=package(fields);validate(p);raws,values=loop.fetch({**bound,'fixture':fixture},p)
        payloads=loop.hardware_payloads(types.SimpleNamespace(pk='s19',revision_id='rev-s19',binding=bound),values,p)
        evaluations=[]
        for payload in payloads:
            parsed,start,end=schemas.parse_request(payload)
            row=types.SimpleNamespace(pk='s19',payload=parsed,window_start=start,window_end=end,evaluation=None)
            evaluations.append(evaluator.evaluate(row,[]))
        return raws,values,payloads,evaluations
    def full():
        raws,values,payloads,evaluations=consume();eq(len(values),17);eq(len(raws),17);eq(len(payloads),2)
        gpu=next(x for x in payloads if x['kind']=='GPU');host=next(x for x in payloads if x['kind']=='HOST')
        eq(len(gpu['metrics']['gpu']['values']),7);eq(sum(len(c['values']) for c in host['metrics'].values()),10)
        for payload in payloads:
            for component in payload['metrics'].values():
                for point in component['values'].values():eq(point['quality'],'VALID');check(point['value'] is not None)
        eq(host['metrics']['filesystem:root']['identity'],{'filesystem':'ext4','mountpoint':'/','block_device':'dev0'})
        eq(host['metrics']['disk:nvme0n1']['identity'],{'block_device':'nvme0n1'})
        eq(values['filesystem.available_bytes'],50*1024**3);eq(values['filesystem.size_bytes'],100*1024**3)
        eq(values['disk.read_bytes_per_second'],41.);eq(values['disk.write_bytes_per_second'],41.);eq(values['disk.io_busy_ratio'],.41)
        eq(values['gpu.ecc_sbe_delta']['value'],5);eq(values['gpu.ecc_dbe_delta']['semantics'],'DOUBLE_BIT')
        eq(values['gpu.xid_events'][0]['code'],79)
        for result in evaluations:eq(result['quality']['state'],'READY')
        gpu_eval=next(x for x in evaluations if 'gpu' in x['coverage']);eq(gpu_eval['status'],'CRITICAL')
        check(any(x['code']=='ECC_DBE_NEW' for x in gpu_eval['issues']))
        host_eval=next(x for x in evaluations if 'host' in x['coverage'])
        eq(host_eval['diagnostics']['disk:nvme0n1/read_bytes_per_second']['status'],'NOT_READY')
    case('all17-default-chain-real-schema-evaluator',full)
    def zero():
        _,values,payloads,evaluations=consume(fixture='zero')
        eq(values['filesystem.available_bytes'],0);check(values['filesystem.size_bytes']>0)
        eq(values['disk.io_busy_ratio'],0);eq(values['gpu.xid_events'],[]);eq(values['gpu.ecc_sbe_delta']['value'],0)
        for payload in payloads:
            for component in payload['metrics'].values():
                for point in component['values'].values():eq(point['quality'],'VALID')
    case('all17-legal-zero-not-missing',zero)
    def partial():
        _,_,payloads,evaluations=consume(['gpu.temperature_celsius','host.cpu_busy_ratio'])
        for payload in payloads:
            for component in payload['metrics'].values():
                for name,point in component['values'].items():
                    if name not in {'temperature_celsius','cpu_busy_ratio'}:eq(point['quality'],'MISSING');eq(point['value'],None)
        for result in evaluations:eq(result['status'],'UNKNOWN');eq(result['quality']['state'],'INCOMPLETE')
    case('partial-missing-schema-valid-never-green',partial)
    for fixture,quality in [('missing','MISSING'),('no-data','UNSUPPORTED')]:
        def nonvalid(fixture=fixture,quality=quality):
            _,values,payloads,evaluations=consume(['gpu.xid_events'],fixture)
            eq(values['gpu.xid_events']['quality'],quality);eq(values['gpu.xid_events']['value'],None)
            eq(payloads[0]['metrics']['gpu']['values']['xid_events']['quality'],quality)
            eq(evaluations[0]['diagnostics']['gpu/xid_events']['status'],quality);eq(evaluations[0]['issues'],[]);eq(evaluations[0]['status'],'UNKNOWN')
        case('default-Xid-nonvalid-'+quality,nonvalid)
    def stable_event():
        a=consume(['gpu.xid_events'])[1]['gpu.xid_events'];b=consume(['gpu.xid_events'])[1]['gpu.xid_events'];eq(a,b);check(bool(a[0]['event_id']))
    case('stable-Xid-event-id-real-default-query',stable_event)
    for field in ['filesystem.available_bytes','filesystem.size_bytes','disk.read_bytes_per_second','disk.write_bytes_per_second','disk.io_busy_ratio']:
        for badkey,badvalue in [('source_unit','seconds'),('conversion','MULTIPLY_1000'),('output_unit','ms')]:
            def wrong_binding(field=field,key=badkey,value=badvalue):
                p=package();next(m for m in p['metrics'] if m['standard_field']==field)[key]=value;rejects(validate,p)
            case('binding-'+field+'-'+badkey,wrong_binding)
        def wrong_identity(field=field):
            raw,request,mapped=raw_and_metric(field);raw['series'][0]['labels']['block_device']='other';rejects(sim.normalize,raw,request,mapped)
            bad=copy.deepcopy(request);bad['resource_labels']['block_device']='other';rejects(sim.query,bad)
        case('resource-identity-'+field,wrong_identity)
        def nan(field=field):
            raw,request,mapped=raw_and_metric(field);raw['series'][0]['points'][0]['value']=float('nan');rejects(sim.normalize,raw,request,mapped)
        case('nonfinite-'+field,nan)
    def fs_path_guard():
        for mount in ['/tmp','/data','//','http://example']:
            p=package();next(m for m in p['metrics'] if m['standard_field']=='filesystem.available_bytes')['labels']['mountpoint']=mount;rejects(validate,p)
        rejects(store._token,'/','generic label')
    case('filesystem-precise-root-exception-token-still-strict',fs_path_guard)
    def pair_absent():
        p=package();p['metrics']=[m for m in p['metrics'] if m['standard_field']!='filesystem.size_bytes'];rejects(validate,p)
    case('filesystem-capacity-pair-required',pair_absent)
    def overflow():
        rejects(loop.fetch,{**bound,'fixture':'capacity-overflow'},package(['filesystem.available_bytes','filesystem.size_bytes']))
    case('filesystem-original-spike-overflow-not-hidden-by-average',overflow)
    def ratio():
        raw,request,mapped=raw_and_metric('disk.io_busy_ratio');raw['series'][0]['points'][0]['value']=1.1;rejects(sim.normalize,raw,request,mapped)
    case('io-ratio-point-range-not-hidden-by-average',ratio)
    for kind in ['event-id','event-time','event-code','quality-fabrication','source-scope']:
        def bad_event(kind=kind):
            raw,request,mapped=raw_and_metric('gpu.xid_events');row=raw['series'][0]
            if kind=='event-id':row['events'][0]['event_id']='bad/id'
            elif kind=='event-time':row['events'][0]['timestamp']=bound['end']
            elif kind=='event-code':row['events'][0]['code']=True
            elif kind=='source-scope':row['labels']['cluster_uid']='other'
            else:row['quality']='UNSUPPORTED'
            rejects(sim.normalize,raw,request,mapped)
        case('Xid-reject-'+kind,bad_event)
    for key,value in [('semantics','SINGLE_BIT'),('scope','SRAM'),('source_metric','invented')]:
        def ecc_proof(key=key,value=value):
            raw,request,mapped=raw_and_metric('gpu.ecc_dbe_delta');raw['series'][0][key]=value;rejects(sim.normalize,raw,request,mapped)
        case('ECC-no-fake-proof-'+key,ecc_proof)
    def ecc_reset():
        _,values,_,evals=consume(['gpu.ecc_sbe_delta'],'counter-reset-end');eq(values['gpu.ecc_sbe_delta']['quality'],'RESET');eq(evals[0]['status'],'UNKNOWN');eq(evals[0]['issues'],[])
    case('focused-S18-reset-quality-compatibility',ecc_reset)
    def endcap():
        request=spec('gpu.ecc_sbe_delta');request.update(start=bound['end']-61,step=1);rejects(sim.query,request)
    case('focused-S18-62-point-rejection',endcap)
    for field in ['filesystem.available_bytes','disk.read_bytes_per_second']:
        def raw_scope(field=field):
            for key,bad in [('unit','ms'),('environment_id','other'),('dstype','COUNTER')]:
                raw,request,mapped=raw_and_metric(field);raw[key]=bad;rejects(sim.normalize,raw,request,mapped)
        case('raw-unit-type-scope-'+field,raw_scope)
    after={m.__name__:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in modules};check(after=={name:r['sha256'] for name,r in origins.items()})
    report={'cwd':str(Path.cwd()),'cli':[sys.executable,'-I','-B',str(Path(__file__).resolve())],'modules':origins,'source_after':after,'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cases':results,'case_count':len(results),'passed':sum(r['status']=='PASS' for r in results),'failed':sum(r['status']=='FAIL' for r in results),'assertions':assertions,'isolation':{'settings_loaded':'django.conf' in sys.modules,'orm':'fail-closed import stub','algorithm_patches':[]}}
    print(json.dumps(report,indent=2));raise SystemExit(bool(report['failed']))
if __name__=='__main__':main()
