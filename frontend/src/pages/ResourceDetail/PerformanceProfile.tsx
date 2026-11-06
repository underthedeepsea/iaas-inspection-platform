import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getApiError } from '../../api/http'
import { getPerformanceProfile, saveControlPlaneDeployment, type ProfileMetric, type ProfileCluster, type ProfileNode } from '../../api/performanceProfile'

function display(value: number | null | undefined, unit: string) {
  if (value == null) return '—'
  if (unit === 'ratio') return `${(value * 100).toFixed(1)}%`
  if (unit === 'bytes') return `${(value / 1024 ** 3).toFixed(2)} GiB`
  return `${Number(value.toFixed(2))} ${unit}`
}
const conditionNames: Record<string, string> = { model_version: '模型版本', quantization: '量化', tensor_parallel_size: '张量并行', pipeline_parallel_size: '流水线并行', historical_roles: '历史角色', historical_cluster_membership: '历史集群归属', historical_node_membership: '历史节点归属', historical_cpu_cores: '历史CPU核数', config_id: '配置标识', host_semantics: 'Linux内存语义', memory_total_bytes: '内存容量', source: '来源', host_id: '节点身份', identity: '规格身份' }
const missing = (items: string[]) => items.map(v => conditionNames[v] ?? v).join('、') || '无已识别缺项'

export function ProfileMetrics({ metrics }: { metrics: ProfileMetric[] }) {
  return <div style={{ overflowX: 'auto' }}><table className="data-table"><thead><tr><th>指标</th><th>当前值 / 最近观测</th><th>历史样本中位数 / 观察范围</th><th>数值差</th><th>样本与覆盖</th></tr></thead><tbody>{metrics.map(metric => <tr key={metric.key}>
    <td>{metric.label}</td><td>{display(metric.current, metric.unit)}{metric.current == null && metric.latest_observed != null ? <small> 历史/过期或语义未核实：{display(metric.latest_observed, metric.unit)}</small> : null}<small style={{ display: 'block' }}>{metric.value_kind === 'WINDOW_STATISTIC' ? `${metric.current == null ? '历史/未知窗口统计' : '当前窗口统计'} · WINDOW_STATISTIC · 统计窗口：${metric.window_start ?? '未记录'} 至 ${metric.window_end ?? '未记录'}` : metric.value_kind === 'POINT_AGGREGATE' ? `参与点采集时间：${metric.participating_collected_at?.join('、') || '未记录可靠时间'}` : `指标采集时间：${metric.observed_at ?? '未记录可靠时间'}`}</small></td>
    <td>{metric.history.n >= 2 ? <>{display(metric.history.median, metric.unit)}<small style={{ display: 'block' }}>{display(metric.history.min, metric.unit)} 至 {display(metric.history.max, metric.unit)}（已知条件）</small></> : '历史不足，范围未知'}</td>
    <td>{display(metric.difference, metric.unit)}<small style={{ display: 'block' }}>仅描述已知条件</small></td>
    <td>n={metric.history.n}{metric.coverage ? ` · ${metric.coverage.covered}/${metric.coverage.total}节点` : ''}<small style={{ display: 'block' }}>{metric.value_kind === 'WINDOW_STATISTIC' ? '窗口结束时间' : metric.value_kind === 'POINT_AGGREGATE' ? '参与点最早采集时间' : '真实采集时间'}：{metric.history.start ?? '—'} 至 {metric.history.end ?? '—'}</small>{metric.current == null ? <small>当前缺测、过期或不可汇总</small> : null}</td>
  </tr>)}</tbody></table></div>
}

