"""Read-only descriptive projection of retained observations. No health evaluation."""
from collections import defaultdict
from datetime import datetime, timedelta
from math import isfinite
from statistics import median

LINUX_MEMORY = {'os': 'LINUX', 'memory_available': 'MemAvailable', 'memory_total': 'MemTotal', 'unit': 'bytes'}
HOST_PLUGIN = {'id': 'gpu-host-health', 'version': '2.0.0'}
HISTORY_DAYS = 14


def number(value):
    return float(value) if type(value) in (int, float) and isfinite(value) else None


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return parsed if isinstance(parsed, datetime) and parsed.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def context_key(value):
    import json
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def window_time(row):
    start, end = timestamp(row.get('start')), timestamp(row.get('end'))
    return end if start and end and start < end else None


def describe(key, label, unit, observations, latest, now, *, current_allowed=True, missing_context=(), observation_time=None, value_kind='POINT', latest_observed=None):
    """Membership uses preceding windows; display times use actual point/window time."""
    def observed_time(row):
        return window_time(row) if value_kind == 'WINDOW_STATISTIC' else timestamp(observation_time(row)) if observation_time else None
    observed = [(row, observed_time(row), value) for row, value in observations if value is not None]
    # A point can precede its containing window end. Exclude the current row by
    # membership before using the point time; never let it count as its own history.
    prior = [(at, value) for row, at, value in observed if row is not latest and row['end'] < latest['end'] and at and now-timedelta(days=HISTORY_DAYS) <= at <= now]
    raw = next((value for row, value in observations if row is latest), None)
    if latest_observed is not None: raw = latest_observed
    at = observed_time(latest)
    fresh = at is not None and 0 <= (now-at).total_seconds() <= 180
    current = raw if fresh and current_allowed else None
    ready = len(prior) >= 2
    center = median([v for _, v in prior]) if ready else None
    extremes = [(row, at, value) for row, at, value in observed if at and now-timedelta(days=HISTORY_DAYS) <= at <= now]
    def extreme(high):
        if not extremes: return None
        row, when, value = (max if high else min)(extremes, key=lambda item:item[2])
        return {'at': when.isoformat(), 'value': value, 'value_kind': value_kind,
                'window_start': timestamp(row.get('start')).isoformat() if timestamp(row.get('start')) else None,
                'window_end': timestamp(row.get('end')).isoformat() if timestamp(row.get('end')) else None}
    return {'key': key, 'label': label, 'unit': unit, 'current': current, 'latest_observed': raw,
            'observed_at': at.isoformat() if at else None, 'collected_at': at.isoformat() if at and value_kind == 'POINT' else None,
            'value_kind': value_kind,
            'window_start': timestamp(latest.get('start')).isoformat() if timestamp(latest.get('start')) else None,
            'window_end': timestamp(latest.get('end')).isoformat() if timestamp(latest.get('end')) else None,
            'state': ('CURRENT_WINDOW_STATISTIC' if value_kind == 'WINDOW_STATISTIC' else 'CURRENT') if current is not None else 'HISTORICAL_OR_UNAVAILABLE',
            'history': {'n': len(prior), 'start': min((t for t, _ in prior), default=None).isoformat() if prior else None,
                        'end': max((t for t, _ in prior), default=None).isoformat() if prior else None,
                        'median': center, 'min': min(v for _, v in prior) if ready else None,
                        'max': max(v for _, v in prior) if ready else None,
                        'time_basis': value_kind, 'state': 'KNOWN_CONTEXT_ONLY' if ready else 'INSUFFICIENT_HISTORY'},
            'difference': current-center if current is not None and center is not None else None,
            'difference_scope': 'DESCRIPTIVE_KNOWN_CONTEXT_ONLY', 'missing_context': list(missing_context),
            'high_observation': extreme(True), 'low_observation': extreme(False)}


def point_time(row, component, key):
    p = row.get('payload', {}).get('metrics', {}).get(component, {}).get('values', {}).get(key, {})
    collected, end = timestamp(p.get('collected_at')), timestamp(row.get('end'))
    return collected if collected and end and 0 <= (end-collected).total_seconds() <= 180 else None


def reported_point(row, component, key):
    p = row.get('payload', {}).get('metrics', {}).get(component, {}).get('values', {}).get(key, {})
    return number(p.get('value')) if p.get('quality') == 'VALID' else None


