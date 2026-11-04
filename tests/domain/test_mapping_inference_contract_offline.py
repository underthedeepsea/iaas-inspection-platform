"""Real S20 default lifecycle with an observable in-memory repository boundary.

Run explicitly with python -I -B; never installs Django settings or contacts a DB.
"""
def main():
    import contextlib,copy,hashlib,importlib,json,sys,types,uuid,traceback
    from pathlib import Path
    from datetime import datetime,timezone,timedelta
    root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root))
    trace=[];managers=[];now=datetime.fromtimestamp(int(datetime.now(timezone.utc).timestamp())//60*60-60,timezone.utc)
    def forbidden(*a,**k):raise AssertionError('External DB/HTTP/network forbidden')
    def attr(obj,path):
        for key in path:
            if isinstance(obj,dict):obj=obj.get(key)
            else:obj=getattr(obj,key)
        return obj
    def matches(row,kw):
        for key,value in kw.items():
            terms=key.split('__');op=terms[-1] if terms[-1] in {'in','lt','lte','gt','gte','contains'} else 'eq'
            if op!='eq':terms=terms[:-1]
            got=attr(row,terms)
            if op=='eq' and got!=value:return False
            if op=='in' and got not in value:return False
            if op=='lt' and not got<value:return False
            if op=='lte' and not got<=value:return False
            if op=='gt' and not got>value:return False
            if op=='gte' and not got>=value:return False
            if op=='contains' and not all(got.get(k)==v for k,v in value.items()):return False
        return True
    class QS:
        def __init__(self,manager,rows):self.manager=manager;self.rows=list(rows)
        def __iter__(self):return iter(self.rows)
        def iterator(self,chunk_size=None):return iter(self.rows)
        def all(self):return self
        def only(self,*keys):return self
        def __len__(self):return len(self.rows)
        def __getitem__(self,k):return QS(self.manager,self.rows[k]) if isinstance(k,slice) else self.rows[k]
        def filter(self,**kw):trace.append(['filter',self.manager.name,repr(kw)]);return QS(self.manager,[r for r in self.rows if matches(r,kw)])
        def exclude(self,**kw):return QS(self.manager,[r for r in self.rows if not matches(r,kw)])
        def get(self,**kw):
            q=self.filter(**kw).rows
            if len(q)!=1:raise self.manager.cls.DoesNotExist()
            return q[0]
        def order_by(self,*keys):
            rows=self.rows[:]
            for k in reversed(keys):rows.sort(key=lambda r:attr(r,k.lstrip('-').split('__')),reverse=k.startswith('-'))
            return QS(self.manager,rows)
        def first(self):return self.rows[0] if self.rows else None
        def exists(self):return bool(self.rows)
        def count(self):return len(self.rows)
        def distinct(self):return self
        def select_related(self,*a):return self
        def select_for_update(self):trace.append(['lock',self.manager.name]);return self
        def values_list(self,k,flat=False):return QS(self.manager,[attr(r,k.split('__')) for r in self.rows])
        def values(self,*keys):return QS(self.manager,[{k:attr(r,k.split('__')) for k in keys} for r in self.rows])
    class Manager(QS):
        def __init__(self,cls):self.cls=cls;self.name=cls.__name__;self.manager=self;self.rows=[];managers.append(self)
        def create(self,**kw):r=self.cls(**kw);r.save();return r
        def get_or_create(self,defaults=None,**kw):
            found=self.filter(**kw).first()
            return (found,False) if found else (self.create(**kw,**(defaults or {})),True)
        def bulk_create(self,rows):
            for row in rows:row.save()
        def none(self):return QS(self,[])
    class Model:
        def __init__(self,**kw):
            self.pk=kw.pop('pk',str(uuid.uuid4()));self.id=self.pk;self.created_at=now
            self.evaluation={};self.metrics={};self.error_code='';self.evidence={};self.status='ACTIVE' if type(self).__name__=='Asset' else 'CREATED';self.run=None
            self.__dict__.update(kw)
        def __getattr__(self,key):
            if key.endswith('_id') and key[:-3] in self.__dict__:return getattr(self.__dict__[key[:-3]],'pk',None)
            raise AttributeError(key)
        def save(self,**kw):
            if self not in type(self).objects.rows:type(self).objects.rows.append(self)
            trace.append(['save',type(self).__name__,str(self.pk),sorted(kw)])
        def refresh_from_db(self):pass
    def model(name):
        cls=type(name,(Model,),{'DoesNotExist':type(name+'Missing',(Exception,),{})});cls.objects=Manager(cls);return cls
    class Atomic(contextlib.ContextDecorator):
        def __enter__(self):
            self.before=[(m,m.rows[:],[(r,copy.deepcopy(r.__dict__,{id(v):v for x in managers for v in x.rows})) for r in m.rows])for m in managers]
            trace.append(['atomic.enter']);return self
        def __exit__(self,t,e,tb):
            if t:
                for m,rows,states in self.before:
                    m.rows[:]=rows
                    for row,state in states:row.__dict__.clear();row.__dict__.update(state)
            trace.append(['atomic.exit',None if t is None else t.__name__]);return False
        def _recreate_cm(self):return Atomic()
    def atomic(fn=None):return Atomic() if fn is None else Atomic()(fn)
    for name in ['django','django.db','django.conf','django.utils','django.utils.timezone','django.http']:sys.modules[name]=types.ModuleType(name)
    sys.modules['django.db'].IntegrityError=type('IntegrityError',(Exception,),{})
    sys.modules['django.db'].transaction=types.SimpleNamespace(atomic=atomic)
    sys.modules['django.conf'].settings=types.SimpleNamespace(BASE_DIR=root)
    tz=sys.modules['django.utils.timezone'];tz.now=lambda:now;tz.localdate=lambda:now.date();tz.is_naive=lambda x:x.tzinfo is None
    sys.modules['django.utils'].timezone=tz;sys.modules['django.http'].JsonResponse=forbidden
    names={'apps.core.models':['Environment','MappingBundle','MappingRevision','MappingValidation','MappingActivation','MappingCollection'],
           'apps.assets.models':['Asset'], 'apps.inference_performance.models':['InferencePerformanceSnapshot','InferencePerformancePolicy'],
           'apps.hardware_health.models':['HardwareSnapshot'],
           'apps.inspections.models':['InspectionItem','InspectionItemRun','InspectionRun','ResourceType','InspectionItemResourceType','InspectionRunEvent']}
    classes={}
    for module,items in names.items():
        m=types.ModuleType(module)
        for name in items:classes[name]=model(name);setattr(m,name,classes[name])
        def dynamic(name,m=m):
            if name.startswith('__'):raise AttributeError(name)
            cls=model(name);setattr(m,name,cls);classes[name]=cls;return cls
        m.__getattr__=dynamic;sys.modules[module]=m
    Env=classes['Environment'];Env.EnvironmentType=types.SimpleNamespace(values=['DEV','TEST','PROD_SIM'])
    Asset=classes['Asset'];Asset.Status=types.SimpleNamespace(ACTIVE='ACTIVE');Asset.AssetType=types.SimpleNamespace(LLM_INSTANCE='LLM_INSTANCE',values=['LLM_INSTANCE','HOST','GPU'])
    Run=classes['InspectionRun'];Run.TriggerType=types.SimpleNamespace(MANUAL='MANUAL');Run.Status=types.SimpleNamespace(PENDING='PENDING')
    worker=types.ModuleType('apps.inspections.services.worker');worker.enqueue_manual_inspection=lambda rid:trace.append(['enqueue',str(rid)]);sys.modules[worker.__name__]=worker
    service_package=types.ModuleType('apps.inspections.services');service_package.__path__=[str(root/'apps/inspections/services')];sys.modules[service_package.__name__]=service_package
    from apps.core import mapping_services as store,mapping_simulation as sim,mapping_loop as loop,mapping_inference as mi
    from apps.inference_performance import schemas
    from apps.inspections.services import trigger,inference_freeze as freezer,scope as scopes,mapping_coverage as coverage
    from apps.inference_performance.services import ingest as inference_ingest
    from apps.hardware_health import services as hardware_ingest
    results=[];assertions=0
    def observe(frame,event,arg):
        if event=='exception' and '/apps/' in frame.f_code.co_filename:
            kind,error,tb=arg;trace.append(['observed.exception',frame.f_code.co_filename,frame.f_lineno,kind.__name__,str(error)])
        return observe
    sys.settrace(observe)
    def check(ok,msg='assertion failed'):
        nonlocal assertions
        assertions+=1
        if not ok:raise AssertionError(msg)
    def eq(a,b):check(a==b,repr((a,b)))
    def rejects(fn,*a,**kw):
        nonlocal assertions
        assertions+=1
        try:fn(*a,**kw)
        except (ValueError,KeyError):return
        raise AssertionError('Expected explicit rejection')
    def case(name,fn):
        before=assertions;start=len(trace)
        try:fn()
        except Exception as exc:results.append({'case':name,'status':'FAIL','assertions':assertions-before,'error':str(exc),'traceback':traceback.format_exc(),'repository_calls':trace[start:]})
        else:results.append({'case':name,'status':'PASS','assertions':assertions-before,'repository_call_count':len(trace)-start})
    for code,kind,rule in [('LLM_RUNTIME','LLM_INSTANCE','llm.performance_profile'),('HOST','HOST','hardware.host_health'),('GPU_POOL','GPU','hardware.gpu_health')]:
        resource=classes['ResourceType'].objects.create(pk=code,code=code,enabled=True,sort_order=1,asset_selector={'asset_types':[kind],'labels':{'input_source':'INFERENCE_SNAPSHOT' if code=='LLM_RUNTIME' else 'HARDWARE_SNAPSHOT'}})
        item=classes['InspectionItem'].objects.create(pk=rule,code=rule,enabled=True,rule_config={})
        item.resource_types=types.SimpleNamespace(enabled=True,resource_type=resource)
        classes['InspectionItemResourceType'].objects.create(inspection_item=item,resource_type=resource,enabled=True,resource_type_id=resource.pk)
    env=Env.objects.create(pk='grid-env',slug='grid-env',environment_type='DEV',is_active=True,metadata={'local_mapping':dict(store.MOCK_METADATA)})
    def metric(field):
        src,unit,out,conversion=store.FIELD_SPECS[field]
        return {'standard_field':field,'source_metric':src,'source_type':store.source_type(field),'source_unit':unit,'output_unit':out,'conversion':conversion,
                'labels':{'engine_id':store.MOCK_INFERENCE_ENGINE['engine_id']} if field in store.INFERENCE_FIELD_SPECS else {},'window_seconds':300,'step_seconds':60}
    def package(fields=None):return {'schema_version':store.SCHEMA_VERSION,'cluster':{'cluster_uid':'grid-cluster','monitor_cluster_id':'grid-monitor','display_name':'Signed offline tuple'},'metrics':[metric(f)for f in (fields if fields is not None else store.INFERENCE_FIELD_SPECS)]}
    def setup(fields=None,fixture='complete',name='batch'):
        content,canonical,digest=store.validate_content(package(fields),cluster_uid='grid-cluster',monitor_cluster_id='grid-monitor')
        rev=classes['MappingRevision'].objects.create(pk='rev-'+name,version=1,canonical_json=canonical,content_hash=digest)
        bundle=classes['MappingBundle'].objects.create(pk='bundle-'+name,environment=env,source_ref='demo-monitor',cluster_uid='grid-cluster',monitor_cluster_id='grid-monitor',head_version=1,head_revision=rev,active_revision=rev)
        bound=loop.binding(bundle,rev,fixture,1,int(now.timestamp())-600,int(now.timestamp())-300,60)
        receipt=classes['MappingValidation'].objects.create(pk='receipt-'+name,bundle=bundle,revision=rev,kind='MOCK',content_hash=digest,binding=bound,result={'status':'MOCK_VERIFIED','raw_hash':'activation-hash'},valid_until=now+timedelta(minutes=10))
        bundle.latest_validation=receipt
        activation=classes['MappingActivation'].objects.create(bundle=bundle,revision=rev,validation=receipt)
        return bundle,rev,bound,content,{'environment_id':env.pk,'source_ref':'demo-monitor','cluster_uid':bundle.cluster_uid,'bundle_id':bundle.pk}
    def inputs(fields=None,fixture='complete',name='batch'):
        b,r,bound,p,scope=setup(fields,fixture,name);raws,values=loop.fetch(bound,p);return b,r,bound,p,scope,raws,values
    def request(fields=None,fixture='complete',name='batch'):
        b,r,bound,p,scope,raws,values=inputs(fields,fixture,name)
        return mi.request_for_values(bound,values,batch_id=name,revision_id=r.pk,content_hash=r.content_hash)
    def clear_data():
        for name in ['MappingBundle','MappingRevision','MappingValidation','MappingActivation','MappingCollection','InferencePerformanceSnapshot','HardwareSnapshot','Asset','InspectionRun','InspectionItemRun','InspectionRunEvent']:classes[name].objects.rows.clear()
    def lifecycle(fields=None,fixture='complete',name='batch'):
        clear_data();bundle,rev,bound,p,scope=setup(fields,fixture,name)
        batch=loop.collect(scope=scope,expected_active=1,idempotency_key=name)
        check(batch.status=='RUN_CREATED',str((batch.status,batch.error_code,[x for x in trace[-100:] if x[0]=='observed.exception'])));check(not batch.error_code,batch.error_code);check(batch.run is not None)
        eq(batch.run.config_snapshot['trigger_options']['ai_mode'],'DISABLED')
        quality=coverage.mapping_input_quality(batch.run);check(not quality['binding_errors'],repr(quality));check(quality['valid_fields']>=20 if fields is None else quality['valid_fields']>0)
        eq(loop.collect(scope=scope,expected_active=1,idempotency_key=name).pk,batch.pk)
        for item_run in classes['InspectionItemRun'].objects.rows:
            check(bool(item_run.asset_scope['asset_ids']),'Real item scope must contain its exact source assets')
        eq(len(classes['InspectionRun'].objects.rows),1);eq(sum(x[0]=='enqueue' for x in trace if x[0]=='enqueue')>=1,True)
        return batch
    case('complete20-default-real-collect-ingest-trigger-scope-freeze-quality',lifecycle)
    case('legal-zero-default-lifecycle',lambda:lifecycle(fixture='zero'))
    for field in store.INFERENCE_FIELD_SPECS:
        case('missing-'+field,lambda field=field:rejects(request,[f for f in store.INFERENCE_FIELD_SPECS if f!=field]))
        def nan(field=field):
            b,r,bound,p,scope,raws,values=inputs();values[field]=float('nan');rejects(mi.request_for_values,bound,values,batch_id='nan',revision_id=r.pk,content_hash=r.content_hash)
            index=list(store.INFERENCE_FIELD_SPECS).index(field);raw=copy.deepcopy(raws[index]);raw['series'][0]['value']=float('nan')
            spec={k:bound[k]for k in ['source_ref','environment_id','cluster_uid','monitor_cluster_id','fixture','seed','start','end','step']};spec['counter']=p['metrics'][index]['source_metric'];rejects(sim.normalize,raw,spec,p['metrics'][index])
        case('nan-'+field,nan)
    for group in ('ttft','tpot','e2e'):
        def inverted(group=group):
            b,r,bound,p,scope,raws,values=inputs();values['llm.'+group+'.p95_ms']=0
            rejects(mi.request_for_values,bound,values,batch_id='bad-order',revision_id=r.pk,content_hash=r.content_hash)
        case('percentile-order-'+group,inverted)
    for kind in ('scope','engine','environment','unit','window','replica','time-quantile','duplicate-series','missing-proof','quality'):
        def invalid_raw(kind=kind):
            b,r,bound,p,scope,raws,values=inputs();idx=list(store.INFERENCE_FIELD_SPECS).index('llm.ttft.p95_ms');raw=copy.deepcopy(raws[idx]);mapped=p['metrics'][idx]
            spec={k:bound[k]for k in ['source_ref','environment_id','cluster_uid','monitor_cluster_id','fixture','seed','start','end','step']};spec['counter']=mapped['source_metric']
            if kind=='scope':raw['cluster_uid']='other'
            elif kind=='engine':raw['engine']['engine_id']='other'
            elif kind=='environment':raw['environment_id']='other'
            elif kind=='unit':raw['unit']='seconds'
            elif kind=='window':raw['series'][0]['window_end']-=1
            elif kind=='replica':raw['series'][0]['replica_id']='other'
            elif kind=='time-quantile':raw['series'][0]['semantics']='time_quantile'
            elif kind=='duplicate-series':raw['series'].append(copy.deepcopy(raw['series'][0]))
            elif kind=='missing-proof':raw['series'][0].pop('semantics')
            else:raw['series'][0]['quality']='MISSING'
            rejects(sim.normalize,raw,spec,mapped)
        case('raw-reject-'+kind,invalid_raw)
    for key in ('cluster_uid','monitor_cluster_id'):
        def static(key=key):
            p=package();p['cluster'][key]='other';rejects(store.validate_content,p,cluster_uid=p['cluster']['cluster_uid'],monitor_cluster_id=p['cluster']['monitor_cluster_id'])
        case('static-binding-reject-'+key,static)
    def freezing():
        batch=lifecycle();prov=batch.evidence;ids=prov['source_snapshot_ids']['INFERENCE_SNAPSHOT'];row=classes['InferencePerformanceSnapshot'].objects.rows[0]
        later=classes['InferencePerformanceSnapshot'].objects.create(**{**row.__dict__,'pk':'competing-latest','sample_id':'other','window_end':now+timedelta(seconds=1)})
        start=len(trace);frozen=freezer.freeze_exact_inference_inputs(ids,environment_id=env.pk,provenance=prov,as_of=now)
        eq(next(iter(frozen['snapshots'].values()))['snapshot_id'],str(row.pk));check(all('window_end__lte' not in str(t)for t in trace[start:]));check(all('pk__in' in t[2] for t in trace[start:] if t[0]=='filter'))
        for key in ('environment_id','source_ref','window_start','window_end','batch_id','revision_id','content_hash','cluster_uid','monitor_cluster_id'):
            bad=copy.deepcopy(prov);bad[key]='other';rejects(freezer.freeze_exact_inference_inputs,ids,environment_id=env.pk,provenance=bad,as_of=now)
        for key in ('engine_id','engine_type','model_name','source','sample_id'):
            old=getattr(row,key);setattr(row,key,'other');rejects(freezer.freeze_exact_inference_inputs,ids,environment_id=env.pk,provenance=prov,as_of=now);setattr(row,key,old)
        rejects(freezer.freeze_exact_inference_inputs,ids+ids,environment_id=env.pk,provenance=prov,as_of=now)
        rejects(freezer.freeze_exact_inference_inputs,[],environment_id=env.pk,provenance=prov,as_of=now)
        bad=copy.deepcopy(prov);bad['source_snapshot_ids']['INFERENCE_SNAPSHOT']=['missing'];rejects(freezer.freeze_exact_inference_inputs,['missing'],environment_id=env.pk,provenance=bad,as_of=now)
    case('exact-freezer-negative-matrix-and-latest-competition',freezing)
    case('hardware-only-default-compatible',lambda:lifecycle(['host.cpu_busy_ratio'],name='hardware'))
    case('mixed-source-default-and-consumer-partitions',lambda:lifecycle([*store.INFERENCE_FIELD_SPECS,'host.cpu_busy_ratio'],name='mixed'))
    def ordinary():
        batch=lifecycle();before=len(trace);run=trigger.create_manual_inspection_run(environment=env,resource_type_codes=['LLM_RUNTIME'],ai_mode='DEFERRED')
        check('mapping_inputs'not in run.config_snapshot);eq(run.config_snapshot['trigger_options']['ai_mode'],'DEFERRED');check(any('window_end__lte' in str(t)for t in trace[before:]));eq(run.config_snapshot['input']['source_type'],'INFERENCE_SNAPSHOT')
    case('ordinary-nonmapping-latest-behavior-retained',ordinary)
    def incomplete_collect():
        clear_data();b,r,bound,p,scope=setup([f for f in store.INFERENCE_FIELD_SPECS if f!='llm.ttft.p99_ms']);batch=loop.collect(scope=scope,expected_active=1,idempotency_key='incomplete')
        eq(batch.status,'FAILED');eq(len(classes['InferencePerformanceSnapshot'].objects.rows),0);eq(len(classes['InspectionRun'].objects.rows),0)
    case('incomplete20-default-collect-no-inference-ingest-or-run',incomplete_collect)
    def same_window():
        batch=lifecycle();before=len(classes['InspectionRun'].objects.rows)
        bundle=batch.bundle;scope={'environment_id':env.pk,'source_ref':'demo-monitor','cluster_uid':bundle.cluster_uid,'bundle_id':bundle.pk}
        second=loop.collect(scope=scope,expected_active=1,idempotency_key='second-batch')
        eq(second.status,'FAILED');check(second.error_code.startswith('TRIGGER:'));eq(len(classes['InspectionRun'].objects.rows),before)
        eq(len(classes['InferencePerformanceSnapshot'].objects.rows),1)
    case('same-window-ingest-reuse-rejected-as-wrong-batch',same_window)
    for fixture in ('missing','no-data','wrong-unit'):
        def invalid_collect(fixture=fixture):
            clear_data();b,r,bound,p,scope=setup(fixture=fixture);batch=loop.collect(scope=scope,expected_active=1,idempotency_key='bad-'+fixture)
            eq(batch.status,'FAILED');eq(len(classes['InferencePerformanceSnapshot'].objects.rows),0);eq(len(classes['InspectionRun'].objects.rows),0)
        case('default-collect-invalid-source-no-ingest-'+fixture,invalid_collect)
    def ai_and_environment():
        batch=lifecycle();p=batch.evidence;before=len(classes['InspectionRun'].objects.rows)
        rejects(trigger.create_manual_inspection_run,environment=env,resource_type_codes=['LLM_RUNTIME'],ai_mode='DEFERRED',explicit_hardware_snapshot_ids=[],explicit_inference_snapshot_ids=p['source_snapshot_ids']['INFERENCE_SNAPSHOT'],mapping_inputs=p)
        eq(len(classes['InspectionRun'].objects.rows),before)
        old=env.is_active;env.is_active=False
        try:rejects(store.check_mock_environment,env,'demo-monitor')
        finally:env.is_active=old
    case('explicit-trigger-ai-disabled-and-server-mock-environment-guards',ai_and_environment)
    sys.settrace(None)
    modules=[store,sim,loop,mi,schemas,trigger,freezer,scopes,coverage,inference_ingest,hardware_ingest]
    origins={m.__name__:{'origin':str(Path(m.__file__).resolve()),'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}for m in modules}
    report={'cwd':str(Path.cwd()),'cli':[sys.executable,'-I','-B',str(Path(__file__).resolve())],'modules':origins,'cases':results,'case_count':len(results),'passed':sum(x['status']=='PASS'for x in results),'failed':sum(x['status']=='FAIL'for x in results),'assertions':assertions,'repository_trace':trace,'isolation':{'external_boundary':['fake ORM models/querysets/transaction rollback','fixed clock','worker enqueue only'], 'real':['schemas','query','normalize','fetch','collect','ingest_snapshot','hardware ingest','registry/evaluators','scope','trigger','freezers','coverage'],'algorithm_patches':[],'real_DB_persistence_or_concurrency':'NOT_RUN'}}
    print(json.dumps(report,indent=2,default=str));raise SystemExit(1 if report['failed']else 0)
if __name__=='__main__':main()
