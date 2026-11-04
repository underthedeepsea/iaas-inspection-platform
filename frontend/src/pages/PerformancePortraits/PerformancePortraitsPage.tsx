import { ControlPlaneRisk, controlGroupNames } from '../ResourceDetail/PerformanceProfile'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { getPortraits, saveControlPlaneDeployment, type PerformanceProfileData, type ProfileCluster } from '../../api/performanceProfile'
import { getApiError } from '../../api/http'
import { useUiStore } from '../../stores/uiStore'
import { MetricPortrait } from './MetricPortrait'
import { portraits, stage, stages, filterPortraits, portraitUrl, kindNames, display, difference, metricTime, missingReason, nodeAttributes, type Portrait } from './portraitModel'
import './portraits.css'

export function PerformancePortraitsPage() {
  const environmentId=useUiStore(s=>s.environmentId)
  const {kind,id}=useParams()
  const query=useQuery({queryKey:['portraits',environmentId,kind,id],queryFn:()=>getPortraits(environmentId!,kind&&id?{kind,id}:undefined),enabled:!!environmentId})
  if(!environmentId)return <section className="portraits-page"><h2>性能画像</h2><p>请先选择一个环境。</p></section>
  if(query.isLoading)return <section className="portraits-page" role="status"><h2>性能画像</h2><div className="portrait-loading">正在读取资源与真实观测…</div></section>
  if(query.isError||!query.data)return <section className="portraits-page" role="alert"><h2>性能画像暂不可用</h2><p>{getApiError(query.error)?.message??'未能读取所选环境，请稍后重试。'}</p><button onClick={()=>void query.refetch()}>重新读取</button></section>
  return <PortraitBrowser key={`${environmentId}:${kind}:${id}`} data={query.data} environmentId={environmentId} refresh={async()=>{await query.refetch()}} />
}
function Attributes({values}:{values:Record<string,unknown>}) {
  return <dl className="portrait-attributes">{Object.entries(values).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v==null||v===''?'未记录':typeof v==='object'?JSON.stringify(v):String(v)}</dd></div>)}</dl>
}
function Deployment({cluster,data,environmentId,refresh}:{cluster:ProfileCluster;data:PerformanceProfileData;environmentId:string;refresh:()=>Promise<void>}) {
  const [value,setValue]=useState(cluster.control_plane_deployment),[saving,setSaving]=useState(false),[message,setMessage]=useState('')
  async function save(){if(!data.deployment_edit.writable)return;setSaving(true);setMessage('');try{await saveControlPlaneDeployment(environmentId,cluster.id,value);await refresh();setMessage('部署方式已保存')}catch(error){setMessage(getApiError(error)?.message??'保存失败，部署方式未确认修改')}finally{setSaving(false)}}
  return <div className="portrait-deployment"><label>控制面部署属性 <select aria-label="控制面部署方式" value={value} disabled={!data.deployment_edit.writable||saving} onChange={e=>setValue(e.target.value)}><option value="UNKNOWN" disabled>未记录</option><option value="MIXED">混合部署</option><option value="DEDICATED">独立部署</option></select></label><button onClick={()=>void save()} disabled={!data.deployment_edit.writable||saving||value===cluster.control_plane_deployment}>保存部署方式</button><p role="status">{message||(!data.deployment_edit.writable?'当前环境只读或权限未知，无法保存。':'仅修改当前集群部署属性；不改变实际节点角色。')}</p></div>
}
export function PortraitBrowser({data,environmentId,refresh=async()=>{}}:{data:PerformanceProfileData;environmentId:string;refresh?:()=>Promise<void>}) {
  const {kind,id}=useParams(),[params,setParams]=useSearchParams()
  const query=params.toString(),listUrl=`/performance-profiles${query?'?'+query:''}`
  const rows=portraits(data),selected=rows.find(r=>r.kind===kind&&r.id===id)
  const type=params.get('type')??'all',phase=params.get('stage')??'all',search=params.get('q')??''
  function filter(key:string,value:string){const next=new URLSearchParams(params);if(value&&value!=='all')next.set(key,value);else next.delete(key);setParams(next,{replace:true})}
  const filtered=filterPortraits(rows,type,phase,search)
  return <section className="portraits-page" aria-label="性能画像">
    <nav className="portrait-breadcrumb" aria-label="面包屑"><Link to={listUrl}>性能画像</Link>{kind?<><span>/</span><span>{selected?.name??'对象详情'}</span></>:null}</nav>
    <header className="portrait-heading"><div><span className="portrait-kicker">资源观测 / {kind?kindNames[kind as keyof typeof kindNames]??'对象':'当前环境'}</span><h2>{kind?selected?.name??'未找到这个对象':'性能画像'}</h2><p>{kind?'从实际指标追踪资源变化，核对每个值的时间、来源与可比条件。':'先定位资源，再进入独立详情；正常、缺项与历史对象都保留在列表。'}</p></div>{!kind?<button onClick={()=>void refresh()}>刷新观测</button>:<Link className="portrait-back" to={listUrl}>← 返回资源列表</Link>}</header>
    {data.truncated?<p className="portrait-notice" role="status">查询达到数量上限，当前列表与历史不完整；集群汇总已按原规则标为未知。搜索仅覆盖本次返回对象。</p>:null}
    {kind?selected?<PortraitDetail row={selected} data={data} query={query} environmentId={environmentId} refresh={refresh}/>:<div className="portrait-empty"><h3>所选环境没有这个对象</h3><p>请检查环境、来源及稳定身份，或返回列表重新选择。对象名称相同不代表冻结身份相同。</p><Link to={listUrl}>返回资源列表</Link></div>:<>
      <div className="portrait-toolbar"><div className="portrait-type-tabs" aria-label="对象类型">{[['all','全部资源'],['cluster','集群'],['node','节点'],['llm','LLM服务']].map(([value,label])=><button aria-pressed={type===value} key={value} onClick={()=>filter('type',value)}>{label} <small>{value==='all'?rows.length:rows.filter(r=>r.kind===value).length}</small></button>)}</div><div className="portrait-filters"><label>搜索资源<input type="search" value={search} placeholder="名称、身份、集群、角色或来源" onChange={e=>filter('q',e.target.value)}/></label><label>数据阶段<select value={phase} onChange={e=>filter('stage',e.target.value)}>{Object.entries(stages).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label></div></div>
      <div className="portrait-list-meta"><span>{filtered.length} 个资源对象</span><span>摘要取自本次返回数据 · {data.generated_at}</span></div>
      {filtered.length?<div className="portrait-resource-list"><div className="portrait-row-head"><span>资源与关系</span><span>当前观测</span><span>历史通常水平 / 观察范围</span><span>当前偏离</span><span>时间与可用性</span></div>{filtered.map(row=><ResourceRow key={row.kind+row.id} row={row} query={query} generatedAt={data.generated_at}/>)}</div>:<div className="portrait-empty"><h3>{rows.length?'没有匹配的资源':'当前环境尚无已登记的画像资源'}</h3><p>{rows.length?'调整名称、类型或数据阶段筛选。所有已返回对象都可在全部资源中查看。':'核对环境和资产来源；不会将缺测当作正常。'}</p></div>}
      <p className="portrait-footnote">历史为过去14天内同已知条件的实际样本，n与覆盖逐项显示；没有固定“成熟14天”门槛。范围是描述统计，不是健康结论。</p>
    </>}
  </section>
}
function ResourceRow({row,query,generatedAt}:{row:Portrait;query:string;generatedAt:string}) {
  const metric=row.metrics[0],age=metric?.observed_at?(Date.parse(generatedAt)-Date.parse(metric.observed_at))/1000:null
  return <Link className="portrait-resource-row" to={portraitUrl(row,query)} aria-label={`查看${kindNames[row.kind]} ${row.name}`}>
    <div><span className="portrait-kind">{kindNames[row.kind]}</span><h3>{row.name}</h3><small>{row.identity}</small>{'context' in row.entity?<small>来源：{String(row.entity.context.source??'未记录')}</small>:null}<p>{row.roles.map(role=>role==='UNKNOWN'?'角色未配置':role).join(' / ')||'角色不适用'}{row.relationships.length?` · ${row.relationships.map(r=>r.name).join(' / ')}`:' · 归属关系未记录'}</p></div>
    <div data-label="当前观测"><strong>{metric?display(metric.current,metric.unit):'—'}</strong><small>{metric?.label??'暂无指标'}</small>{metric&&metric.current==null?<small>历史 {display(metric.latest_observed,metric.unit)}</small>:null}</div>
    <div data-label="历史通常水平 / 观察范围">{metric&&metric.history.n>=2?<><b>{display(metric.history.median,metric.unit)}</b><small>{display(metric.history.min,metric.unit)} — {display(metric.history.max,metric.unit)}</small></>:<b>历史不足</b>}<small>n={metric?.history.n??0} · 同已知条件</small></div>
    <div data-label="当前偏离">{metric?difference(metric):'无法比较'}</div><div data-label="时间与可用性"><span className={`portrait-stage portrait-stage-${stage(row)}`}>{stages[stage(row)]}</span><small>{metric?metricTime(metric):'未记录可靠时间'}</small><small>{age!=null&&age>=0?`${Math.floor(age)}秒前（参考本次查询）`:'时间未知'}</small>{metric?.current==null?<small>{metric?missingReason(metric):'没有观测输入'}</small>:null}</div>
  </Link>
}
function PortraitDetail({row,data,query,environmentId,refresh}:{row:Portrait;data:PerformanceProfileData;query:string;environmentId:string;refresh:()=>Promise<void>}) {
  const cluster=row.kind==='cluster'?row.entity as ProfileCluster:null
  return <>
    <section className="portrait-overview"><div><h3>身份与上下文</h3><Attributes values={{对象类型:kindNames[row.kind],对象标识:row.identity,画像标识:row.id,...(row.kind==='node'?nodeAttributes(row):{})}}/>{'context' in row.entity?<Attributes values={row.entity.context}/>:null}</div><div><h3>数据覆盖</h3><p>{row.metrics.filter(m=>m.current!=null).length}/{row.metrics.length} 项当前观测可用</p><p>{stages[stage(row)]} · 不作为健康判定</p><p>真实历史与缺项逐指标独立呈现，某项缺测不遮住其他项。</p>{row.kind==='node'||cluster?<p>控制面使用整台宿主机CPU、Linux内存与逐盘IO；不归因到组件进程。基础画像不依赖LLM绑定或组件QPS。</p>:<p>p95是原窗口统计；各窗口的p95不合成全局请求p95。</p>}</div></section>
    {'current_asset_configuration' in row.entity?<details className="portrait-configuration"><summary>当前资产配置（不是历史配置证明）</summary><Attributes values={row.entity.current_asset_configuration??{}}/></details>:null}
    {cluster?<><ControlPlaneRisk key={environmentId+cluster.id} cluster={cluster} nodes={data.nodes}/><Deployment cluster={cluster} data={data} environmentId={environmentId} refresh={refresh}/><div className="portrait-relationship-note"><h3>控制面关系与唯一节点</h3><p>总计 {cluster.total.node_count} 个唯一节点；多角色共享 {cluster.shared_nodes.length} 个；三类控制面主机互斥；未知与其他角色独立保留。</p><p>{cluster.total.note}</p>{cluster.groups.map(g=><p key={g.role}>{controlGroupNames[g.role]??g.role} · {g.node_count} 个节点 · {g.node_ids.join(' / ')}</p>)}</div></>:null}
    <div className="portrait-section-title"><h3>逐指标观测</h3><span>真实值与真实时间 · 描述差异，不重判健康</span></div>
    {row.kind==='node'&&!row.metrics.some(m=>m.key.startsWith('disk:'))?<p className="portrait-notice">未收到逐盘IO观测；仅影响磁盘指标，不阻塞CPU及内存。不会补造磁盘对象或数值。</p>:null}
    <div className="portrait-metric-grid">{row.metrics.map(metric=><MetricPortrait key={row.id+metric.key} metric={metric}/>)}</div>
    <aside className="portrait-reference-gap"><h3>历史参考能力</h3><p>已提供同已知条件的历史中位数与min/max范围。尚无逐点同钟点参考上下界及连续偏离投影，因此历史带和持续偏离片段暂不可用；不会用当前范围回填过去。</p></aside>
    <section className="portrait-related"><h3>关联资源</h3>{row.relationships.length?<ul>{row.relationships.map(relation=><li key={relation.kind+relation.id}><Link to={portraitUrl(relation,query)}>{kindNames[relation.kind]} · {relation.name} →</Link></li>)}</ul>:<p>没有已记录的直接归属关系；不按名称推断。当前资产关系不证明历史成员固定。</p>}</section>
  </>
}