def point(row, component, key):
    return reported_point(row, component, key) if point_time(row, component, key) else None


def current_point(row, component, key, now):
    collected = point_time(row, component, key) if row else None
    return point(row, component, key) if collected and 0 <= (now-collected).total_seconds() <= 180 else None


def node_context(row):
    p = row.get('payload', {})
    # Current editable Asset labels are never evidence of historic role/spec/config.
    return {'source': row.get('source'), 'host_id': p.get('host_id'), 'config_id': p.get('config_id'),
            'identity': p.get('identity'), 'host_semantics': p.get('host_semantics'),
            'memory_total_bytes': point(row, 'host', 'memory_total_bytes')}


def roles(asset):
    values = []
    for container in (asset.get('labels', {}), asset.get('topology', {})):
        for key in ('roles', 'role', 'node_roles'):
            value = container.get(key, [])
            values += value if isinstance(value, list) else [value]
    aliases = {'apiserver': 'API_SERVER', 'api-server': 'API_SERVER', 'api_server': 'API_SERVER', 'kube-apiserver': 'API_SERVER', 'etcd': 'ETCD', 'worker': 'WORKER'}
    return sorted({aliases.get(str(v).lower(), str(v).upper()) for v in values if v}) or ['UNKNOWN']


def belongs(asset, cluster):
    references = {str(cluster['id']), str(cluster.get('external_key', ''))}
    references |= {str(cluster.get('labels', {}).get(k)) for k in ('cluster_id', 'cluster_uid') if cluster.get('labels', {}).get(k)}
    candidates = [asset.get('parent_id')]
    for container in (asset.get('labels', {}), asset.get('topology', {})):
        candidates += [container.get(k) for k in ('cluster_id', 'cluster_uid')]
    return any(str(v) in references for v in candidates if v is not None)


def make_node(asset, rows, now):
    rows = sorted(rows, key=lambda r:(r['end'], str(r['id'])))
    latest = rows[-1] if rows else None
    base = {'id': str(asset['id']), 'name': asset.get('name', ''), 'roles': roles(asset),
            'asset_ids': [str(asset['id'])], 'metrics': [], 'shared_load': len(roles(asset)) > 1,
            'missing_context': ['historical_roles', 'historical_cluster_membership', 'historical_cpu_cores'],
            'capacity_source': 'current Asset labels/topology; not historical configuration evidence'}
    if latest:
        ctx = node_context(latest)
        comparable = [r for r in rows if node_context(r) == ctx]
        missing = base['missing_context'] + [k for k,v in ctx.items() if v is None or v == '']
        linux = latest.get('payload', {}).get('host_semantics') == LINUX_MEMORY
        base.update({'context': ctx, 'missing_context': missing, 'window_start': latest['start'].isoformat(), 'window_end': latest['end'].isoformat(),
                     'frozen_diagnostics': latest.get('evaluation', {}).get('diagnostics', {}) if latest.get('evaluation', {}).get('plugin') == HOST_PLUGIN else {},
                     'diagnostic_note': '仅复用已冻结2.0诊断；VALID和旧capacity NORMAL均不表示健康正常',
                     'memory_semantics': 'LINUX_MEMAVAILABLE' if linux else 'SOURCE_REPORTED_NOT_LINUX_MEMAVAILABLE'})
        specs = [('host', 'cpu_busy_ratio', 'CPU忙碌比例', 'ratio'),
                 ('host', 'memory_available_bytes', 'Linux MemAvailable' if linux else '来源报告可用内存（非Linux MemAvailable）', 'bytes'),
                 ('host', 'memory_total_bytes', '内存总量', 'bytes')]
        for component in latest.get('payload', {}).get('metrics', {}):
            if component.startswith('disk:'):
                specs += [(component, k, component+' · '+label, unit) for k,label,unit in [('io_busy_ratio','IO忙碌比例','ratio'),('read_bytes_per_second','读取吞吐','bytes/s'),('write_bytes_per_second','写入吞吐','bytes/s')]]
        for component, key, label, unit in specs:
            base['metrics'].append(describe(component+'.'+key, label, unit, [(r, point(r,component,key)) for r in comparable], latest, now,
                                             current_allowed=linux if key=='memory_available_bytes' else True, missing_context=missing,
                                             observation_time=lambda r: point_time(r,component,key), latest_observed=reported_point(latest,component,key)))
        present = sum(m['latest_observed'] is not None for m in base['metrics'])
        current = sum(m['current'] is not None for m in base['metrics'])
        base['freshness'] = 'MIXED' if 0 < current < present else 'FRESH' if current else 'STALE'
    else:
        base['metrics'] = [describe(key,label,unit,[],{'end':now},now,current_allowed=False,missing_context=base['missing_context']) for key,label,unit in [('host.cpu_busy_ratio','CPU忙碌比例','ratio'),('host.memory_available_bytes','Linux MemAvailable（语义未知）','bytes'),('host.memory_total_bytes','内存总量','bytes')]]
        base.update({'freshness': 'MISSING', 'context': {}, 'memory_semantics': 'UNKNOWN', 'frozen_diagnostics': {}, 'diagnostic_note': '没有硬件快照；基础指标不依赖LLM绑定'})
    cores = next((number(c.get('cpu_cores')) for c in (asset.get('labels',{}), asset.get('topology',{})) if number(c.get('cpu_cores')) is not None), None)
    base['cpu_cores'] = cores if cores and cores > 0 else None
    base['_rows'] = rows
    base['_latest'] = latest
    return base


