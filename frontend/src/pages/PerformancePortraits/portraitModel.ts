import type { PerformanceProfileData, PortraitKind, PortraitRelation, ProfileEntity, ProfileCluster, ProfileMetric, ProfileNode } from '../../api/performanceProfile'
export type Portrait = { kind: PortraitKind; id: string; name: string; metrics: ProfileMetric[]; relationships: PortraitRelation[]; identity: string; roles: string[]; entity: ProfileEntity | ProfileCluster }
export const kindNames = {cluster:'集群',node:'节点',llm:'LLM服务'}
export function portraits(data: PerformanceProfileData): Portrait[] {
  return [
    ...data.clusters.map(entity => ({kind:'cluster' as const,id:entity.portrait_id ?? entity.id,name:entity.name,metrics:entity.total.metrics,relationships:entity.relationships ?? [],identity:entity.id,roles:entity.roles ?? [],entity})),
    ...data.nodes.map(entity => ({kind:'node' as const,id:entity.portrait_id ?? entity.id,name:entity.name,metrics:entity.metrics,relationships:entity.relationships ?? [],identity:entity.stable_identity,roles:entity.roles,entity})),
    ...data.llm.map(entity => ({kind:'llm' as const,id:entity.portrait_id ?? entity.id,name:entity.name,metrics:entity.metrics,relationships:entity.relationships ?? [],identity:entity.asset_id ?? entity.id,roles:[],entity})),
  ]
}
export function stage(row: Portrait) {
  const current=row.metrics.filter(m=>m.current!=null).length
  if (current===row.metrics.length && current>0) return 'fresh'
  if (current>0) return 'mixed'
  return row.metrics.some(m=>m.latest_observed!=null) ? 'history' : 'missing'
}
export const stages:Record<string,string> = {all:'全部数据阶段',fresh:'当前观测可用',mixed:'部分指标可用',history:'仅历史或语义未核实',missing:'尚无有效观测'}
export function filterPortraits(rows:Portrait[], type:string, phase:string, search:string) {
  const q=search.trim().toLocaleLowerCase()
  return rows.filter(row=>(type==='all'||row.kind===type)&&(phase==='all'||stage(row)===phase)&&(!q||JSON.stringify([row.name,row.identity,row.roles,row.relationships,'context' in row.entity?row.entity.context:{}]).toLocaleLowerCase().includes(q)))
}
export function portraitUrl(row:Pick<Portrait,'kind'|'id'>, query:string) {return `/performance-profiles/${row.kind}/${encodeURIComponent(row.id)}${query?'?'+query:''}`}
export function display(value:number|null|undefined,unit:string) {
  if(value==null||!Number.isFinite(value))return '—'
  if(unit==='ratio')return `${Number((value*100).toFixed(2))}%`
  if(unit==='bytes')return `${Number((value/1024**3).toFixed(3))} GiB`
  if(unit==='bytes/s')return `${Number((value/1024**2).toFixed(3))} MiB/s`
  return `${Number(value.toFixed(3))} ${unit}`
}
export function difference(metric:ProfileMetric) {
  if(metric.difference==null)return '历史不足或当前不可比'
  const delta=metric.unit==='ratio'?`${Number((metric.difference*100).toFixed(2))} 个百分点`:display(metric.difference,metric.unit)
  const base=metric.history.median
  const ratio=base!=null&&base!==0?metric.difference/base*100:null
  return `${metric.difference>0?'+':''}${delta}${ratio!=null&&Number.isFinite(ratio)?` · 相对${ratio>0?'+':''}${Number(ratio.toFixed(2))}%`:' · 零基线或无基线，相对变化不可算'}`
}
export function metricTime(metric:ProfileMetric) {
  return metric.value_kind==='WINDOW_STATISTIC'?`统计窗口 ${metric.window_start??'未记录'} → ${metric.window_end??'未记录'}`:metric.value_kind==='POINT_AGGREGATE'?`参与点 ${metric.participating_collected_at?.join(' / ')||'时间未记录'}`:`采集 ${metric.collected_at??metric.observed_at??'未记录可靠时间'}`
}
export function missingReason(metric:ProfileMetric) {
  if(metric.current!=null)return '本项当前观测可用，不代表健康结论'
  if(metric.latest_observed==null)return '未收到本项有效观测；检查来源和对应指标'
  return '仅保留历史观测：采集已过期、时间无效或来源语义未核实；核对时间及来源后补齐有效输入'
}
export function nodeAttributes(row:Portrait) {const n=row.entity as ProfileNode;return {资产类型:n.asset_type,稳定身份:n.stable_identity,CPU核数:n.cpu_cores,角色:n.roles?.join(' / '),内存语义:n.memory_semantics}}
