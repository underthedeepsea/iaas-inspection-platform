"""Existing Asset/snapshot API boundary; no new storage or evaluation."""
from django.db import DatabaseError, connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.assets.models import Asset
from apps.inference_performance.api import _boundary, _endpoint
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inference_performance.services.ingest import resolve_environment
from .models import HardwareSnapshot
from .performance_profile import build_profile

LIMIT=20000


def writable():
    # Capability check is read-only; unknown never advertises a successful save.
    if connection.vendor != 'postgresql': return False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('transaction_read_only'), has_table_privilege(current_user, 'assets', 'UPDATE')")
            readonly, privilege=cursor.fetchone()
        return readonly=='off' and bool(privilege)
    except DatabaseError:
        return False


def environment(request):
    identifier=request.GET.get('environment_id')
    if not identifier:raise APIRequestError('VALIDATION_ERROR','environment_id is required')
    return resolve_environment(identifier)


@_boundary
@_endpoint('GET')
def profiles(request):
    env=environment(request)
    resource=request.GET.get('resource_type','HOST')
    if resource not in {'HOST','LLM_RUNTIME','CONTROL_PLANE','CLUSTER'}:raise APIRequestError('VALIDATION_ERROR','unsupported resource_type')
    portrait_mode=request.GET.get('view') == 'portraits'
    detail_kind=request.GET.get('kind'); detail_id=request.GET.get('id')
    if detail_kind is not None and detail_kind not in {'node','cluster','llm'}:raise APIRequestError('VALIDATION_ERROR','unsupported portrait kind')
    if bool(detail_kind) != bool(detail_id):raise APIRequestError('VALIDATION_ERROR','kind and id must be provided together')
    now=timezone.now()
    asset_rows=list(Asset.objects.filter(environment=env,asset_type__in=['HOST','CLUSTER','LLM_INSTANCE']).values('id','environment_id','external_key','name','asset_type','labels','topology','parent_id')[:2001])
    hw=list(HardwareSnapshot.objects.filter(environment=env,asset__asset_type='HOST',window_end__lte=now).order_by('-window_end','-pk').values('id','asset_id','source','window_start','window_end','payload','evaluation')[:LIMIT+1])
    llm=list(InferencePerformanceSnapshot.objects.filter(environment=env,window_end__lte=now).order_by('-window_end','-pk').values('id','asset_id','source','engine_id','engine_type','model_name','window_start','window_end','metrics','evaluation')[:LIMIT+1])
    for row in hw+llm:row['start']=row.pop('window_start');row['end']=row.pop('window_end')
    result=build_profile(asset_rows[:2000],hw[:LIMIT],llm[:LIMIT],now=now,resource_type=resource,portrait_mode=portrait_mode,detail_kind=detail_kind,detail_id=detail_id)
    result['truncated']=len(asset_rows)>2000 or len(hw)>LIMIT or len(llm)>LIMIT
    if result['truncated']:
        for cluster in result['clusters']:
            for group in [cluster['total'],cluster['classified'],*cluster['groups']]:
                group['note']='查询达到数量上限，节点/历史覆盖不完整，集群汇总未知；逐节点仍可查看。'
                if 'risk' in group: group['risk']['truncated'] = True
                for metric in group['metrics']:
                    metric.update(current=None,state='UNKNOWN',difference=None,high_observation=None,low_observation=None)
                    metric['history'].update(n=0,median=None,min=None,max=None,start=None,end=None,state='TRUNCATED_UNKNOWN')
    result['limits']={'assets':2000,'observations_per_kind':LIMIT}
    result['deployment_edit']={'writable':writable(),'note':'只读或权限未知时无法保存；只修改当前环境CLUSTER的部署方式'}
    return JsonResponse(result)


@_boundary
@_endpoint('PATCH')
def cluster_deployment(request, cluster_id):
    env=environment(request)
    payload=parse_json_object(request)
    if set(payload)!={'control_plane_deployment'} or not isinstance(payload['control_plane_deployment'],str) or payload['control_plane_deployment'] not in {'MIXED','DEDICATED'}:
        raise APIRequestError('VALIDATION_ERROR','only control_plane_deployment=MIXED/DEDICATED is accepted')
    if not writable():return api_error('READ_ONLY','当前环境只读或没有保存权限，部署方式未保存',status=403)
    try:
        with transaction.atomic():
            cluster=Asset.objects.select_for_update().filter(environment=env,asset_type='CLUSTER',pk=cluster_id).first()
            if cluster is None:return api_error('CLUSTER_NOT_FOUND','当前环境没有这个集群',status=404)
            cluster.labels={**cluster.labels,'control_plane_deployment':payload['control_plane_deployment']}
            cluster.save(update_fields=['labels'])
    except DatabaseError:
        return api_error('READ_ONLY','数据库拒绝保存，部署方式未保存',status=403)
    return JsonResponse({'cluster_id':str(cluster.pk),'control_plane_deployment':cluster.labels['control_plane_deployment']})