def aggregate(nodes, now):
    count = len(nodes)
    current_rows = [n['_latest'] for n in nodes]
    complete = count > 0 and all(current_rows) and len({(r['start'],r['end']) for r in current_rows}) == 1
    cores = [n['cpu_cores'] for n in nodes]
    cpus = [point(r,'host','cpu_busy_ratio') if r else None for r in current_rows]
    current_cpus = [current_point(r,'host','cpu_busy_ratio',now) for r in current_rows]
    mems = [(point(r,'host','memory_total_bytes'),point(r,'host','memory_available_bytes')) if r and r.get('payload',{}).get('host_semantics') == LINUX_MEMORY else (None,None) for r in current_rows]
    current_mems = [(current_point(r,'host','memory_total_bytes',now),current_point(r,'host','memory_available_bytes',now)) if r and r.get('payload',{}).get('host_semantics') == LINUX_MEMORY else (None,None) for r in current_rows]
    cpu_known = complete and all(c and c>0 for c in cores) and all(v is not None for v in cpus)
    memory_known = complete and all(t and a is not None and 0<=a<=t for t,a in mems)
    cpu_ok = cpu_known and all(v is not None for v in current_cpus)
    memory_ok = memory_known and all(t and a is not None and 0<=a<=t for t,a in current_mems)
    cpu_times = sorted({point_time(r,'host','cpu_busy_ratio') for r in current_rows if r and point_time(r,'host','cpu_busy_ratio')})
    memory_times = sorted({point_time(r,'host',key) for r in current_rows if r for key in ('memory_total_bytes','memory_available_bytes') if point_time(r,'host',key)})
    def metric(key,label,value,raw,covered,times):
        return {'key':key,'label':label,'unit':'ratio','current':value,'latest_observed':raw,'observed_at':times[0].isoformat() if times else None,
                'collected_at':None,'value_kind':'POINT_AGGREGATE','participating_collected_at':[at.isoformat() for at in times],
                'window_start':current_rows[0]['start'].isoformat() if complete else None,'window_end':current_rows[0]['end'].isoformat() if complete else None,
                'state':'CURRENT' if value is not None else 'UNKNOWN','history':{'n':0,'median':None,'min':None,'max':None,'start':None,'end':None,'time_basis':'POINT_AGGREGATE','state':'INSUFFICIENT_HISTORY'},
                'difference':None,'difference_scope':'DESCRIPTIVE_KNOWN_CONTEXT_ONLY','missing_context':['historical_node_membership','historical_cpu_cores'],
                'coverage':{'covered':covered,'total':count},'high_observation':None,'low_observation':None}
    raw_cpu = sum(v*c for v,c in zip(cpus,cores))/sum(cores) if cpu_known else None
    raw_used = sum(t-a for t,a in mems)/sum(t for t,a in mems) if memory_known else None
    raw_available = sum(a for t,a in mems)/sum(t for t,a in mems) if memory_known else None
    cpu_covered = sum(v is not None and c is not None for v,c in zip(current_cpus,cores))
    memory_covered = sum(t is not None and a is not None for t,a in current_mems)
    metrics = [metric('cluster.cpu_busy_ratio','CPU容量加权',raw_cpu if cpu_ok else None,raw_cpu,cpu_covered,cpu_times),
               metric('cluster.memory_used_ratio','Linux内存已用比例（容量加权）',raw_used if memory_ok else None,raw_used,memory_covered,memory_times),
               metric('cluster.memory_available_ratio','Linux可用内存比例（容量加权）',raw_available if memory_ok else None,raw_available,memory_covered,memory_times)]
    # Historic aggregation uses only aligned observations of this explicit current
    # node cohort. Never infer historic role/membership or cores from mutable labels.
    aligned = defaultdict(dict)
    for node in nodes:
        latest = node['_latest']
        if not latest: continue
        for row in node['_rows']:
            if now-timedelta(days=HISTORY_DAYS) <= row['end'] <= now and node_context(row)==node_context(latest):
                aligned[(row['start'],row['end'])][node['id']]=row
    history_rows=[]
    for (start,end), members in aligned.items():
        if len(members)!=count: continue
        memory=[(point(r,'host','memory_total_bytes'),point(r,'host','memory_available_bytes')) for r in members.values()]
        if not all(r.get('payload',{}).get('host_semantics')==LINUX_MEMORY for r in members.values()):continue
        if not all(t and a is not None and 0<=a<=t for t,a in memory):continue
        total=sum(t for t,a in memory)
        point_times=sorted({point_time(r,'host',key) for r in members.values() for key in ('memory_total_bytes','memory_available_bytes') if point_time(r,'host',key)})
        history_rows.append({'point_time':point_times[0] if point_times else None,'id':end.isoformat(),'start':start,'end':end,'available':sum(a for t,a in memory)/total,'used':sum(t-a for t,a in memory)/total})
    if complete:
        marker={'id':'latest','start':current_rows[0]['start'],'end':current_rows[0]['end'],'point_time':memory_times[0] if len(memory_times) else None}
        for index,key in [(1,'used'),(2,'available')]:
            observations=[(r,r[key]) for r in history_rows if r['end']<marker['end']]
            observations.append((marker,metrics[index]['current']))
            stats=describe(metrics[index]['key'],metrics[index]['label'],'ratio',observations,marker,now,current_allowed=memory_ok,missing_context=['historical_node_membership','historical_roles'],observation_time=lambda r:r.get('point_time'),value_kind='POINT_AGGREGATE')
            for field in ('history','difference','high_observation','low_observation'):metrics[index][field]=stats[field]
    return {'node_ids':[n['id'] for n in nodes], 'node_count':count,'metrics':metrics,
            'window_aligned':bool(complete),'note':'当前唯一节点、窗口对齐且新鲜才汇总；历史统计描述当前节点集合的已知条件观测，历史归属/角色未冻结，CPU历史容量未知。IO百分比/请求p95不汇总。'}


