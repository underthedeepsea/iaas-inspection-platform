from copy import deepcopy
import hashlib
import json
from django.db import transaction
from django.utils import timezone
from apps.assets.models import Asset
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inference_performance.schemas import _error, _timestamp
from .models import HardwareSnapshot
from .schemas import parse_request
from .evaluator import evaluate

SOURCE='HARDWARE_SNAPSHOT'


@transaction.atomic
def ingest(payload):
    from apps.inference_performance.services.ingest import resolve_environment, IdempotencyConflict
    raw,start,end=parse_request(payload)
    environment=resolve_environment(raw['environment_id'])
    # Environment lock covers first asset creation and same source/sample races.
    type(environment).objects.select_for_update().get(pk=environment.pk)
    canonical=deepcopy(raw);canonical['environment_id']=str(environment.pk)
    existing=HardwareSnapshot.objects.filter(environment=environment,source=raw['source'],sample_id=raw['sample_id']).first()
    if existing:
        original={k:v for k,v in existing.payload.items() if not k.startswith('_')}
        if original!=canonical: raise IdempotencyConflict()
        return existing,False
    identity=[raw['kind'],raw['host_id'],raw['identity'].get('gpu_uuid')]
    key='hardware:'+hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()
    asset,_=Asset.objects.get_or_create(environment=environment,external_key=key,defaults={
        'asset_type':raw['kind'],'name':raw['identity'].get('gpu_uuid',raw['host_id']),
        'labels':{'input_source':SOURCE,'host_id':raw['host_id'],**raw['identity']}})
    history=list(HardwareSnapshot.objects.filter(asset=asset).order_by('window_end','pk'))
    if history and start<history[-1].window_end: raise IdempotencyConflict()
    xid_point=raw['metrics'].get('gpu', {}).get('values', {}).get('xid_events', {})
    old_xids={event['event_id']:event for row in history for event in (row.payload['metrics'].get('gpu', {}).get('values', {}).get('xid_events', {}).get('value') or [])}
    for event in (xid_point.get('value') or []):
        if event['event_id'] in old_xids:
            raise IdempotencyConflict()
    canonical['_inference']=[]
    for engine in raw['bindings']['engines']:
        query=InferencePerformanceSnapshot.objects.filter(environment=environment,**engine)
        if not query.exists(): _error('binding requires an existing same-environment engine','bindings')
        joined=query.filter(window_start__lt=end,window_end__gt=start,window_end__lte=end).order_by('-window_end','pk').first()
        if joined:
            canonical['_inference'].append({'snapshot_id':str(joined.pk),'asset_id':str(joined.asset_id),
                'window_start':joined.window_start.isoformat(),'window_end':joined.window_end.isoformat(),
                'metrics':deepcopy(joined.metrics),'evaluation':deepcopy(joined.evaluation),'engine':engine})
    all_events={k:v for row in history for k,v in row.evaluation.get('pending_hardware_events',{}).items()}
    if 'hardware_reverification' in canonical:
        att=canonical['hardware_reverification']; performed=_timestamp(att['performed_at'],'performed_at')
        for event_id in att['event_ids']:
            event=all_events.get(event_id)
            if not event or performed<=_timestamp(event['occurred_at'],'occurred_at'):
                _error('attestation must reference a prior event on this device','hardware_reverification')
    snapshot=HardwareSnapshot.objects.create(environment=environment,asset=asset,source=raw['source'],sample_id=raw['sample_id'],window_start=start,window_end=end,payload=canonical)
    snapshot.evaluation=evaluate(snapshot,history)
    snapshot.save(update_fields=['evaluation'])
    return snapshot,True


def freeze_hardware_inputs(asset_ids,*,as_of=None):
    as_of=as_of or timezone.now();snapshots={}
    for asset_id in asset_ids:
        row=HardwareSnapshot.objects.filter(asset_id=asset_id,window_end__lte=as_of,created_at__lte=as_of).order_by('-window_end','pk').first()
        snapshots[str(asset_id)]=None if row is None else {
            'snapshot_id':str(row.pk),'asset_id':str(asset_id),'environment_id':str(row.environment_id),
            'window_start':row.window_start.isoformat(),'window_end':row.window_end.isoformat(),
            'created_at':row.created_at.isoformat(),'frozen_at':as_of.isoformat(),
            'evaluation':deepcopy(row.evaluation),'payload':deepcopy(row.payload)}
    return {'source_type':SOURCE,'as_of':as_of.isoformat(),'snapshots':snapshots}


class HardwareInputReader:
    source_type=SOURCE
    def __init__(self,*,assets,frozen): self._assets=assets;self._frozen=frozen
    def assets(self): return list(self._assets)
    def hardware_input(self,asset_id): return self._frozen.get(str(asset_id))
