import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getResourceRunDetail, resourceKeys } from '../../api/resources'
import { AIAnalysisPanel } from '../../features/ai-analysis/AIAnalysisPanel'
import { InspectionRunSummary } from '../../features/inspection-history/InspectionRunSummary'
import { resourceSlugToCode } from '../../features/resource-health/resourceRoutes'
import { useUiStore } from '../../stores/uiStore'

export function ResourceRunDetailPage({ environmentId: providedEnvironmentId }: { environmentId?: string | null }) {
  const { resourceType = '', runId = '' } = useParams()
  const storeEnvironmentId = useUiStore((state) => state.environmentId)
  const environmentId = providedEnvironmentId ?? storeEnvironmentId
  const code = resourceSlugToCode(resourceType)
  const query = useQuery({
    queryKey: resourceKeys.run(environmentId ?? 'none', code, runId),
    queryFn: () => getResourceRunDetail(code, runId, environmentId as string),
    enabled: Boolean(environmentId && runId),
  })

  if (!environmentId) return <section className="view"><div className="empty-state"><strong>巡检详情</strong><p>请选择巡检环境。</p></div></section>
  if (query.isLoading) return <section className="view"><div className="empty-state"><strong>正在加载巡检详情</strong><p>正在读取本轮巡检的覆盖率、Finding 和风险。</p></div></section>
  if (query.isError || !query.data) return <section className="view" role="alert"><div className="empty-state"><strong>巡检详情加载失败</strong><p>暂时无法读取本轮巡检结果。</p><button className="button button-secondary" onClick={() => void query.refetch()} type="button">重试</button></div></section>

  const detail = query.data
  const status = detail.run.status.toLowerCase()
  return (
    <section aria-labelledby="run-detail-title" className="view">
      <div className="back-row"><Link className="text-link" to={`/resources/${resourceType}?tab=history`}>← 返回巡检历史</Link><span className="muted">运行 ID：{runId}</span></div>
      <div className="page-heading">
        <div><span className="eyebrow">INSPECTION RUN</span><h2 id="run-detail-title">{detail.run.run_date} · {code} 巡检详情</h2><p className="lede">查看本轮执行结果、主要风险与 AI 补充研判。</p></div>
        <span className={`status-badge${status === 'failed' ? ' status-critical' : ''}`}>{detail.run.status}</span>
      </div>
      <InspectionRunSummary detail={detail} />
      <div className="content-grid">
        <section className="panel panel-large">
          <div className="section-heading"><div><span className="eyebrow">ATTENTION QUEUE</span><h3>主要风险</h3></div><span className="legend">本轮风险 {detail.risk_count}</span></div>
          {detail.major_risks.length ? <div className="evidence-list">{detail.major_risks.map((risk, index) => <article className="evidence-item" key={String(risk.id ?? index)}><header><strong>{String(risk.title ?? '未命名风险')}</strong><span className="severity-badge severity-p2">{String(risk.severity ?? '风险')}</span></header><p>{String(risk.conclusion ?? risk.description ?? '查看风险详情获取证据和处理建议。')}</p></article>)}</div> : <div className="empty-state compact"><strong>本轮没有主要风险</strong><p>当前资源运行结果没有需要优先关注的风险。</p></div>}
        </section>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">EXECUTION</span><h3>执行摘要</h3></div></div><dl className="definition-list"><div><dt>资源对象</dt><dd>{detail.coverage.assets_covered} / {detail.coverage.assets_total}</dd></div><div><dt>巡检项成功</dt><dd>{detail.inspection_item_status_counts.SUCCEEDED ?? 0}</dd></div><div><dt>AI 依赖案例</dt><dd>{detail.ai_dependent_cases}</dd></div><div><dt>完成时间</dt><dd>{detail.run.finished_at ?? '—'}</dd></div></dl></section>
      </div>
      <section className="panel run-ai-panel"><AIAnalysisPanel contextType="RESOURCE_RUN" environmentId={environmentId} inspectionRunId={runId} resourceCode={code} /></section>
    </section>
  )
}