def make_llm(rows, now, assets=()):
    latest = max(rows,key=lambda r:(r['end'],str(r['id'])))
    ctx = {k: latest.get(k) for k in ('source','engine_id','engine_type','model_name')}
    missing = ['model_version','quantization','tensor_parallel_size','pipeline_parallel_size']
    matched = [r for r in rows if all(r.get(k)==v for k,v in ctx.items())]
    specs=[('ttft','p95_ms','TTFT窗口p95','ms'),('tpot','p95_ms','TPOT窗口p95','ms/token'),('e2e','p95_ms','E2E窗口p95','ms'),
           ('traffic','qps','QPS','requests/s'),('throughput','generation_tps','生成吞吐','tokens/s'),('throughput','prompt_tps','输入吞吐','tokens/s'),('requests','waiting','等待队列','requests'),('requests','running','运行请求','requests')]
    end=window_time(latest)
    window_fresh=end is not None and 0 <= (now-end).total_seconds() <= 180

    asset=next((a for a in assets if str(a['id'])==str(latest.get('asset_id'))), {})
    current_configuration={k:asset.get('labels',{}).get(k) for k in ('engine_version','model_version','quantization','tensor_parallel_size','pipeline_parallel_size') if asset.get('labels',{}).get(k) is not None}
    return {'current_asset_configuration':current_configuration,'id':context_key([ctx[k] for k in ('engine_id','engine_type','model_name')]),'name':' · '.join(str(ctx[k]) for k in ('engine_id','engine_type','model_name')),
            'context':ctx,'missing_context':missing,'value_kind':'WINDOW_STATISTIC',
            'window_start':timestamp(latest.get('start')).isoformat() if timestamp(latest.get('start')) else None,
            'window_end':timestamp(latest.get('end')).isoformat() if timestamp(latest.get('end')) else None,
            'freshness':'CURRENT_WINDOW_STATISTIC' if window_fresh else 'STALE_WINDOW_STATISTIC' if end else 'UNKNOWN_WINDOW',
            'metrics':[describe(f'{group}.{key}',label,unit,[(r,number(r.get('metrics',{}).get(group,{}).get(key))) for r in matched],latest,now,value_kind='WINDOW_STATISTIC',missing_context=missing) for group,key,label,unit in specs],
            'note':'仅匹配冻结的引擎/模型/来源；未记录版本、量化及并行配置。窗口p95的历史中位数/观察范围不是总体请求p95。'}


