"""Service-owned mock validation, activation and exact-input collection lifecycle."""
import hashlib,json
from datetime import timedelta,datetime,timezone as utc
from pathlib import Path
from django.db import transaction, connection
from django.utils import timezone
from . import mapping_services as store,mapping_simulation as sim,mapping_query
from .models import MappingValidation,MappingActivation,MappingCollection


class ValidationRejected(store.MappingInputError):pass


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def versions():
    from apps.hardware_health import schemas,evaluator
    from apps.inference_performance import schemas as inference_schema
    return {'adapter':sim.FIXTURE_VERSION,'validator':'mapping-loop-v2-exact-inference','mapping_schema':store.SCHEMA_VERSION,'inference_schema':hashlib.sha256(Path(inference_schema.__file__).read_bytes()).hexdigest(),'inference_policy':hashlib.sha256((Path(inference_schema.__file__).parent/'services'/'policy.py').read_bytes()).hexdigest(),'hardware_schema':hashlib.sha256(Path(schemas.__file__).read_bytes()).hexdigest(),'hardware_policy':hashlib.sha256(Path(evaluator.__file__).read_bytes()).hexdigest()}
def lock(scope):
    from .models import Environment
    environment = store._environment(scope['environment_id'],scope['source_ref'])
    Environment.objects.select_for_update().get(pk=environment.pk)
    return store._bundle(scope['bundle_id'],scope['environment_id'],scope['source_ref'],scope['cluster_uid'])
def current(bundle,expected_head):
    store.validate_version(expected_head)
    if bundle.head_version!=expected_head:raise store.MappingConflict(bundle.head_version)
    revision=bundle.head_revision
    content,canonical,hashed=store.validate_content(json.loads(revision.canonical_json),cluster_uid=bundle.cluster_uid,monitor_cluster_id=bundle.monitor_cluster_id)
    if canonical!=revision.canonical_json or hashed!=revision.content_hash:raise ValidationRejected('Stored revision integrity mismatch.')
    return revision,content

def binding(bundle,revision,fixture,seed,start,end,step):
    try:
        sim.window(start,end,step)
    except store.MappingInputError as exc:
        exc.path = "step" if type(step) is not int or step <= 0 or (type(start) is int and type(end) is int and step > end-start > 0) else "start" if type(start) is not int else "end"
        raise
    if fixture not in sim.FIXTURES or type(seed)is not int or not 0<=seed<=9999:raise ValidationRejected('Unknown fixture/seed.')
    return {'environment_id':str(bundle.environment_id),'source_ref':bundle.source_ref,'cluster_uid':bundle.cluster_uid,'monitor_cluster_id':bundle.monitor_cluster_id,'revision_id':str(revision.pk),'content_hash':revision.content_hash,'fixture':fixture,'seed':seed,'start':start,'end':end,'step':step,'versions':versions()}

def fetch(binding,content,*,query_executor=None):
    budget = mapping_query.QueryBudget(len(content['metrics']))
    raws=[];values={};raws_by_field={}
    for metric in content['metrics']:
        if metric['window_seconds']!=binding['end']-binding['start'] or metric['step_seconds']!=binding['step']:raise ValidationRejected('Observation window must match every mapping.')
        spec={key:binding[key]for key in ['source_ref','environment_id','cluster_uid','monitor_cluster_id','fixture','seed','start','end','step']};spec['counter']=metric['source_metric']
        if metric['standard_field'].startswith(('disk.','filesystem.')):spec['resource_labels']=dict(metric['labels'])
        if query_executor is None:
            raw = mapping_query.execute(spec, budget=budget)
        else:
            # Preserve the explicit executor contract used by offline callers.
            budget.enter_attempt()
            raw = query_executor(spec)
        budget.check_complete()
        values[metric['standard_field']]=sim.normalize(raw,spec,metric);raws.append(raw);raws_by_field[metric['standard_field']]=raw
    sim.validate_capacities(raws_by_field)
    from .mapping_inference import request_for_values
    if any(field.startswith('llm.') for field in values):
        request_for_values(binding, values, batch_id='validation', revision_id=binding['revision_id'], content_hash=binding['content_hash'])
    budget.check_complete()
    return raws,values

