"""Standalone S18 test; importing this module has no test-environment side effects."""

def main():
    """Standalone S18 offline verification. Run directly, without pytest/Django setup.

    Only Django import boundaries and ORM model names are stubbed. DB, transaction
    entry and HTTP response use fail closed. All mapping/schema/evaluator functions
    are imported from their actual repository modules, never extracted or patched.
    """
    import contextlib
    import copy
    import hashlib
    import importlib
    import json
    import sys
    import types
    from datetime import datetime, timezone
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))

    def forbidden(*args, **kwargs):
        raise AssertionError('Offline boundary forbids DB/HTTP access')

    class NoDatabase:
        def __getattr__(self, name):
            forbidden()

    class Atomic(contextlib.ContextDecorator):
        def __enter__(self):
            forbidden()
        def __exit__(self, *args):
            return False

    def atomic(function=None):
        return Atomic() if function is None else Atomic()(function)

    # Explicit isolated environment, no settings/config/.env imports or DB fixture.
    for name in ['django', 'django.db', 'django.utils', 'django.utils.timezone', 'django.http']:
        sys.modules[name] = types.ModuleType(name)
    sys.modules['django.db'].IntegrityError = type('IntegrityError', (Exception,), {})
    sys.modules['django.db'].transaction = types.SimpleNamespace(atomic=atomic)
    sys.modules['django.utils.timezone'].now = lambda: datetime.now(timezone.utc)
    sys.modules['django.utils'].timezone = sys.modules['django.utils.timezone']
    sys.modules['django.http'].JsonResponse = forbidden
    models = types.ModuleType('apps.core.models')
    for name in ['Environment', 'MappingBundle', 'MappingRevision', 'MappingValidation', 'MappingActivation', 'MappingCollection']:
        setattr(models, name, type(name, (), {'objects': NoDatabase()}))
    sys.modules['apps.core.models'] = models

    from apps.core import mapping_services as store, mapping_simulation as sim, mapping_loop as loop
    from apps.hardware_health import schemas, evaluator

    MODULES = [store, sim, loop, schemas, evaluator, importlib.import_module('apps.inference_performance.schemas'), importlib.import_module('apps.api.http')]
    ORIGINS = {module.__name__: {'origin': str(Path(module.__file__).resolve()), 'sha256': hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()} for module in MODULES}
    assert all(Path(row['origin']).is_relative_to(ROOT) for row in ORIGINS.values())

    BOUND = {'environment_id':'offline-s18','source_ref':'demo-monitor','cluster_uid':'s18-cluster','monitor_cluster_id':'s18-monitor','fixture':'complete','seed':1,'start':1700000000,'end':1700000300,'step':60}
    RESULTS = []
    ASSERTIONS = 0

    def check(condition, message='assertion failed'):
        nonlocal ASSERTIONS
        ASSERTIONS += 1
        if not condition:
            raise AssertionError(message)

    def eq(actual, expected):
        check(actual == expected, f'{actual!r} != {expected!r}')

    def rejects(function, *args):
        nonlocal ASSERTIONS
        ASSERTIONS += 1
        try:
            function(*args)
        except store.MappingInputError:
            return
        raise AssertionError('Expected MappingInputError')

    def case(name, function):
        before = ASSERTIONS
        try:
            function()
        except Exception as exc:
            import traceback
            RESULTS.append({'case':name,'status':'FAIL','assertions':ASSERTIONS-before,'error':str(exc),'traceback':traceback.format_exc()})
        else:
            RESULTS.append({'case':name,'status':'PASS','assertions':ASSERTIONS-before})

    def metric(field='gpu.ecc_sbe_delta', bound=None):
        bound = bound or BOUND
        source, unit, output, conversion = store.FIELD_SPECS[field]
        return {'standard_field':field,'source_metric':source,'source_type':store.source_type(field),'source_unit':unit,'output_unit':output,'conversion':conversion,'labels':{'block_device':'nvme0n1'} if field.startswith('disk.') else {},'window_seconds':bound['end']-bound['start'],'step_seconds':bound['step']}

    def content(fields=('gpu.ecc_sbe_delta','gpu.ecc_dbe_delta'), bound=None):
        return {'schema_version':store.SCHEMA_VERSION,'cluster':{'cluster_uid':'s18-cluster','monitor_cluster_id':'s18-monitor','display_name':'S18 fixture'},'metrics':[metric(field,bound) for field in fields]}

    def validated(package):
        return store.validate_content(package,cluster_uid='s18-cluster',monitor_cluster_id='s18-monitor')

    def spec(bound=None, field='gpu.ecc_sbe_delta'):
        return {**(bound or BOUND),'counter':store.FIELD_SPECS[field][0]}

    def snapshot(bound=None, fields=('gpu.ecc_sbe_delta','gpu.ecc_dbe_delta'), pk='current'):
        bound = bound or BOUND
        package = content(fields,bound)
        validated(package)
        raws,values = loop.fetch(bound,package)
        payload = loop.hardware_payloads(types.SimpleNamespace(pk=pk,revision_id='s18-revision',binding=bound),values,package)[0]
        parsed,start,end = schemas.parse_request(payload)
        row=types.SimpleNamespace(pk=pk,payload=parsed,window_start=start,window_end=end,evaluation=None)
        return row,raws,values

    def positive():
        row,raws,values=snapshot()
        for field in store.COUNTER_FIELDS:
            point=values[field]
            eq(point['value'],5);eq(point['quality'],'VALID')
            eq(point['collected_at'],row.window_end.isoformat())
            eq(point['scope'],'DRAM');eq(point['semantics'],store.COUNTER_FIELDS[field][1])
        eq(len(raws[0]['series'][0]['points']),6)
        eq([p['timestamp'] for p in raws[0]['series'][0]['points'][:-1]],sim.window(BOUND['start'],BOUND['end'],60))
        eq(raws[0]['series'][0]['points'][-1]['timestamp'],BOUND['end'])
        eq(row.window_start.timestamp(),BOUND['start']);eq(row.window_end.timestamp(),BOUND['end'])
        result=evaluator.evaluate(row,[])
        check(any(issue['code']=='ECC_DBE_NEW' for issue in result['issues']))

    case('default-query-fetch-payload-schema-evaluator-monotonic',positive)

    def rate_consumer():
        end=BOUND['end']
        current={**BOUND,'start':end-120,'step':60}
        recent={**BOUND,'end':current['start'],'start':current['start']-270,'step':90}
        old={**BOUND,'end':recent['start'],'start':recent['start']-480,'step':120}
        rows=[snapshot(bound,('gpu.ecc_sbe_delta',),str(index))[0] for index,bound in enumerate([old,recent,current])]
        eq([row.payload['metrics']['gpu']['values']['ecc_sbe_delta']['value'] for row in rows],[4,3,2])
        captured=[]
        def trace(frame,event,arg):
            if frame.f_code is evaluator.evaluate.__code__ and event=='return':
                captured.append(frame.f_locals.get('rate'))
            return trace
        sys.settrace(trace)
        try:
            result=evaluator.evaluate(rows[-1],rows[:-1])
        finally:
            sys.settrace(None)
        eq(captured,[2/120])
        check(any(issue['code']=='ECC_SBE_ACCELERATING' for issue in result['issues']))
    case('actual-evaluator-rate-full-window-and-history-denominators',rate_consumer)

    def zero():
        row,_,values=snapshot({**BOUND,'fixture':'zero'})
        for point in values.values():eq(point['value'],0);eq(point['quality'],'VALID')
        result=evaluator.evaluate(row,[])
        eq(result['issues'],[]);eq(result['status'],'UNKNOWN')
    case('legal-zero-remains-valid-zero',zero)

    for fixture in ['counter-reset-middle','counter-reset-end']:
        def default_reset(fixture=fixture):
            row,_,values=snapshot({**BOUND,'fixture':fixture})
            for point in values.values():eq(point['quality'],'RESET');eq(point['value'],None)
            result=evaluator.evaluate(row,[])
            eq(result['diagnostics']['gpu/ecc_sbe_delta']['status'],'RESET')
            eq(result['status'],'UNKNOWN');eq(result['issues'],[])
        case('default-chain-'+fixture,default_reset)

    for fixture in ['counter-missing-start','counter-missing-end','counter-single-point','missing','no-data','wrong-unit']:
        case('default-fetch-reject-'+fixture,lambda fixture=fixture:rejects(loop.fetch,{**BOUND,'fixture':fixture},content()))

    for index in range(1,6):
        def visible_reset(index=index):
            raw=sim.query(spec());raw['series'][0]['points'][index]['value']=index-1
            point=sim.normalize(raw,spec(),metric())
            eq(point['quality'],'RESET');eq(point['value'],None)
            payload=loop.hardware_payloads(types.SimpleNamespace(pk='reset',revision_id='s18-revision',binding=BOUND),{'gpu.ecc_sbe_delta':point},content())[0]
            _,start,end=schemas.parse_request(payload)
            result=evaluator.evaluate(types.SimpleNamespace(pk='reset',payload=payload,window_start=start,window_end=end,evaluation=None),[])
            eq(result['diagnostics']['gpu/ecc_sbe_delta']['status'],'RESET');eq(result['status'],'UNKNOWN')
        case('visible-negative-difference-position-'+str(index),visible_reset)

    for index in range(6):
        def explicit_reset(index=index):
            raw=sim.query(spec());raw['series'][0]['points'][index].update(quality='RESET',value=None)
            point=sim.normalize(raw,spec(),metric());eq(point['quality'],'RESET');eq(point['value'],None)
        case('explicit-reset-including-boundaries-'+str(index),explicit_reset)

    mutations={
     'missing-interior':lambda r:r['series'][0]['points'].pop(2),
     'missing-start':lambda r:r['series'][0]['points'].pop(0),
     'missing-end':lambda r:r['series'][0]['points'].pop(),
     'empty':lambda r:r['series'][0].update(points=[]),
     'only-one-point':lambda r:r['series'][0].update(points=r['series'][0]['points'][:1]),
     'duplicate-time':lambda r:r['series'][0]['points'][2].update(timestamp=BOUND['start']),
     'unordered-time':lambda r:r['series'][0]['points'].reverse(),
     'extra-time':lambda r:r['series'][0]['points'].append(copy.deepcopy(r['series'][0]['points'][-1])),
     'multi-series':lambda r:r['series'].append(copy.deepcopy(r['series'][0])),
     'no-series':lambda r:r.update(series=[]),
     'endpoint':lambda r:r['series'][0].update(endpoint='other'),
     'cluster-label':lambda r:r['series'][0]['labels'].update(cluster_uid='other'),
     'extra-label':lambda r:r['series'][0]['labels'].update(gpu_uuid='other'),
     'source-metric':lambda r:r['series'][0].update(source_metric='demo.gpu.ecc_dbe'),
     'wrong-bit':lambda r:r['series'][0].update(semantics='DOUBLE_BIT'),
     'wrong-memory-scope':lambda r:r['series'][0].update(scope='SRAM'),
     'missing-semantics':lambda r:r['series'][0].pop('semantics'),
     'invalid-quality-shape':lambda r:r['series'][0]['points'][0].update(quality=[]),
     'missing-point-quality':lambda r:r['series'][0]['points'][0].pop('quality'),
     'unit':lambda r:r.update(unit='bytes'),
     'dstype':lambda r:r.update(dstype='GAUGE'),
     'source-ref':lambda r:r.update(source_ref='other'),
     'environment':lambda r:r.update(environment_id='other'),
     'monitor':lambda r:r.update(monitor_cluster_id='other'),
     'window':lambda r:r.update(end=BOUND['end']+60),
     'fixture-version':lambda r:r.update(fixture_version='other'),
    }
    for name,change in mutations.items():
        def invalid(change=change):
            raw=sim.query(spec());change(raw);rejects(sim.normalize,raw,spec(),metric())
        case('reject-source-'+name,invalid)
    for name,bad in [('nan',float('nan')),('inf',float('inf')),('negative',-1),('string','1'),('bool',True),('float-count',1.5),('null',None)]:
        def invalid_number(bad=bad):
            raw=sim.query(spec());raw['series'][0]['points'][2]['value']=bad;rejects(sim.normalize,raw,spec(),metric())
        case('reject-count-'+name,invalid_number)
    for key,bad in [('source_unit','bytes'),('output_unit','ratio'),('conversion','IDENTITY'),('source_type','GAUGE'),('source_metric','demo.gpu.xid_events'),('labels',{'gpu':'other'})]:
        def invalid_mapping(key=key,bad=bad):
            package=content();package['metrics'][0][key]=bad;rejects(validated,package)
            mapped=metric();mapped[key]=bad;rejects(sim.normalize,sim.query(spec()),spec(),mapped)
        case('reject-mapping-'+key,invalid_mapping)

    def max_counter():
        bound={**BOUND,'start':BOUND['end']-3600,'step':60}
        row,raws,values=snapshot(bound)
        eq(len(raws[0]['series'][0]['points']),61);eq(values['gpu.ecc_sbe_delta']['value'],60)
        check(schemas.parse_request(row.payload)[0] is row.payload)
    case('61-total-counter-points-accepted',max_counter)
    case('62-total-counter-points-rejected',lambda:rejects(sim.query,spec({**BOUND,'start':BOUND['end']-61,'step':1})))
    def raw62():
        bound={**BOUND,'start':BOUND['end']-61,'step':1}
        raw=sim.query(spec());raw.update(start=bound['start'],step=1)
        raw['series'][0]['points']=[{'timestamp':stamp,'value':i,'quality':'VALID'} for i,stamp in enumerate(range(bound['start'],bound['end']+1))]
        rejects(sim.normalize,raw,spec(bound),metric(bound=bound))
    case('normalizer-independently-rejects-62-points',raw62)

    def minimum():
        bound={**BOUND,'start':BOUND['end']-60,'step':60}
        _,raws,values=snapshot(bound)
        eq(len(raws[0]['series'][0]['points']),2);eq(values['gpu.ecc_sbe_delta']['value'],1)
    case('two-boundaries-one-ordinary-grid-point-valid',minimum)

    def gauge_events_regression():
        package=content(tuple(field for field in store.FIELD_SPECS if field not in store.COUNTER_FIELDS))
        validated(package);raws,values=loop.fetch(BOUND,package)
        eq(values['host.cpu_busy_ratio'],.41);eq(values['gpu.temperature_celsius'],41.)
        eq(values['disk.read_latency_avg_ms'],2.);eq(values['disk.write_latency_avg_ms'],3.)
        eq(values['gpu.memory_used_bytes'],8*1024**3);eq(values['host.memory_total_bytes'],64*1024**3)
        eq(values['gpu.xid_events'][0]['code'],79)
        for raw in raws:
            if raw['dstype']=='GAUGE':eq(len(raw['series'][0]['points']),5);check(all(p['timestamp']<BOUND['end'] for p in raw['series'][0]['points']))
        payloads=loop.hardware_payloads(types.SimpleNamespace(pk='regression',revision_id='s18-revision',binding=BOUND),values,package)
        eq(len(payloads),2)
        for payload in payloads:schemas.parse_request(payload)
        _,zeros=loop.fetch({**BOUND,'fixture':'zero'},package)
        eq(zeros['gpu.xid_events'],[]);eq(zeros['host.cpu_busy_ratio'],0.)
        rejects(loop.fetch,{**BOUND,'fixture':'capacity-overflow'},package)
        rejects(loop.fetch,{**BOUND,'fixture':'missing'},package)
        rejects(loop.fetch,{**BOUND,'fixture':'wrong-unit'},package)
        rejects(loop.fetch,{**BOUND,'fixture':'no-data'},package)
        for field in ['gpu.xid_events','host.cpu_busy_ratio']:
            raw=sim.query(spec(field=field));raw['unit']='invalid';rejects(sim.normalize,raw,spec(field=field),metric(field))
    case('gauge-events-capacities-and-real-schema-regression',gauge_events_regression)

    def gauge61():
        bound={**BOUND,'start':BOUND['end']-61,'step':1};field='host.cpu_busy_ratio'
        raw=sim.query(spec(bound,field));eq(len(raw['series'][0]['points']),61)
        eq(sim.normalize(raw,spec(bound,field),metric(field,bound)),.41)
    case('gauge-original-61-grid-points-still-valid',gauge61)

    def canonical():
        package=content();clean,canonical,sha=validated(package)
        eq(clean,package);eq(hashlib.sha256(canonical.encode()).hexdigest(),sha)
        for field in store.COUNTER_FIELDS:eq(store.source_type(field),'COUNTER')
    case('counter-whitelist-canonical-json-and-sha',canonical)

    if __name__=='__main__':
        after={module.__name__:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in MODULES}
        check(after=={name:row['sha256'] for name,row in ORIGINS.items()},'source changed during test run')
        report={'cwd':str(Path.cwd()),'cli':[sys.executable,'-I','-B',str(Path(__file__).resolve())],
                'module_origins':ORIGINS,'source_after':after,'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'isolation':{'settings_loaded':'django.conf' in sys.modules,'orm':'fail-closed import names only','http':'fail-closed JsonResponse import boundary','algorithm_patches':[]},
                'cases':RESULTS,'case_count':len(RESULTS),'passed':sum(r['status']=='PASS' for r in RESULTS),'failed':sum(r['status']=='FAIL' for r in RESULTS),'assertions':ASSERTIONS}
        print(json.dumps(report,indent=2,allow_nan=False))
        raise SystemExit(1 if report['failed'] else 0)


if __name__ == '__main__':
    main()