def build_profile(assets, hardware_rows, inference_rows, *, now, resource_type='HOST', portrait_mode=False, detail_kind=None, detail_id=None):
    """Accept plain records for offline validation; never mutate source observations."""
    host_assets = [a for a in assets if a['asset_type']=='HOST']
    cluster_assets = [a for a in assets if a['asset_type']=='CLUSTER']
    by_asset=defaultdict(list)
    for row in hardware_rows:
        by_asset[str(row['asset_id'])].append(row)
    # Stable identity is scoped to environment. Duplicate assets preserve union roles.
    unique={}
    for asset in host_assets:
        node=make_node(asset,by_asset[str(asset['id'])],now)
        identity=(node['_latest'] or {}).get('payload',{}).get('host_id') or asset.get('labels',{}).get('host_id') or asset.get('external_key')
        node['stable_identity'] = str(identity) if identity else 'UNKNOWN:'+str(asset['id'])
        key=(str(asset['environment_id']),node['stable_identity'])
        if key in unique:
            other=unique[key]
            chosen=max([node,other],key=lambda n:n['_latest']['end'] if n['_latest'] else now-timedelta(days=100000))
            merged_roles=sorted(set(node['roles']+other['roles']))
            chosen['roles']=merged_roles;chosen['shared_load']=len(merged_roles)>1
            chosen['asset_ids']=list(dict.fromkeys(node['asset_ids']+other['asset_ids']))
            if node['cpu_cores'] != other['cpu_cores']: chosen['cpu_cores']=None
            unique[key]=chosen
        else: unique[key]=node
    from .control_plane_risk import group_id, project_risk, summarize, GROUPS
    nodes=list(unique.values())
    for node in nodes:
        node['control_plane_group'] = group_id(node)
        node['risk'] = project_risk(node, now)
    clusters=[]
    for cluster in cluster_assets:
        members=[n for n in nodes if any(str(a['id']) in n['asset_ids'] and str(a['environment_id']) == str(cluster['environment_id']) and belongs(a,cluster) for a in host_assets)]
        deployment=cluster.get('labels',{}).get('control_plane_deployment','UNKNOWN')
        if deployment not in {'MIXED','DEDICATED'}:deployment='UNKNOWN'
        groups=[{'role':role, **aggregate([n for n in members if n['control_plane_group'] == role], now), 'risk':summarize([n for n in members if n['control_plane_group'] == role])} for role in (*GROUPS, 'UNKNOWN', 'OTHER')]
        classified=[n for n in members if n['control_plane_group'] in GROUPS]
        clusters.append({'id':str(cluster['id']),'name':cluster.get('name',''),'control_plane_deployment':deployment,'groups':groups,'classified':{**aggregate(classified,now),'risk':summarize(classified)},'total':aggregate(members,now),'shared_nodes':[n['id'] for n in members if n['shared_load']]})
    llm_groups=defaultdict(list)
    for row in inference_rows:llm_groups[(row['engine_id'],row['engine_type'],row['model_name'])].append(row)
    for node in nodes:node.pop('_rows');node.pop('_latest')
    result = {'resource_type':resource_type,'generated_at':now.isoformat(),'history_days':HISTORY_DAYS,'llm':[make_llm(r,now,assets) for r in llm_groups.values()],
            'nodes':nodes,'clusters':clusters,'note':'描述实际观测：历史范围不是置信区间、健康结论或容量预测；高低值只是资源观测时刻。缺项逐指标显示。'}

    if portrait_mode:
        from .portrait_projection import enrich_portraits
        enrich_portraits(result, assets, hardware_rows, inference_rows, now=now, detail_kind=detail_kind, detail_id=detail_id)
    return result
