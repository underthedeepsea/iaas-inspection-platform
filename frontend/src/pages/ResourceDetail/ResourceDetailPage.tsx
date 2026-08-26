import { useQuery } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { getResourceHistory, getResourceOverview, resourceKeys } from '../../api/resources'
import { AIAnalysisPanel } from '../../features/ai-analysis/AIAnalysisPanel'
import { InspectionHistoryTable } from '../../features/inspection-history/InspectionHistoryTable'
import { InspectionTriggerButton } from '../../features/inspection-trigger/InspectionTriggerButton'
import { HealthTrendChart } from '../../features/resource-health/HealthTrendChart'
import { resourceSlugToCode } from '../../features/resource-health/resourceRoutes'
import { useUiStore } from '../../stores/uiStore'

const tabs = [
  ['overview', '概览'],
  ['history', '巡检历史'],
  ['risks', '当前风险'],
  ['ai', 'AI 分析'],
] as const

export function ResourceDetailPage({ environmentId: providedEnvironmentId }: { environmentId?: string | null }) {
  const { resourceType = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const storeEnvironmentId = useUiStore((state) => state.environmentId)
  const environmentId = providedEnvironmentId ?? storeEnvironmentId
  const code = resourceSlugToCode(resourceType)
  const requestedTab = searchParams.get('tab') ?? 'overview'
  const activeTab = tabs.some(([value]) => value === requestedTab) ? requestedTab : 'overview'
  const overviewQuery = useQuery({
    queryKey: resourceKeys.detail(environmentId ?? 'none', code),
    queryFn: () => getResourceOverview(code, environmentId as string),
    enabled: Boolean(environmentId),
  })
  const historyQuery = useQuery({
    queryKey: resourceKeys.history(environmentId ?? 'none', code),
    queryFn: () => getResourceHistory(code, { environmentId: environmentId as string }),
    enabled: Boolean(environmentId) && activeTab === 'history',
  })

  if (!environmentId) return <section className="view"><div className="empty-state"><strong>资源详情</strong><p>请选择巡检环境。</p></div></section>

  const resource = overviewQuery.data?.resource_type
  const resourceName = resource?.name ?? code
  const latest = overviewQuery.data?.latest

  return (
    <section aria-labelledby="resource-detail-title" className="view">
      <div className="back-row"><Link className="text-link" to="/resources">← 返回资源巡检</Link><span className="muted">{code}</span></div>
      <div className="page-heading">
        <div><span className="eyebrow">RESOURCE DETAIL</span><h2 id="resource-detail-title">{resourceName}</h2><p className="lede">{resource?.description ?? '查看资源健康、巡检历史、风险和 AI 研判。'}</p></div>
        <div className="heading-actions"><span className="freshness">{latest?.run_date ? `最近巡检：${latest.run_date}` : '等待最近巡检'}</span>{resource ? <InspectionTriggerButton environmentId={environmentId} resourceTypes={[resource]} /> : null}</div>
      </div>
      <div aria-label="资源详情标签" className="detail-tabs" role="tablist">
        {tabs.map(([value, label]) => <button aria-selected={activeTab === value} className={`detail-tab${activeTab === value ? ' is-active' : ''}`} onClick={() => setSearchParams({ tab: value })} role="tab" type="button" key={value}>{label}</button>)}
      </div>
      {activeTab === 'history' ? (
        <section className="panel panel-large"><div className="section-heading"><div><span className="eyebrow">INSPECTION HISTORY</span><h3>巡检历史</h3></div><span className="legend">按时间回看每次执行</span></div>{historyQuery.isLoading ? <div className="empty-state compact"><p>正在加载巡检历史</p></div> : <InspectionHistoryTable resourceCode={code} summaries={historyQuery.data?.items ?? []} />}</section>
      ) : activeTab === 'overview' ? (
        <OverviewPanel overview={overviewQuery.data} />
      ) : activeTab === 'risks' ? (
        <RiskPanel overview={overviewQuery.data} />
      ) : (
        <section className="panel panel-large"><AIAnalysisPanel contextType="RESOURCE_TYPE" environmentId={environmentId} resourceCode={code} /></section>
      )}
    </section>
  )
}

function OverviewPanel({ overview }: { overview?: Awaited<ReturnType<typeof getResourceOverview>> }) {
  if (!overview) return <section className="panel"><div className="empty-state compact"><strong>正在加载资源概览</strong><p>正在读取健康度、覆盖率和趋势数据。</p></div></section>
  const latest = overview.latest
  const metrics = [
    ['健康度', latest?.health_score ?? '—', latest?.health_score == null ? '等待巡检结果' : '最近一轮巡检'],
    ['巡检覆盖率', latest ? `${Math.round(latest.coverage_rate * 100)}%` : '—', '已覆盖资源对象'],
    ['当前风险', latest?.risk_count ?? 0, '跨运行关联后的风险'],
    ['P1/P2', `${latest?.p1_count ?? 0} / ${latest?.p2_count ?? 0}`, '按严重级别统计'],
  ] as const
  return (
    <>
      <div className="metric-grid">{metrics.map(([label, value, detail]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>)}</div>
      <div className="content-grid">
        <section className="panel panel-large"><div className="section-heading"><div><span className="eyebrow">HEALTH TREND</span><h3>健康趋势</h3></div><span className="legend">最近 {overview.health_trend.length} 次巡检</span></div><HealthTrendChart trend={overview.health_trend} /></section>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">LATEST RUN</span><h3>最近巡检</h3></div></div><dl className="definition-list"><div><dt>运行日期</dt><dd>{latest?.run_date ?? '—'}</dd></div><div><dt>巡检项</dt><dd>{latest?.inspection_item_count ?? '—'}</dd></div><div><dt>Finding</dt><dd>{latest?.finding_count ?? '—'}</dd></div><div><dt>AI 依赖案例</dt><dd>{latest?.ai_dependent_cases ?? '—'}</dd></div></dl></section>
      </div>
    </>
  )
}

function RiskPanel({ overview }: { overview?: Awaited<ReturnType<typeof getResourceOverview>> }) {
  const riskCount = overview?.latest?.risk_count ?? 0
  return <section className="panel"><div className="section-heading"><div><span className="eyebrow">RISK SNAPSHOT</span><h3>当前风险</h3></div><span className="severity-badge severity-p2">{riskCount} 项</span></div><div className="empty-state compact"><strong>{riskCount ? '风险详情将在风险中心展示' : '当前没有资源风险'}</strong><p>{riskCount ? '进入风险中心查看生命周期、证据和处置动作。' : '下一轮巡检会继续验证资源状态。'}</p><Link className="button button-secondary" to="/risks">打开风险中心</Link></div></section>
}
