import { RunCounts, RunFactsWorkspace, PortraitSummaryLinks } from '../../features/run-overview/RunOverview'
import { reportLabel } from '../../features/inspection-history/resultLabels'
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { getInspectionRunResult } from '../../api/inspectionRunResult'
import { FrozenMappingProvenance } from '../../features/inspection-history/FrozenMappingProvenance'
import { useUiStore } from '../../stores/uiStore'

export function InspectionRunResultPage() {
  const {runId = ''} = useParams()
  const environmentId = useUiStore(state => state.environmentId)
  const {hash} = useLocation()
  const [params] = useSearchParams()
  const query = useQuery({queryKey:['inspection-result',environmentId,runId],queryFn:() => getInspectionRunResult(runId,environmentId!),enabled:Boolean(environmentId && runId),refetchInterval:query => query.state.data && !['SUCCEEDED','PARTIAL','FAILED'].includes(query.state.data.run.status) ? 5000 : false})
  useEffect(() => { if (query.data && hash) revealReportTarget(hash) }, [query.data,hash])
  if (!environmentId) return <div className="empty-state">请选择巡检环境。</div>
  if (query.isLoading) return <div className="empty-state" role="status">正在读取本次巡检结果…</div>
  if (query.isError || !query.data) return <div className="empty-state" role="alert"><strong>无法读取本次巡检结果</strong><p>请确认所选环境，或稍后重试。</p><button className="button button-secondary" onClick={() => void query.refetch()}>重试</button><Link className="text-link" to="/">返回总览</Link></div>
  const detail = query.data
  const conclusion = reportLabel(detail.fact_report?.checks ?? detail.check_results)
  const statusLabel = ({SUCCEEDED:'已完成',PARTIAL:'部分完成',FAILED:'执行失败'} as Record<string,string>)[detail.run.status] ?? '正在巡检'
  return <section className="view inspection-result-view" aria-labelledby="inspection-result-title"><div className="back-row"><Link className="text-link" to={`/?environment=${environmentId}`}>← 返回总览</Link><Link className="text-link" to="/rules">查看规则库 →</Link></div><div className="page-heading"><div><span className="eyebrow">INSPECTION REPORT</span><h2 id="inspection-result-title">本次巡检结果</h2><p className="lede">检查结论、执行证据与风险，集中在同一份巡检记录中。</p></div><span className={`run-state run-state-${detail.run.status.toLowerCase()}`}>{statusLabel} · {conclusion}</span></div>
    <div className="run-context-bar"><span className="mono run-identity">RUN {runId}</span><span>{detail.run.trigger_type === 'MANUAL' ? '手动巡检' : detail.run.trigger_type}</span><time>{detail.run.finished_at ? new Date(detail.run.finished_at).toLocaleString('zh-CN') : detail.run.run_date}</time><div>{detail.scope.resource_types.map(code => <span className="resource-type-tag" key={code}>{code === 'CONTROL_PLANE' ? '控制面' : code === 'LLM_RUNTIME' ? 'LLM 运行时' : code}</span>)}</div></div>
    <FrozenMappingProvenance inputs={detail.mapping_inputs} quality={detail.mapping_input_quality} />
    {detail.run.status === 'FAILED' ? <p className="ai-error" role="alert">{detail.run.error_message || '巡检执行失败，请查看已产生的检查记录。'}</p> : null}
    <RunCounts detail={detail}/>
    <RunFactsWorkspace key={`${environmentId}:${runId}`} detail={detail} environmentId={environmentId} initialOpen={params.get('interpret')==='1'||hash==='#ai-explanation'}/>
    <PortraitSummaryLinks detail={detail} environmentId={environmentId}/>
    <section className="panel result-risk-panel"><div className="section-heading"><div><h3>本次关联风险</h3><p className="panel-lede">本次 CODE 检查发现并关联的风险，状态展示当前处置进展。</p></div><span className="legend">{detail.summary.risk_count} 个风险</span></div>{detail.risks.length ? <div className="dashboard-risk-list">{detail.risks.map(risk => <article className="dashboard-risk-item" key={risk.id}><span className={`severity-badge severity-${risk.severity.toLowerCase()}`}>{risk.severity}</span><Link className="dashboard-risk-copy" to={`/risks/${risk.id}?environment=${environmentId}`}><strong>{risk.title}</strong><small>{detail.check_results.find(row => row.asset_id === risk.primary_asset_id)?.asset_name ?? risk.primary_asset_id} · {risk.domain} · 当前  {({PERSISTING:'持续中',NEW:'新增',PENDING_ACTION:'待处置',PENDING_REVERIFY:'待复验',RECOVERED:'已恢复',IGNORED:'已忽略',WORSENED:'已加重'} as Record<string,string>)[risk.status] ?? risk.status}</small></Link><Link className="text-link" to={`/risks/${risk.id}?environment=${environmentId}`}>查看风险 →</Link></article>)}</div> : <p className="empty-cell">本次没有关联风险。请同时关注采集缺项、历史不足和执行失败的检查。</p>}</section>
  </section>
}

export function revealReportTarget(hash: string) {
  const target = document.getElementById(hash.slice(1))
  if (!target) return
  let ancestor = target.parentElement
  while (ancestor) {
    if (ancestor instanceof HTMLDetailsElement) ancestor.open = true
    ancestor = ancestor.parentElement
  }
  target.scrollIntoView({block: 'start'})
}