@transaction.atomic
def validate(*,scope,expected_head,kind,fixture='complete',seed=1,start,end,step):
    bundle=lock(scope);revision,content=current(bundle,expected_head)
    if kind not in {'STRUCTURE','MOCK'}:raise ValidationRejected('Unknown validation kind.')
    bound=binding(bundle,revision,fixture,seed,start,end,step)
    result={'status':'CONFIG_VALID','coverage':None,'errors':[]}
    if kind=='MOCK':
        try:
            raws,values=fetch(bound,content);result={'status':'MOCK_VERIFIED','coverage':1.0,'mapped_values':values,'raw_hash':digest(raws),'errors':[]}
        except store.MappingInputError:
            result={'status':'FAILED','coverage':0.0,'errors':['MOCK_DATA_INVALID']}
    receipt=MappingValidation.objects.create(bundle=bundle,revision=revision,kind=kind,content_hash=revision.content_hash,binding=bound,result=result,valid_until=timezone.now()+timedelta(minutes=10))
    bundle.latest_validation=receipt;bundle.save(update_fields=['latest_validation'])
    return receipt


def checked_receipt(bundle,revision,validation_id,*,activation_admission=True):
    try:receipt=MappingValidation.objects.get(pk=validation_id,bundle=bundle,revision=revision)
    except MappingValidation.DoesNotExist:raise ValidationRejected('Missing or wrong-scope validation receipt.')from None
    if activation_admission and bundle.latest_validation_id!=receipt.pk:
        raise ValidationRejected('Receipt was superseded by a later validation.')
    if receipt.kind!='MOCK' or receipt.result.get('status')!='MOCK_VERIFIED' or (activation_admission and receipt.valid_until<=timezone.now()) or receipt.content_hash!=revision.content_hash or receipt.binding.get('versions')!=versions() or receipt.binding.get('environment_id')!=str(bundle.environment_id) or receipt.binding.get('source_ref')!=bundle.source_ref or receipt.binding.get('cluster_uid')!=bundle.cluster_uid:
        raise ValidationRejected('Receipt is expired, stale, failed or bound to another contract.')
    return receipt

@transaction.atomic
def activate(*,scope,expected_head,expected_active,content_hash,validation_id,idempotency_key,reason,actor_label):
    store._write_input(expected_head,reason,actor_label);store.validate_version(expected_active);store._token(idempotency_key,'idempotency_key')
    bundle=lock(scope)
    request_hash=digest({'scope':{key:str(value)for key,value in scope.items()},'expected_head':expected_head,'expected_active':expected_active,'content_hash':content_hash,'validation_id':str(validation_id),'reason':reason,'actor_label':actor_label})
    old=MappingActivation.objects.filter(bundle=bundle,idempotency_key=idempotency_key).first()
    if old:
        if old.request_hash!=request_hash:raise store.MappingConflict(bundle.head_version)
        return old
    revision,_=current(bundle,expected_head)
    if (bundle.active_revision.version if bundle.active_revision_id else 0)!=expected_active or content_hash!=revision.content_hash:raise store.MappingConflict(bundle.head_version)
    receipt=checked_receipt(bundle,revision,validation_id)
    event=MappingActivation.objects.create(bundle=bundle,revision=revision,previous_revision_id=bundle.active_revision_id,validation=receipt,idempotency_key=idempotency_key,request_hash=request_hash,reason=reason,actor_label=actor_label)
    bundle.active_revision=revision;bundle.save(update_fields=['active_revision']);return event


def hardware_payloads(batch,values,content=None):
    from apps.hardware_health.schemas import FIELDS
    bound=batch.binding;at=datetime.fromtimestamp(bound['end']-bound['step'],utc.utc).isoformat();payloads={}
    mappings={m['standard_field']:m for m in (content or {}).get('metrics',[])}
    def component(family,identity):
        points={key:{'value':None,'quality':'MISSING','collected_at':at}for key in FIELDS[family]}
        if family=='gpu':
            for key,semantic in [('ecc_sbe_delta','SINGLE_BIT'),('ecc_dbe_delta','DOUBLE_BIT')]:points[key].update(source_metric='UNCONFIGURED',semantics=semantic,scope='DRAM')
        return {'identity':identity,'values':points}
    for field,value in values.items():
        if field in store.INFERENCE_FIELD_SPECS:continue
        family,name=field.split('.');kind='GPU'if family=='gpu'else'HOST'
        if kind not in payloads:
            payloads[kind]={'source':'demo-monitor','environment_id':bound['environment_id'],'sample_id':f'mapping:{batch.pk}:{kind}','window_start':datetime.fromtimestamp(bound['start'],utc.utc).isoformat(),'window_end':datetime.fromtimestamp(bound['end'],utc.utc).isoformat(),'host_id':bound['monitor_cluster_id'],'config_id':str(batch.revision_id),'kind':kind,'identity':{}if kind=='HOST'else{'gpu_uuid':bound['cluster_uid']+'-synthetic-gpu','model':'SYNTHETIC'},'metrics':{'host':component('host',{})}if kind=='HOST'else{},'bindings':{'complete':False,'engines':[]}}
        identity={};key=family
        if family in {'disk','filesystem'}:
            identity=dict(mappings.get(field,{}).get('labels',{}))
            expected=store.MOCK_FILESYSTEM_IDENTITY if family=='filesystem' else {'block_device':'nvme0n1'}
            if identity!=expected:raise store.MappingInputError('Payload requires source-bound resource identity.')
            key='filesystem:root' if family=='filesystem' else 'disk:'+identity['block_device']
        group=payloads[kind]['metrics'].setdefault(key,component(family,identity))
        group['values'][name]=dict(value) if field in store.COUNTER_FIELDS or field=='gpu.xid_events' and type(value)is dict else {'value':value,'quality':'VALID','collected_at':at}
    return list(payloads.values())


