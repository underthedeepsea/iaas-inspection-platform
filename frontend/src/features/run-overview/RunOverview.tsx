import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import type { InspectionRunResult } from '../../api/inspectionRunResult'
import { getProductInfo } from '../../api/product'
import { DashboardAIBar } from '../dashboard-ai/DashboardAIBar'
import { InspectionFacts } from '../inspection-history/InspectionFacts'
import { CheckResultsTable } from '../inspection-history/CheckResultsTable'
import './runOverview.css'
export function RunCounts({detail}:{detail:InspectionRunResult}) {
 const s=detail.summary
 return <div className="run-count-grid"><article><span>执行对象覆盖</span><strong>{s.assets_covered} / {s.assets_total}</strong><small>本轮已产生检查结果的资源</small></article><article><span>已得出判定</span><strong>{s.pass_count+s.fail_count}</strong><small>异常 {s.fail_count} · 通过 {s.pass_count} 条检查</small></article><article><span>仍无法判断</span><strong>{s.unknown_count+s.error_count}</strong><small>证据缺项 {s.unknown_count} · 执行失败 {s.error_count}</small></article><article><span>未产生结果对象</span><strong>{Math.max(0,s.assets_total-s.assets_covered)}</strong><small>不与待判断检查条数混为分母</small></article></div>
}
export function BoundExplanation({detail,environmentId,onClose}:{detail:InspectionRunResult;environmentId:string;onClose:()=>void}) {
 const config=useQuery({queryKey:['product-info'],queryFn:getProductInfo,retry:false})
 const disabled=config.isLoading?'正在确认现有AI配置。':config.isError?'无法确认现有AI配置，智能解读暂未开放。':config.data&&['disabled','none','off'].includes(config.data.llm_provider?.toLowerCase())?'当前AI配置已关闭；本页不会开启配置。':undefined
 const completed=['SUCCEEDED','PARTIAL'].includes(detail.run.status)&&!!detail.run.finished_at
 return <aside className="bound-explanation" aria-label="本轮智能解读"><header><h3>智能解读本轮</h3><button className="button" onClick={onClose}>关闭解读并返回事实</button></header>{config.isError?<p>未能确认运行配置；请求失败将保留实际错误，事实仍可查看。</p>:null}<DashboardAIBar key={`${environmentId}:${detail.run.id}`} environmentId={environmentId} runId={detail.run.id} resultMode facts={detail.fact_report} showFacts={false} boundRun cutoff={detail.run.finished_at??detail.run.started_at} disabledReason={disabled??(!completed?'本轮尚未完成，智能解读未开放。':undefined)}/></aside>
}
export function RunFactsWorkspace({detail,environmentId,initialOpen=false}:{detail:InspectionRunResult;environmentId:string;initialOpen?:boolean}) {
 const [open,setOpen]=useState(initialOpen)
 const checks=detail.fact_report?.checks??[]
 const abnormal=checks.filter(row=>row.status==='FAIL'),gaps=checks.filter(row=>row.status==='UNKNOWN'||row.status==='ERROR')
 const makeReport=(rows:typeof checks)=>detail.fact_report?{...detail.fact_report,checks:rows,check_count:rows.length,status_counts:rows.reduce<Record<string,number>>((c,r)=>({...c,[r.status]:(c[r.status]??0)+1}),{}),omitted_count:0}:undefined
 return <div className="run-facts-section"><div className="run-facts-toolbar"><div><h3>本轮结果与待办</h3><p>RUN {detail.run.id} · 截止 {detail.run.finished_at??detail.run.started_at??'时间未记录'}</p></div><button className="button button-primary" onClick={()=>setOpen(true)} disabled={open}>智能解读本轮</button></div><div className={`run-facts-workspace${open?' is-open':''}`}><div className="run-facts-main"><section className="run-attention"><h3>已确认异常 · {detail.summary.fail_count}</h3>{abnormal.length&&detail.fact_report?<InspectionFacts report={makeReport(abnormal)!} environmentId={environmentId}/>:<p>本轮没有已确认异常记录；不能据此认定缺项正常。</p>}</section><section className="run-gaps"><h3>数据缺口与执行问题 · {detail.summary.unknown_count+detail.summary.error_count}</h3>{gaps.length&&detail.fact_report?<InspectionFacts report={makeReport(gaps)!} environmentId={environmentId}/>:<p>本轮没有待判断或失败的检查记录。</p>}</section>{checks.some(r=>r.status==='PASS'||r.status==='NOT_APPLICABLE')?<details><summary>查看本轮通过与不适用项</summary><InspectionFacts report={makeReport(checks.filter(r=>r.status==='PASS'||r.status==='NOT_APPLICABLE'))!} environmentId={environmentId}/></details>:null}<details className="run-raw-checks"><summary>全部检查、原规则与冻结证据</summary><CheckResultsTable results={detail.check_results}/></details></div>{open?<BoundExplanation detail={detail} environmentId={environmentId} onClose={()=>setOpen(false)}/>:null}</div></div>
}
export function PortraitSummaryLinks({detail,environmentId}:{detail:InspectionRunResult;environmentId:string}) {
 const assets=[...new Map(detail.check_results.map(row=>[row.asset_id,row])).values()].slice(0,3)
 return <section className="run-portrait-links"><h3>资源画像 · 当前观测入口</h3><p>画像是当前描述数据，与本轮历史检查分开。</p><div>{assets.map(row=><Link key={row.asset_id} to={row.inspection_item_code==='hardware.host_health'?`/performance-profiles/node/${encodeURIComponent(row.asset_id)}?environment=${environmentId}`:`/performance-profiles?environment=${environmentId}&q=${encodeURIComponent(row.asset_name)}`}>{row.asset_name} · 查看画像 →</Link>)}<Link to={`/performance-profiles?environment=${environmentId}`}>全部性能画像 →</Link></div></section>
}
