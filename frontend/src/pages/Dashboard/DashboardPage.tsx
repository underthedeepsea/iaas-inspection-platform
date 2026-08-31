import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Progress, Skeleton, Tag } from 'antd'
import { Link } from 'react-router-dom'

import { getApiError } from '../../api/http'
import { getDashboardToday, type DashboardRisk } from '../../api/dashboard'
import { getResourceTypes, resourceKeys, type ResourceType } from '../../api/resources'
import { InspectionTriggerButton } from '../../features/inspection-trigger/InspectionTriggerButton'
import { HealthTrendChart } from '../../features/resource-health/HealthTrendChart'
import { ResourceHealthCard } from '../../features/resource-health/ResourceHealthCard'
import { ResourceKPI } from '../../features/resource-health/ResourceKPI'
import { resourceCodeToSlug } from '../../features/resource-health/resourceRoutes'
import { useUiStore } from '../../stores/uiStore'

function formatDate(value?: string | null) {
  if (!value) return '等待数据'
  return value.slice(0, 10)
}

function total(resources: ResourceType[], key: 'risk_count' | 'p1_count' | 'p2_count' | 'asset_count') {
  return resources.reduce((sum, resource) => sum + resource[key], 0)
}

function averageHealth(resources: ResourceType[]) {
  const scores = resources.map((resource) => resource.health_score).filter((value): value is number => value != null)
  return scores.length ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length) : '—'
}

function asPercent(value?: number | null) {
  return Math.min(100, Math.max(0, Math.round(value ?? 0)))
}

function fallbackRisks(resources: ResourceType[]): DashboardRisk[] {
  return resources
    .filter((resource) => resource.risk_count > 0)
    .map((resource) => ({
      id: resource.code,
      title: resource.name,
      domain: '资源对象',
      severity: resource.p1_count ? 'P1' : resource.p2_count ? 'P2' : 'P3',
      status: 'PENDING_ACTION',
      occurrence_count: resource.risk_count,
      ai_involved: false,
      last_seen_at: resource.last_inspection_at,
      href: `/resources/${resourceCodeToSlug(resource.code)}`,
    }))
}

function statusLabel(status: string) {
  return ({
    ACTIVE: '持续中',
    NEW: '新增',
    PENDING_ACTION: '待处置',
    PENDING_REVERIFY: '待复验',
    WORSENED: '已加重',
  } as Record<string, string>)[status] ?? status
}