@transaction.atomic
def set_enabled(*, scope, expected_head, expected_active, enabled, validation_id,
                idempotency_key, reason, actor_label):
    """Local actor labels are audit descriptions, not authenticated identities."""
    from .models import MappingEnableEvent
    store._write_input(expected_head, reason, actor_label)
    store.validate_version(expected_active)
    store._token(idempotency_key, 'idempotency_key')
    if type(enabled) is not bool:
        raise store.MappingInputError('enabled must be an exact boolean.')
    bundle = lock(scope)
    request_hash = digest({'scope': {key: str(value) for key, value in scope.items()},
        'expected_head': expected_head, 'expected_active': expected_active,
        'enabled': enabled, 'validation_id': str(validation_id) if validation_id else None,
        'reason': reason, 'actor_label': actor_label})
    old = MappingEnableEvent.objects.filter(bundle=bundle, idempotency_key=idempotency_key).first()
    if old:
        if old.request_hash != request_hash:
            raise store.MappingConflict(bundle.head_version)
        return old
    active = bundle.active_revision
    if bundle.head_version != expected_head or (active.version if active else 0) != expected_active:
        raise store.MappingConflict(bundle.head_version)
    receipt = None
    if enabled:
        if active is None or active.pk != bundle.head_revision_id:
            raise ValidationRejected('Enable requires a validated current active head.')
        revision, _ = current(bundle, expected_head)
        receipt = checked_receipt(bundle, revision, validation_id)
    elif validation_id is not None:
        raise store.MappingInputError('Disable does not accept a validation receipt.')
    event = MappingEnableEvent.objects.create(bundle=bundle, enabled=enabled,
        previous_enabled=bundle.enabled, revision=active, validation=receipt,
        idempotency_key=idempotency_key, request_hash=request_hash,
        reason=reason, actor_label=actor_label)
    bundle.enabled = enabled
    bundle.save(update_fields=['enabled'])
    return event


