from django.http import JsonResponse
from django.db import transaction
from django.utils import timezone
from apps.api.http import parse_json_object, APIRequestError
from apps.inference_performance.api import _boundary, _endpoint
from apps.inference_performance.services.ingest import resolve_environment
from .models import HardwareSnapshot
from .services import ingest


def serialize(row):
    fresh=0<=(timezone.now()-row.window_end).total_seconds()<=300
    return {'snapshot_id':str(row.pk),'asset_id':str(row.asset_id),'asset_name':row.asset.name,
            'window_start':row.window_start.isoformat(),'window_end':row.window_end.isoformat(),
            'status':row.evaluation['status'] if fresh else 'UNKNOWN','freshness':'FRESH' if fresh else 'STALE',
            'metrics':row.payload['metrics'],'identity':row.payload['identity'],'host_id':row.payload['host_id'],
            'evaluation':row.evaluation}


@_boundary
@_endpoint('POST')
def snapshots(request):
    row,created=ingest(parse_json_object(request))
    return JsonResponse({'created':created,'profile':serialize(row)},status=201 if created else 200)


@_boundary
@_endpoint('GET')
def profiles(request):
    environment_id=request.GET.get('environment_id')
    if not environment_id: raise APIRequestError('VALIDATION_ERROR','environment_id is required')
    environment=resolve_environment(environment_id)
    resource=request.GET.get('resource_type','GPU_POOL')
    if resource not in {'GPU_POOL','HOST'}: raise APIRequestError('VALIDATION_ERROR','unsupported resource_type')
    rows=HardwareSnapshot.objects.filter(environment=environment,asset__asset_type='GPU' if resource=='GPU_POOL' else 'HOST').select_related('asset').order_by('asset_id','-window_end')
    seen=set();result=[]
    for row in rows:
        if row.asset_id not in seen: result.append(serialize(row));seen.add(row.asset_id)
        if len(result)>=200: break
    return JsonResponse({'profiles':result,'limit':200})


@_boundary
@_endpoint('POST')
@transaction.atomic
def snapshots_batch(request):
    payload=parse_json_object(request)
    if set(payload)!={'samples'} or not isinstance(payload['samples'],list) or not 1<=len(payload['samples'])<=500:
        raise APIRequestError('VALIDATION_ERROR','samples must contain 1..500 full observations')
    rows=[ingest(sample) for sample in payload['samples']]
    return JsonResponse({'created_count':sum(created for _,created in rows),'profiles':[serialize(row) for row,_ in rows]},status=201)