export function DashboardPage({
  environmentId: providedEnvironmentId,
  onOpenInspection,
}: {
  environmentId?: string | null
  onOpenInspection?: () => void
}) {
  const storeEnvironmentId = useUiStore((state) => state.environmentId)
  const environmentId = providedEnvironmentId ?? storeEnvironmentId
  const resourcesQuery = useQuery({
    queryKey: resourceKeys.list(environmentId ?? 'none'),
    queryFn: () => getResourceTypes(environmentId as string),
    enabled: Boolean(environmentId),
  })
  const dashboardQuery = useQuery({
    queryKey: ['dashboard', 'today', environmentId ?? 'none'],
    queryFn: () => getDashboardToday(environmentId as string),
    enabled: Boolean(environmentId),
  })

  if (!environmentId) {
    return <section className="view"><div className="empty-state"><strong>今天的巡检还没开始</strong><p>请选择顶部环境后查看每日巡检、重点风险和完整性摘要。</p></div></section>
  }
  if (resourcesQuery.isLoading) {
    return <section className="view" aria-label="资源健康度加载中"><div className="empty-state"><strong>正在读取每日巡检</strong><Skeleton active paragraph={{ rows: 2 }} /></div></section>
  }
  if (resourcesQuery.isError) {
    const error = getApiError(resourcesQuery.error)
    return <section className="view"><div className="empty-state"><Alert description={<>{error?.message ?? '资源健康度加载失败'}{error?.trace_id ? <small className="alert-trace">追踪 ID：{error.trace_id}</small> : null}</>} message="每日巡检暂时无法加载" showIcon type="error" /><Button autoInsertSpace={false} onClick={() => void resourcesQuery.refetch()} type="default">重试</Button></div></section>
  }

  const resources = resourcesQuery.data?.items ?? []
  if (resources.length === 0) {
    return <section className="view"><div className="empty-state"><strong>还没有可展示的资源巡检数据</strong><p>请选择其他环境或先执行一次巡检。</p>{onOpenInspection ? <button className="button button-primary" onClick={onOpenInspection} type="button">立即巡检</button> : <InspectionTriggerButton environmentId={environmentId} resourceTypes={resources} />}</div></section>
  }

  const snapshot = dashboardQuery.data?.snapshot
  const riskCount = snapshot?.risk_total ?? total(resources, 'risk_count')
  const p1Count = snapshot?.p1_count ?? total(resources, 'p1_count')
  const p2Count = snapshot?.p2_count ?? total(resources, 'p2_count')
  const overallHealth = averageHealth(resources)
  const coverage = snapshot && snapshot.assets_total ? Math.round((snapshot.assets_covered / snapshot.assets_total) * 100) : '—'
  const coverageDetail = snapshot && snapshot.assets_total ? `${snapshot.assets_covered} / ${snapshot.assets_total} 个对象` : '等待本轮快照'
  const aiCount = snapshot?.ai_dependent_cases ?? 0
  const completeness = snapshot ? asPercent(snapshot.data_completeness_rate) : 0
  const maturity = dashboardQuery.data?.capability_maturity ?? { enabled_items: 0, coded_items: 0 }
  const topRisks = dashboardQuery.data?.top_risks?.length ? dashboardQuery.data.top_risks : fallbackRisks(resources)
  const trend = dashboardQuery.data?.trend_7d ?? []
  const newDiff = dashboardQuery.data?.yesterday_diff?.new_count
  const freshness = snapshot ? `最后完成：${formatDate(snapshot.snapshot_date)}` : '等待今日快照'

  return (
    <section className="view" aria-labelledby="dashboard-title">
      <div className="page-heading">
        <div>
          <span className="eyebrow">DAILY INSPECTION · {formatDate(snapshot?.snapshot_date)}</span>
          <h2 id="dashboard-title">租户区智能巡检</h2>
          <p className="lede">先看整体状态，再进入资源、风险和证据详情。内部执行细节只在需要时展开。</p>
        </div>
        <div className="heading-actions">
          <span className="freshness">{freshness}</span>
          {onOpenInspection ? <button className="button button-primary" onClick={onOpenInspection} type="button">立即巡检</button> : <InspectionTriggerButton environmentId={environmentId} resourceTypes={resources} />}
        </div>
      </div>

      <div className="metric-grid" data-dashboard-metrics data-dashboard-section="kpi">
        <ResourceKPI label="整体健康度" value={overallHealth} detail={newDiff == null ? '资源类型平均值' : `${newDiff >= 0 ? '↑' : '↓'} ${Math.abs(newDiff)} vs 昨日`} />
        <ResourceKPI label="当前风险" value={riskCount} detail={`P1/P2 ${p1Count} / ${p2Count}`} tone={p1Count ? 'critical' : p2Count ? 'warn' : undefined} />
        <ResourceKPI label="巡检覆盖率" value={typeof coverage === 'number' ? `${coverage}%` : coverage} detail={coverageDetail} />
        <ResourceKPI label="AI 介入" value={aiCount} detail="Code-first / 按需介入" />
      </div>

      <div className="dashboard-workspace-grid">
        <section className="panel dashboard-risk-panel" data-dashboard-section="trend-and-risks">
          <div className="section-heading"><div><span className="panel-kicker">重点风险</span><h3>关注队列</h3><p className="panel-lede">按影响和生命周期排序</p></div><Link className="text-link" to="/risks">风险中心 →</Link></div>
          <div className="dashboard-risk-list">
            {topRisks.slice(0, 6).map((risk) => (
              <article className="dashboard-risk-item" key={risk.id}>
                <Tag className={`severity-badge severity-${risk.severity.toLowerCase()}`} color={severityColor(risk.severity)}>{risk.severity}</Tag>
                <Link className="risk-row-link dashboard-risk-copy" to={risk.href ?? `/risks/${risk.id}`}>
                  <strong>{risk.title}</strong>
                  <small>{risk.domain} · {statusLabel(risk.status)}{risk.occurrence_count ? ` · 持续 ${risk.occurrence_count} 次发现` : ''}</small>
                </Link>
                <div className="dashboard-risk-meta"><span>{statusLabel(risk.status)}</span><Link to={risk.href ?? `/risks/${risk.id}`}>打开 →</Link></div>
              </article>
            ))}
            {topRisks.length === 0 ? <div className="empty-cell">当前没有需要关注的重点风险。</div> : null}
          </div>
        </section>

        <section className="panel dashboard-completeness-panel" data-dashboard-section="auxiliary">
          <div className="section-heading"><div><span className="panel-kicker">今日数据</span><h3>巡检完整性</h3><p className="panel-lede">完整数据让结论更稳定</p></div><span className="legend">当前 {completeness}%</span></div>
          <div className="dashboard-health-layout">
            <div className="ring-stat" style={{ '--ring-progress': completeness } as CSSProperties}><div className="ring-content"><strong>{completeness}</strong><span>完整性</span></div></div>
            <div className="dashboard-health-copy">
              <h4>{completeness >= 80 ? '大部分对象已覆盖' : '仍有对象等待覆盖'}</h4>
              <p>{snapshot ? `还有 ${Math.max(0, snapshot.assets_total - snapshot.assets_covered)} 个对象等待本轮快照。` : '等待今日快照完成后更新覆盖情况。'}</p>
              <dl className="dashboard-health-facts">
                <div><dt>已代码化能力</dt><dd>{maturity.coded_items} 个</dd></div>
                <div><dt>已启用能力</dt><dd>{maturity.enabled_items} 个</dd></div>
                <div><dt>待复验风险</dt><dd>{topRisks.filter((risk) => risk.status === 'PENDING_REVERIFY').length} 个</dd></div>
              </dl>
            </div>
          </div>
          <div className="dashboard-trend-block">
            <div className="trend-head"><strong>近 7 日风险趋势</strong><span>当前 {riskCount} 个</span></div>
            <HealthTrendChart metric="risk" trend={trend} />
          </div>
        </section>
      </div>

      <section className="panel dashboard-resource-panel" data-dashboard-section="resource-health">
        <div className="section-heading"><div><span className="panel-kicker">资源概览</span><h3>资源健康状态</h3><p className="panel-lede">按资源类型查看覆盖、健康度和风险</p></div><Link className="text-link" to="/resources">资源巡检 →</Link></div>
        <div className="resource-grid">{resources.map((resource) => <ResourceHealthCard key={resource.code} resource={resource} />)}</div>
      </section>

      <div className="dashboard-lower-grid">
        <section className="panel dashboard-ai-panel">
          <div className="section-heading"><div><span className="panel-kicker">运行边界</span><h3>AI 按需介入</h3><p className="panel-lede">先代码，后调查</p></div><span className="mode-badge">只读</span></div>
          <p className="body-copy">确定性的规则由代码完成。AI 只在证据不足或需要分类判断时介入，所有工具调用保持只读。</p>
          <div className="dashboard-ai-rule"><strong>当前运行边界</strong><span>最大调查 3 轮，最多 5 次 Tool Call，不执行写操作。</span></div>
          <div className="dashboard-ai-event">
            {topRisks[0] ? <span><strong>{topRisks[0].title}</strong><small>已完成证据收集，等待人工确认原因。</small></span> : <span><strong>暂无待调查案例</strong><small>当前没有需要 AI 介入的风险。</small></span>}
          </div>
          <Link className="text-link" to="/ai-runtime">查看 AI 运行情况 →</Link>
        </section>

        <section className="panel dashboard-maturity-panel">
          <div className="section-heading"><div><span className="panel-kicker">能力演进</span><h3>能力成熟度</h3></div><Link className="text-link" to="/evolution">看演进 →</Link></div>
          <div className="maturity-list">
            <div className="maturity-row"><span>代码化能力</span><strong>{maturity.coded_items}/{maturity.enabled_items || '—'}</strong><Progress percent={maturity.enabled_items ? Math.round((maturity.coded_items / maturity.enabled_items) * 100) : 0} showInfo={false} size="small" /></div>
            <div className="maturity-row"><span>资源对象覆盖</span><strong>{total(resources, 'asset_count')}</strong><Progress percent={completeness} showInfo={false} size="small" /></div>
            <div className="maturity-row"><span>AI 介入案例</span><strong>{snapshot?.ai_dependent_cases ?? 0}</strong><Progress percent={snapshot ? Math.min(100, snapshot.ai_dependent_cases * 10) : 0} showInfo={false} size="small" /></div>
          </div>
        </section>
      </div>
    </section>
  )
}

function severityColor(severity: string) {
  return ({ P1: 'red', P2: 'orange', P3: 'blue', P4: 'default' } as Record<string, string>)[severity] ?? 'default'
}
