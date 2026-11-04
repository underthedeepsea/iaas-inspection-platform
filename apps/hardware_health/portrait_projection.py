"""Optional detail serialization only. No new statistics, evaluations or writes."""
from datetime import timedelta
from .performance_profile import (HISTORY_DAYS, context_key, timestamp, window_time, node_context,
    point, point_time, number, make_llm, describe, belongs)
SERIES_LIMIT = 1000
LLM_SPECS = [('ttft','p95_ms','TTFT窗口p95','ms'),('tpot','p95_ms','TPOT窗口p95','ms/token'),('e2e','p95_ms','E2E窗口p95','ms'),('traffic','qps','QPS','requests/s'),('throughput','generation_tps','生成吞吐','tokens/s'),('throughput','prompt_tps','输入吞吐','tokens/s'),('requests','waiting','等待队列','requests'),('requests','running','运行请求','requests')]

def attach_series(metric, rows, now, *, component=None, field=None):
    """Discrete original observations; unknown continuity never becomes a line."""
    ordered=sorted(rows,key=lambda r:(r['end'],str(r['id'])))
    latest=ordered[-1] if ordered else None
    entries=[]
    for row in ordered:
        if not (timestamp(row.get('end')) and now-timedelta(days=HISTORY_DAYS)<=row['end']<=now):continue
        if component is not None:
            at=point_time(row,component,field)
            value=point(row,component,field)
        else:
            at=window_time(row)
            group,key=metric['key'].split('.',1)
            value=number(row.get('metrics',{}).get(group,{}).get(key))
        # A future collected point is not a historical observation.
        if at and not (now-timedelta(days=HISTORY_DAYS)<=at<=now):continue
        entries.append({'snapshot_id':str(row['id']),'at':at.isoformat() if at else None,
            'collected_at':at.isoformat() if at and component is not None else None,
            'window_start':timestamp(row.get('start')).isoformat() if timestamp(row.get('start')) else None,
            'window_end':timestamp(row.get('end')).isoformat() if timestamp(row.get('end')) else None,
            'value':value if at else None,'unit':metric['unit'],'source':row.get('source'),
            'value_kind':metric['value_kind'],'is_current':row is latest and metric['current'] is not None,
            'quality':'RECORDED_VALID' if at and value is not None else 'UNAVAILABLE',
            'continuity':'UNKNOWN','reference_bounds':None})
    metric['series']=entries[-SERIES_LIMIT:]
    metric['series_truncated']=len(entries)>SERIES_LIMIT
    metric['series_note']='原始离散观测，不推断连续性；未记录逐点同钟点参考上下界，不能生成历史带或连续偏离片段。'


def enrich_portraits(result, assets, hardware, inference, *, now, detail_kind=None, detail_id=None):
    # Preserve legacy id and default API. Portrait mode exposes each frozen source
    # identity separately rather than merging equal engine triples across sources.
    by_asset={str(a['id']):a for a in assets}
    groups={}
    for row in inference:
        key=tuple(str(row.get(k) or '') for k in ('asset_id','source','engine_id','engine_type','model_name'))
        groups.setdefault(key,[]).append(row)
    llms=[];represented=set()
    for key,rows in groups.items():
        entity=make_llm(rows,now,assets);entity['portrait_id']=context_key(list(key));entity['asset_id']=key[0] or None
        represented.add(key[0]);llms.append(entity)
        if detail_kind=='llm' and detail_id==entity['portrait_id']:
            for metric in entity['metrics']:attach_series(metric,rows,now)
    for asset in assets:
        if asset['asset_type']!='LLM_INSTANCE' or str(asset['id']) in represented:continue
        aid=str(asset['id']);labels=asset.get('labels') or {}
        entity={'id':aid,'portrait_id':context_key([aid,'NO_SNAPSHOT']),'asset_id':aid,'name':asset.get('name') or aid,
            'context':{},'current_asset_configuration':labels,'freshness':'MISSING','missing_context':['source','model_version','quantization','tensor_parallel_size','pipeline_parallel_size'],
            'note':'真实已登记资产；未收到推理快照，当前资产标签不能证明历史引擎/模型配置。',
            'metrics':[describe(f'{g}.{k}',label,unit,[],{'end':now},now,current_allowed=False,value_kind='WINDOW_STATISTIC',missing_context=['snapshot']) for g,k,label,unit in LLM_SPECS]}
        if detail_kind=='llm' and detail_id==entity['portrait_id']:
            for metric in entity['metrics']:attach_series(metric,[],now)
        llms.append(entity)
    result['llm']=llms
    for node in result['nodes']:
        node['portrait_id']=node['id'];node['current_asset_configuration']={k:by_asset.get(node['id'],{}).get(k) for k in ('labels','topology','external_key')}
        if detail_kind=='node' and detail_id==node['id']:
            rows=sorted([r for r in hardware if str(r['asset_id'])==node['id']],key=lambda r:(r['end'],str(r['id'])))
            matched=[r for r in rows if node_context(r)==node_context(rows[-1])] if rows else []
            for metric in node['metrics']:
                component,field=metric['key'].rsplit('.',1);attach_series(metric,matched,now,component=component,field=field)
    for cluster in result['clusters']:
        cluster['portrait_id']=cluster['id']
        if detail_kind=='cluster' and detail_id==cluster['id']:
            # Current weights/membership do not prove a historical cohort. No fabricated series.
            for metric in cluster['total']['metrics']:
                metric.update(series=[],series_truncated=False,series_note='历史节点成员、角色或容量权重未完整冻结；本批不回推集群曲线。可查看关联节点原始观测。')
    for kind,entities in [('node',result['nodes']),('llm',llms),('cluster',result['clusters'])]:
        for entity in entities:
            entity['relationships']=[]
            if kind=='cluster':
                related=[('node',n) for n in result['nodes'] if n['id'] in entity['total']['node_ids']]
                related += [('llm',l) for l in llms if l.get('asset_id') in by_asset and belongs(by_asset[l['asset_id']],by_asset[entity['id']])]
            elif kind=='node':
                related=[('cluster',c) for c in result['clusters'] if entity['id'] in c['total']['node_ids']]
                related += [('llm',l) for l in llms if str(by_asset.get(l.get('asset_id'),{}).get('parent_id') or '') in entity.get('asset_ids',[entity['id']])]
            else:
                asset=by_asset.get(entity.get('asset_id'),{})
                related=[('node',n) for n in result['nodes'] if str(asset.get('parent_id') or '') in n.get('asset_ids',[n['id']])]
                related += [('cluster',c) for c in result['clusters'] if entity.get('asset_id') in by_asset and belongs(asset,by_asset[c['id']])]
            entity['relationships']=[{'kind':k,'id':e['portrait_id'],'name':e['name']} for k,e in related]
    result['detail_request']={'kind':detail_kind,'id':detail_id,'series_limit_per_metric':SERIES_LIMIT}
    result['reference_band']={'available':False,'reason':'未保留逐历史点同钟点参考边界与连续性；现有范围仅当前排除自身的14天同已知条件观察统计。'}