export function PerformanceProfile({ environmentId, resourceCode }: { environmentId: string; resourceCode: string }) {
  const [layer, setLayer] = useState(resourceCode === 'LLM_RUNTIME' ? 'llm' : resourceCode === 'HOST' ? 'nodes' : 'clusters')
  const [clusterId, setClusterId] = useState('')
  const [deployment, setDeployment] = useState<{ environmentId: string; clusterId: string; value: string } | null>(null)
  const [saveState, setSaveState] = useState<{ environmentId: string; clusterId: string; message: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const query = useQuery({ queryKey: ['performance-profile', environmentId, resourceCode], queryFn: () => getPerformanceProfile(environmentId, resourceCode) })
  const data = query.data
  const clusters = Array.isArray(data?.clusters) ? data.clusters : []
  const selected = clusters.find(c => c.id === clusterId) ?? clusters[0]
  const selectedDeployment = deployment?.environmentId === environmentId && deployment.clusterId === selected?.id ? deployment.value : ''
  const selectedSaveState = saveState?.environmentId === environmentId && saveState.clusterId === selected?.id ? saveState.message : ''
  const selectedNodes = (data?.nodes ?? []).filter(n => resourceCode !== 'K8S_CLUSTER' || n.scope_cluster_id === selected?.id)
  const llm = Array.isArray(data?.llm) ? data.llm : []
  const entities = layer === 'llm' ? resourceCode === 'K8S_CLUSTER' ? llm.filter(entity => selected && entity.scope_cluster_ids?.includes(selected.id)) : llm : (Array.isArray(data?.nodes) ? data.nodes : [])
  function selectCluster(id: string) {
    if (id === selected?.id) return
    setClusterId(id); setDeployment(null); setSaveState(null)
  }
  async function save() {
    if (!selected || !selectedDeployment || saving || !data?.deployment_edit?.writable) return
    const target = { environmentId, clusterId: selected.id }
    setSaving(true); setSaveState(null)
    try { await saveControlPlaneDeployment(target.environmentId, target.clusterId, selectedDeployment); await query.refetch(); setSaveState({ ...target, message: '部署方式已保存' }) }
    catch (error) { setSaveState({ ...target, message: getApiError(error)?.message ?? '无法保存部署方式，请检查当前环境权限' }) }
    finally { setSaving(false) }
  }
  return <section className="panel panel-large" aria-labelledby="performance-profile-title"><div className="section-heading"><div><span className="eyebrow">PERFORMANCE OBSERVATIONS</span><h3 id="performance-profile-title">{resourceCode === 'CONTROL_PLANE' ? '控制面主机风险' : '性能画像 · 实际观测'}</h3></div><span className="legend">14天 · 描述统计</span></div>
    <div className="heading-actions" role="group" aria-label="画像层级">{[['llm','LLM服务'],['nodes','节点'],['clusters','集群']].map(([key,label]) => <button className={`button ${layer===key?'button-primary':'button-secondary'}`} aria-pressed={layer===key} key={key} onClick={() => setLayer(key)}>{label}</button>)}</div>
    <p className="data-source-note">历史范围不是置信区间、健康结论或容量预测；数值差只描述已知条件。窗口p95历史统计不代表总体请求p95。高低值是资源观测时刻。</p>
    {query.isLoading ? <p role="status">正在读取性能画像</p> : query.isError ? <p role="status">性能画像读取失败，请稍后重试。</p> : <>
      {data?.truncated ? <p role="status">查询达到数量上限，覆盖不完整；下方汇总仅描述返回节点，不代表全集群。</p> : null}
      {resourceCode === 'K8S_CLUSTER' && layer === 'llm' && selected ? <label>现有集群 <select aria-label="现有集群" value={selected.id} onChange={event => selectCluster(event.target.value)}>{clusters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label> : null}
      {layer === 'clusters' ? !selected ? <p role="status">{data?.truncated ? '查询达到数量上限，无法确认集群是否存在。' : '当前环境没有集群资产，部署方式未配置。'}</p> : <>
        <label>现有集群 <select aria-label="现有集群" value={selected.id} onChange={event => selectCluster(event.target.value)}>{clusters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
        {resourceCode === 'K8S_CLUSTER' ? <section aria-label="集群资源类型与角色"><p>资源类型：{selected.asset_type ?? '未记录'} · 平台：{selected.platform || '未记录'} · 集群角色：{selected.roles?.join(' / ') || '未记录'}</p><p>当前资产属性与成员关系，不作为历史配置证明。</p><h4>集群节点</h4>{selectedNodes.filter(n => selected.total.node_ids.includes(n.id)).map(n => <p key={n.id}>{n.name} · 类型：{n.asset_type ?? '未记录'} · 角色：{n.roles.join(' / ') || '未记录'}</p>)}<Link to={`/performance-profiles/cluster/${encodeURIComponent(selected.portrait_id ?? selected.id)}?environment=${encodeURIComponent(environmentId)}&resource_type=K8S_CLUSTER&cluster_id=${encodeURIComponent(selected.id)}`}>查看集群完整画像 →</Link></section> : null}
        <div style={{ margin: '16px 0' }}><label>控制面部署方式 <select aria-label="控制面部署方式" disabled={!data?.deployment_edit?.writable || saving} value={selectedDeployment || selected.control_plane_deployment} onChange={event => setDeployment({ environmentId, clusterId: selected.id, value: event.target.value })}><option value="UNKNOWN" disabled>未记录</option><option value="MIXED">混合部署</option><option value="DEDICATED">独立部署</option></select></label> <button className="button button-secondary" disabled={!data?.deployment_edit?.writable || !selectedDeployment || saving} onClick={save}>保存</button><p role="status">{selectedSaveState || (data?.deployment_edit?.writable ? '仅修改所选集群部署方式' : '当前环境只读或权限未知，无法保存部署方式。')}</p></div>
        <ControlPlaneRisk key={environmentId+selected.id} cluster={selected} nodes={selectedNodes} />
        <details><summary>集群总计实际观测（原始成员口径）</summary><ProfileMetrics metrics={selected.total.metrics} /><p>{selected.total.note}</p></details>
        <details><summary>集群节点与逐设备IO</summary>{selectedNodes.filter(n => selected.total.node_ids.includes(n.id)).map(n => <div key={n.id}><h4>{n.name} · {n.roles.join(' / ')} {n.shared_load ? '共享负载' : ''}</h4><ProfileMetrics metrics={n.metrics.filter(m => m.key.startsWith('disk:'))} /></div>)}</details>
      </> : entities.length === 0 ? <p role="status">{layer === 'llm' ? resourceCode === 'K8S_CLUSTER' ? '当前集群没有可确认归属的 LLM 服务快照。' : '尚无LLM服务快照；其他层级仍可查看。' : '尚无节点资产或硬件快照；基础指标不依赖LLM绑定。'}</p> : entities.map(entity => <article className="evidence-item" key={`${'scope_cluster_id' in entity ? entity.scope_cluster_id : ''}:${entity.id}`}>
        <header><strong>{entity.name}</strong><span>{entity.freshness === 'CURRENT_WINDOW_STATISTIC' ? '当前窗口统计' : entity.freshness === 'STALE_WINDOW_STATISTIC' ? '历史窗口统计' : entity.freshness === 'UNKNOWN_WINDOW' ? '窗口时间未知' : entity.freshness === 'MIXED' ? '新鲜与历史指标并存 · 逐项查看' : entity.freshness === 'FRESH' ? '新鲜观测 · 逐项采集时间' : entity.freshness === 'MISSING' ? '未采集' : '历史/过期观测'}</span></header>
        {resourceCode === 'K8S_CLUSTER' && layer === 'llm' ? <p>资产：{entity.asset_name || '未记录名称'} · 标识：{entity.asset_id || '未记录'} · 所属集群：{selected?.name ?? '未记录'}（当前资产关系）</p> : null}
        {'roles' in entity && (entity as ProfileNode).scope_cluster_id ? <p>所属集群：{clusters.find(c => c.id === (entity as ProfileNode).scope_cluster_id)?.name ?? (entity as ProfileNode).scope_cluster_id}</p> : null}
        {'roles' in entity ? <p>组件承载节点负载 · {(entity as import('../../api/performanceProfile').ProfileNode).roles.join(' / ')} · {(entity as import('../../api/performanceProfile').ProfileNode).shared_load ? '共享负载' : '节点负载'}；不作进程归因或组件健康判断。</p> : null}
        <p className="data-source-note">已知条件：{JSON.stringify(entity.context)}<br />未记录比较条件：{missing(entity.missing_context)}</p>
        {entity.current_asset_configuration && Object.keys(entity.current_asset_configuration).length ? <p>当前资产配置：{JSON.stringify(entity.current_asset_configuration)}（未作为历史配置一致证据）</p> : null}
        {entity.note ? <p>{entity.note}</p> : null}<ProfileMetrics metrics={entity.metrics} />
        <details><summary>资源观测高低值时刻</summary>{entity.metrics.map(m => <p key={m.key}>{m.label}（{m.value_kind === 'WINDOW_STATISTIC' ? '窗口结束时间' : m.value_kind === 'POINT_AGGREGATE' ? '参与点最早采集时间' : '真实采集时间'}）：高值 {m.high_observation ? `${display(m.high_observation.value,m.unit)} · ${m.high_observation.at}` : '未采集'}；低值 {m.low_observation ? `${display(m.low_observation.value,m.unit)} · ${m.low_observation.at}` : '未采集'}</p>)}</details>
        {'frozen_diagnostics' in entity ? <details><summary>已冻结诊断</summary><p>{(entity as import('../../api/performanceProfile').ProfileNode).diagnostic_note}</p><pre>{JSON.stringify((entity as import('../../api/performanceProfile').ProfileNode).frozen_diagnostics,null,2)}</pre></details> : null}
      </article>)}
    </>}
  </section>
}

const riskNames: Record<string,string> = {CRITICAL:'严重',WARNING:'警告',UNKNOWN:'未知',NORMAL:'正常'}
export const controlGroupNames: Record<string,string> = {API_SERVER_ONLY:'纯APIServer',ETCD_ONLY:'纯ETCD',MIXED:'混合部署',UNKNOWN:'角色未知',OTHER:'其他角色'}
export function ControlPlaneRisk({cluster,nodes}:{cluster:ProfileCluster;nodes:ProfileNode[]}) {
  const [groupId,setGroupId]=useState('API_SERVER_ONLY'),[showNormal,setShowNormal]=useState(false)
  const groups=['API_SERVER_ONLY','ETCD_ONLY','MIXED'].map(role=>cluster.groups.find(g=>g.role===role)).filter(g=>!!g)
  const selected=groups.find(g=>g.role===groupId)??groups[0]
  const summary=cluster.classified?.risk,rank:Record<string,number>={CRITICAL:0,WARNING:1,UNKNOWN:2,NORMAL:3}
  const members=nodes.filter(n=>selected?.node_ids.includes(n.id)).sort((a,b)=>(rank[a.risk?.level??'UNKNOWN']-rank[b.risk?.level??'UNKNOWN'])||a.name.localeCompare(b.name))
  function evidence(node:ProfileNode){const items=node.risk?.triggers??[];return items.length?items.map(i=>`${i.key} ${display(i.current,i.unit)}`).join('；'):'未发现已确认触发项'}
  return <section className="control-risk" aria-label="控制面主机风险"><h3>控制面主机风险</h3>
    <div className="control-risk-summary">{[['风险主机 / 已分类',summary?`${summary.risk_hosts} / ${cluster.classified?.node_count??0}`:'—'],['严重',summary?.counts.CRITICAL??'—'],['警告',summary?.counts.WARNING??'—'],['无法判定',summary?.counts.UNKNOWN??'—'],['本次可判定覆盖',summary?`${summary.coverage.covered} / ${summary.coverage.total}`:'—']].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
    <p className="data-source-note">风险来自新鲜冻结v2逐主机诊断。未知不等于正常；异常伴缺项仍计风险，且不计完整判定覆盖。{summary?.truncated?'查询截断，计数仅覆盖本次返回主机。':''}</p>
    <div className="control-risk-groups">{groups.map(g=>{const priority=nodes.filter(n=>g.node_ids.includes(n.id)).sort((a,b)=>rank[a.risk?.level??'UNKNOWN']-rank[b.risk?.level??'UNKNOWN'])[0];return <button key={g.role} aria-pressed={selected?.role===g.role} onClick={()=>{setGroupId(g.role);setShowNormal(false)}}><h4>{controlGroupNames[g.role]}</h4><p>{g.node_count} 台成员</p><p>严重 {g.risk?.counts.CRITICAL??'—'} · 警告 {g.risk?.counts.WARNING??'—'} · 未知 {g.risk?.counts.UNKNOWN??'—'}</p><small>优先检查实例：{priority?.name??'无成员'}</small>{priority?<><p>{evidence(priority)}</p><small>{priority.metrics.filter(m=>['host.cpu_busy_ratio','host.memory_available_bytes'].includes(m.key)).map(m=>`${m.label} ${display(m.current,m.unit)}`).join(' · ')}</small><small>{priority.risk?.triggers.map(i=>`${i.rule_id} v${i.rule_version} · 确认有效点 ${i.confirmation_points??'未保存'}/${i.confirmation_required??'未保存'}`).join('；')||priority.risk?.missing[0]||'本项未触发'}</small></>:null}</button>})}</div>
    <p>角色未知 {cluster.groups.find(g=>g.role==='UNKNOWN')?.node_count??0} 台：未记录API_SERVER/ETCD角色；其他角色 {cluster.groups.find(g=>g.role==='OTHER')?.node_count??0} 台：没有控制面角色，保留于原集群总计。</p>
    <div className="section-heading"><h4>{selected?controlGroupNames[selected.role]:'已分类'}成员</h4><label><input type="checkbox" checked={showNormal} onChange={e=>setShowNormal(e.target.checked)}/> 查看正常成员</label></div>
    <div style={{overflowX:'auto'}}><table className="data-table"><thead><tr>{['等级','主机','触发指标','判定依据','样本时间','现有证据或缺项'].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{members.filter(n=>showNormal||n.risk?.level!=='NORMAL').map(n=><tr key={n.id}><td>{riskNames[n.risk?.level??'UNKNOWN']}{n.risk?.incomplete?' · 不完整':''}</td><td>{n.name}<small style={{display:'block'}}>{n.stable_identity}</small></td><td>{evidence(n)}</td><td>{n.risk?.triggers.map(i=><p key={i.key}>{i.rule_id} v{i.rule_version} · {i.reason}<br/>有效确认点 {i.confirmation_points??'未保存'}/{i.confirmation_required??'未保存'}<br/>{i.rule?JSON.stringify(i.rule):'冻结规则未保存'}</p>)??'无可信冻结依据'}</td><td>{n.risk?.sample_time??'未记录'}</td><td><details><summary>查看证据与缺项</summary>{n.risk?.missing.length?<ul>{n.risk.missing.map(m=><li key={m}>{m}</li>)}</ul>:<p>无已识别缺项</p>}<pre>{JSON.stringify(n.frozen_diagnostics,null,2)}</pre></details></td></tr>)}</tbody></table></div>
    {!members.length?<p>该组没有成员。</p>:null}
    <p className="data-source-note">计数口径：{nodes.some(node=>node.scope_cluster_id) ? '集群 + ' : ''}environment + stable identity 去重；API_SERVER与ETCD都有仅计混合，API_SERVER + WORKER仍计纯APIServer。严重→警告→未知→正常；同主机多个触发只计最高等级一次。完整覆盖分母为三组唯一主机，120秒是规则确认窗口；未保存可信开始时间，仅显示确认点数，不推定异常持续时间。原集群总计还保留未知与其他角色。</p>
    {summary?<details><summary>逐指标可判覆盖</summary>{Object.entries(summary.metric_coverage).map(([key,c])=><p key={key}>{key}：{c.covered}/{c.total}</p>)}</details>:null}
  </section>
}
