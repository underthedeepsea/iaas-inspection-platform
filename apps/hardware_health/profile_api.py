"""Existing Asset/snapshot API boundary; no new storage or evaluation."""
from django.db import DatabaseError, connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.assets.models import Asset
from apps.inference_performance.api import _boundary, _endpoint
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inference_performance.services.ingest import resolve_environment
from apps.inspections.models import ResourceType
from apps.inspections.services.scope import asset_ids_for_selectors
from .models import HardwareSnapshot
from .performance_profile import belongs, build_profile

LIMIT=20000
ASSET_LIMIT=2000
ASSET_FIELDS=('id','environment_id','external_key','name','asset_type','labels','topology','parent_id')


def scoped_members(env, asset_type, clusters, room, parent_ids=()):
    """Apply the existing membership semantics before the existing asset cap.

    Stream rather than materialize the environment: JSON labels can contain
    numbers or other values, and belongs() deliberately compares their string
    forms. SQL JSON equality alone would omit some valid members.
    """
    rows=[]
    parents={str(value) for value in parent_ids}
    candidates=Asset.objects.filter(environment=env,asset_type=asset_type).order_by('pk').values(*ASSET_FIELDS).iterator()
    for row in candidates:
        if str(row.get('parent_id') or '') not in parents and not any(belongs(row,cluster) for cluster in clusters):
            continue
        rows.append(row)
        if len(rows)>room:
            return rows[:room], True
    return rows, False


def scoped_k8s_rows(env, selector, requested_cluster):
    """Select matching cluster assets and their members before applying existing limits."""
    ids=asset_ids_for_selectors(env.pk,[selector or {}])
    if requested_cluster:
        ids=[value for value in ids if str(value) == requested_cluster]
    clusters=list(Asset.objects.filter(environment=env,asset_type='CLUSTER',id__in=ids).order_by('pk').values(*ASSET_FIELDS)[:ASSET_LIMIT+1])
    truncated=len(clusters)>ASSET_LIMIT
    clusters=clusters[:ASSET_LIMIT]
    if not clusters:
        return [], [], [], truncated
    room=ASSET_LIMIT-len(clusters)
    hosts,hosts_truncated=scoped_members(env,'HOST',clusters,room)
    truncated |= hosts_truncated
    room-=len(hosts)
    services,services_truncated=scoped_members(env,'LLM_INSTANCE',clusters,room,[host['id'] for host in hosts])
    truncated |= services_truncated
    return clusters+hosts+services, [host['id'] for host in hosts], [service['id'] for service in services], truncated


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
    if resource not in {'HOST','LLM_RUNTIME','CONTROL_PLANE','CLUSTER','K8S_CLUSTER'}:raise APIRequestError('VALIDATION_ERROR','unsupported resource_type')
    portrait_mode=request.GET.get('view') == 'portraits'
    detail_kind=request.GET.get('kind'); detail_id=request.GET.get('id')
    if detail_kind is not None and detail_kind not in {'node','cluster','llm'}:raise APIRequestError('VALIDATION_ERROR','unsupported portrait kind')
    if bool(detail_kind) != bool(detail_id):raise APIRequestError('VALIDATION_ERROR','kind and id must be provided together')
    now=timezone.now()
    profile_options={}
    if resource == 'K8S_CLUSTER':
        resource_type=ResourceType.objects.filter(code=resource,enabled=True).first()
        if resource_type is None:return api_error('RESOURCE_TYPE_NOT_FOUND','resource type does not exist',status=404)
        asset_rows,host_ids,service_ids,asset_truncated=scoped_k8s_rows(env,resource_type.asset_selector,request.GET.get('cluster_id'))
        profile_options['cluster_ids']=[row['id'] for row in asset_rows if row['asset_type']=='CLUSTER']
        hw_query=HardwareSnapshot.objects.filter(environment=env,asset_id__in=host_ids,window_end__lte=now)
        llm_query=InferencePerformanceSnapshot.objects.filter(environment=env,asset_id__in=service_ids,window_end__lte=now)
    else:
        asset_rows=list(Asset.objects.filter(environment=env,asset_type__in=['HOST','CLUSTER','LLM_INSTANCE']).values(*ASSET_FIELDS)[:ASSET_LIMIT+1])
        asset_truncated=len(asset_rows)>ASSET_LIMIT
        asset_rows=asset_rows[:ASSET_LIMIT]
        hw_query=HardwareSnapshot.objects.filter(environment=env,asset__asset_type='HOST',window_end__lte=now)
        llm_query=InferencePerformanceSnapshot.objects.filter(environment=env,window_end__lte=now)
    hw=list(hw_query.order_by('-window_end','-pk').values('id','asset_id','source','window_start','window_end','payload','evaluation')[:LIMIT+1])
    llm=list(llm_query.order_by('-window_end','-pk').values('id','asset_id','source','engine_id','engine_type','model_name','window_start','window_end','metrics','evaluation')[:LIMIT+1])
    for row in hw+llm:row['start']=row.pop('window_start');row['end']=row.pop('window_end')
    result=build_profile(asset_rows,hw[:LIMIT],llm[:LIMIT],now=now,resource_type=resource,portrait_mode=portrait_mode,detail_kind=detail_kind,detail_id=detail_id,**profile_options)
    result['truncated']=asset_truncated or len(hw)>LIMIT or len(llm)>LIMIT
    if result['truncated']:
        for cluster in result['clusters']:
            for group in [cluster['total'],cluster['classified'],*cluster['groups']]:
                group['note']='查询达到数量上限，节点/历史覆盖不完整，集群汇总未知；逐节点仍可查看。'
                if 'risk' in group: group['risk']['truncated'] = True
                for metric in group['metrics']:
                    metric.update(current=None,state='UNKNOWN',difference=None,high_observation=None,low_observation=None)
                    metric['history'].update(n=0,median=None,min=None,max=None,start=None,end=None,state='TRUNCATED_UNKNOWN')
    result['limits']={'assets':ASSET_LIMIT,'observations_per_kind':LIMIT}
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