def collect(*,scope,expected_active,idempotency_key):
    # The phase commits below are part of the admission contract. An enclosing
    # caller transaction would hide them and prevent the pre-Run disable window.
    if connection.in_atomic_block:
        raise store.MappingInputError('Collection requires an outermost transaction boundary.')
    store.validate_version(expected_active,minimum=1);store._token(idempotency_key,'idempotency_key')
    with transaction.atomic(durable=True):
        bundle=lock(scope)
        environment=bundle.environment
        request_hash=digest({'scope':{key:str(value)for key,value in scope.items()},'expected_active':expected_active})
        old=MappingCollection.objects.filter(environment=environment,idempotency_key=idempotency_key).first()
        if old:
            if old.bundle_id!=bundle.pk or old.revision.version!=expected_active or old.request_hash!=request_hash:raise store.MappingConflict(bundle.head_version)
            return old
        if not bundle.enabled:
            raise ValidationRejected('Mapping bundle is disabled.')
        revision=bundle.active_revision
        if revision is None or revision.version!=expected_active:raise store.MappingConflict(bundle.head_version)
        activation=MappingActivation.objects.filter(bundle=bundle,revision=revision).order_by('-created_at').first()
        receipt=checked_receipt(bundle,revision,activation.validation_id,activation_admission=False)
        content,canonical,content_hash=store.validate_content(json.loads(revision.canonical_json),cluster_uid=bundle.cluster_uid,monitor_cluster_id=bundle.monitor_cluster_id)
        if canonical!=revision.canonical_json or content_hash!=revision.content_hash:raise ValidationRejected('Active revision integrity mismatch.')
        # Activation evidence expires for admission only. Each collection uses
        # a new server-owned complete window, retaining fixed fixture/seed/policy.
        live_binding=dict(receipt.binding)
        duration=receipt.binding['end']-receipt.binding['start']
        live_binding['end']=int(timezone.now().timestamp())//live_binding['step']*live_binding['step']
        live_binding['start']=live_binding['end']-duration
        sim.window(live_binding['start'],live_binding['end'],live_binding['step'])
        batch=MappingCollection.objects.create(environment=environment,bundle=bundle,activation=activation,revision=revision,idempotency_key=idempotency_key,request_hash=request_hash,binding=live_binding)

    # PREPARED is now durable. Fetch/ingest retains the frozen binding and revision;
    # no environment/bundle lock is held, so disable may commit during this phase.
    stage='FETCH'
    with transaction.atomic(durable=True):
        try:
            with transaction.atomic():
                raws,values=fetch(batch.binding,content)
                if not values:raise ValidationRejected('No assessable mapped values.')
                stage='INGEST'
                from apps.hardware_health.services import ingest
                from .mapping_inference import request_for_values
                request=request_for_values(batch.binding,values,batch_id=str(batch.pk),revision_id=str(revision.pk),content_hash=revision.content_hash)
                hardware=[ingest(payload)[0]for payload in hardware_payloads(batch,values,content)]
                inference=[]
                if request is not None:
                    from apps.inference_performance.services.ingest import ingest_snapshot
                    inference=[ingest_snapshot(request)[0]]
                snapshots=hardware+inference
                evidence={'batch_id':str(batch.pk),'revision_id':str(revision.pk),'content_hash':revision.content_hash,'validation_id':str(receipt.pk),'activation_id':str(activation.pk),'fixture':batch.binding['fixture'],'seed':batch.binding['seed'],'source_ref':bundle.source_ref,'environment_id':str(bundle.environment_id),'window_start':snapshots[0].window_start.isoformat(),'window_end':snapshots[0].window_end.isoformat(),'raw_responses':raws,'raw_hash':digest(raws),'activation_validation_raw_hash':receipt.result['raw_hash'],'mapped_values':values,'versions':versions(),'snapshot_ids':[str(row.pk)for row in snapshots],'asset_ids':[str(row.asset_id)for row in snapshots],'baseline_status':'NOT_READY','limitations':[f'{len(values)} mapped fields in this batch; remaining required fields MISSING/null.','No full37-field coverage or LLM snapshot; baseline may be NOT_READY.']}
                evidence.update(cluster_uid=bundle.cluster_uid,monitor_cluster_id=bundle.monitor_cluster_id,
                    source_snapshot_ids={'HARDWARE_SNAPSHOT':[str(row.pk)for row in hardware], 'INFERENCE_SNAPSHOT':[str(row.pk)for row in inference]},
                    source_asset_ids={'HARDWARE_SNAPSHOT':[str(row.asset_id)for row in hardware], 'INFERENCE_SNAPSHOT':[str(row.asset_id)for row in inference]})
                evidence['limitations']=['MOCK inputs only; baseline may be NOT_READY.']
                batch.evidence=evidence;batch.status='INGESTED'
                batch.save(update_fields=['evidence','status'])
        except Exception as exc:
            batch.status='FAILED';batch.error_code=(stage+':'+type(exc).__name__)[:64]
            batch.save(update_fields=['status','error_code']);batch.refresh_from_db();return batch
    # INGESTED and exact snapshot IDs are durable before the admission lock.
    # All admission/enable services lock environment, bundle, then collection.
    with transaction.atomic(durable=True):
        bundle=lock(scope)
        batch=MappingCollection.objects.select_for_update().get(pk=batch.pk)
        if not bundle.enabled:
            batch.status='BLOCKED';batch.error_code='BUNDLE_DISABLED'
            batch.save(update_fields=['status','error_code']);return batch
        stage='TRIGGER'
        try:
            with transaction.atomic():
                from apps.inspections.services.trigger import create_manual_inspection_run
                run=create_manual_inspection_run(environment=bundle.environment,resource_type_codes=['LLM_RUNTIME'if key.startswith('llm.')else'GPU_POOL'if key.startswith('gpu.')else'HOST'for key in values],ai_mode='DISABLED',explicit_hardware_snapshot_ids=evidence['source_snapshot_ids']['HARDWARE_SNAPSHOT'],explicit_inference_snapshot_ids=evidence['source_snapshot_ids']['INFERENCE_SNAPSHOT'] if inference else None,mapping_inputs=evidence)
                batch.run=run;batch.status='RUN_CREATED';batch.save(update_fields=['run','status'])
        except Exception as exc:
            batch.status='FAILED';batch.error_code=(stage+':'+type(exc).__name__)[:64]
            batch.save(update_fields=['status','error_code']);batch.refresh_from_db();return batch
    # Run and its frozen inputs commit before dispatch. No S25 recovery is implied.
    from apps.inspections.services.worker import enqueue_manual_inspection
    try:enqueue_manual_inspection(batch.run_id)
    except Exception as exc:
        batch.error_code='DISPATCH_'+type(exc).__name__[:48];batch.save(update_fields=['error_code'])
    return batch
