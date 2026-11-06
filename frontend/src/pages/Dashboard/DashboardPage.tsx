import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { apiClient, getApiError } from '../../api/http'
import { getInspectionRunResult } from '../../api/inspectionRunResult'
import { getResourceTypes } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'
import { InspectionTriggerButton } from '../../features/inspection-trigger/InspectionTriggerButton'
import { RunCounts, RunFactsWorkspace, PortraitSummaryLinks } from '../../features/run-overview/RunOverview'
export function DashboardPage({environmentId:providedEnvironmentId,onOpenInspection}:{environmentId?:string|null;onOpenInspection?:()=>void}) {
 const stored=useUiStore(s=>s.environmentId),environmentId=providedEnvironmentId??stored,[params,setParams]=useSearchParams()
 const resources=useQuery({queryKey:['overview-resources',environmentId],queryFn:()=>getResourceTypes(environmentId!),enabled:!!environmentId})
 const runs=useQuery({queryKey:['overview-runs',environmentId],queryFn:async()=>(await apiClient.get<{items:Array<{id:string;environment_id:string;status:string;finished_at:string|null;run_date:string}>}>('/inspection-runs',{params:{environment_id:environmentId,page_size:30}})).data.items,enabled:!!environmentId})
 const list=(runs.data??[]).filter(r=>r.environment_id===environmentId)
 const requested=params.get('run'),selected=requested?list.find(r=>r.id===requested):list[0]
 const runId=requested??selected?.id
 const result=useQuery({queryKey:['inspection-result',environmentId,runId],queryFn:()=>getInspectionRunResult(runId!,environmentId!),enabled:!!environmentId&&!!runId})
 const detail=result.data?.run.environment_id===environmentId&&result.data.run.id===runId?result.data:undefined
 if(!environmentId)return <section className="view"><h2>本轮巡检</h2><p>请选择顶部环境，查看本轮结果。</p></section>
 return <section className="view" aria-label="本轮巡检总览"><header className="run-summary-heading"><div><span className="eyebrow">INSPECTION OVERVIEW</span><h2>本轮结果，下一步有据可查</h2><p className="lede">先处理已确认异常，再补齐影响判断的数据缺口。</p></div><div className="run-summary-actions">{onOpenInspection?<button className="button button-primary" onClick={onOpenInspection}>立即巡检</button>:<InspectionTriggerButton environmentId={environmentId} resourceTypes={resources.data?.items??[]} resourceTypesLoaded={resources.isSuccess||resources.isError}/>}</div></header>
 <label className="run-selector">本轮巡检 <select aria-label="本轮巡检" value={runId??''} onChange={e=>{const next=new URLSearchParams(params);next.set('run',e.target.value);setParams(next)}}><option value="" disabled>选择巡检记录</option>{list.map(r=><option key={r.id} value={r.id}>{r.run_date} · {r.status} · {r.id}</option>)}{requested&&!list.some(r=>r.id===requested)?<option value={requested}>{requested}（通过链接定位）</option>:null}</select></label>
 {runs.isLoading?<p role="status">正在读取当前环境的巡检记录…</p>:runs.isError?<div role="alert"><p>{getApiError(runs.error)?.message??'巡检列表读取失败，无法确认最新一轮。'}</p>{getApiError(runs.error)?.trace_id?<p>追踪 ID：{getApiError(runs.error)?.trace_id}</p>:null}<button onClick={()=>void runs.refetch()}>重试</button></div>:!runId?<div className="panel"><h3>当前环境尚无巡检报告</h3><p>尚未产生本轮结果，不能据此认定资源健康。已有画像仍可查看。</p><Link to={`/performance-profiles?environment=${environmentId}`}>查看性能画像 →</Link></div>:null}
 {result.isLoading&&runId?<p role="status">正在读取本轮冻结结果…</p>:result.isError?<div role="alert">本轮报告读取失败。<button onClick={()=>void result.refetch()}>重新读取</button></div>:detail?<><p className="run-current-context">环境 {environmentId} · RUN {detail.run.id} · 执行状态 {({SUCCEEDED:'已完成',PARTIAL:'部分完成',FAILED:'执行失败',PENDING:'排队中',RUNNING:'执行中'} as Record<string,string>)[detail.run.status]??detail.run.status}<br/>开始 {detail.run.started_at??'未记录'} · 完成/事实截止 {detail.run.finished_at??'尚未完成'}</p><div className="run-summary-actions"><Link className="button button-secondary" to={`/inspection-runs/${detail.run.id}?environment=${environmentId}`}>查看本轮报告 →</Link><a className="button button-secondary" href="#run-overview-facts">查看本轮异常与缺口 ↓</a></div><RunCounts detail={detail}/><div id="run-overview-facts"><RunFactsWorkspace key={`${environmentId}:${detail.run.id}`} detail={detail} environmentId={environmentId}/></div><PortraitSummaryLinks detail={detail} environmentId={environmentId}/></>:null}
 </section>
}
