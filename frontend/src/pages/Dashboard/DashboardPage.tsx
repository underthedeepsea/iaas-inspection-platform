import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Progress, Skeleton, Table, Tag } from 'antd'
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
  const completeness = snapshot ? Math.round(snapshot.data_completeness_rate * 100) : 0
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

      <section className="panel dashboard-resource-panel" data-dashboard-section="resource-health">
        <div className="section-heading"><div><span className="eyebrow">RESOURCE HEALTH</span><h3>资源健康状态</h3></div><Link className="text-link" to="/resources">查看资源巡检</Link></div>
        <div className="resource-grid">{resources.map((resource) => <ResourceHealthCard key={resource.code} resource={resource} />)}</div>
      </section>

      <div className="content-grid content-grid-wide" data-dashboard-section="trend-and-risks">
        <section className="panel">
          <div className="section-heading"><div><span className="eyebrow">LAST 7 DAYS</span><h3>风险趋势</h3></div><span className="legend">风险总数 · 当前 {riskCount}</span></div>
          <HealthTrendChart metric="risk" trend={trend} />
        </section>
        <section className="panel panel-large">
          <div className="section-heading"><div><span className="eyebrow">ATTENTION QUEUE</span><h3>重点风险</h3></div><Link className="text-link" to="/risks">查看全部</Link></div>
          <Table
            className="data-table dashboard-risk-table"
            columns={[
              { title: '风险', dataIndex: 'title', render: (_value, risk: DashboardRisk) => <Link className="risk-row-link risk-name" to={risk.href ?? `/risks/${risk.id}`}><strong>{risk.title}</strong><small>{risk.domain}</small></Link> },
              { title: '级别', dataIndex: 'severity', render: (value: string) => <Tag className={`severity-badge severity-${value.toLowerCase()}`} color={severityColor(value)}>{value}</Tag> },
              { title: '状态', dataIndex: 'status', render: (value: string, risk: DashboardRisk) => <Tag className={`status-badge${risk.severity === 'P1' ? ' status-critical' : ''}`}>{statusLabel(value)}</Tag> },
              { title: '最近发现', dataIndex: 'last_seen_at', render: (value: string | null) => <span className="muted">{formatDate(value)}</span> },
              { title: '', key: 'action', render: (_value, risk: DashboardRisk) => <Link className="text-link" to={risk.href ?? `/risks/${risk.id}`}>查看 →</Link> },
            ]}
            dataSource={topRisks.slice(0, 6)}
            locale={{ emptyText: '当前没有需要关注的重点风险。' }}
            pagination={false}
            rowKey="id"
            size="small"
          />
        </section>
      </div>

      <div className="content-grid" data-dashboard-section="auxiliary">
        <section className="panel">
          <div className="section-heading"><div><span className="eyebrow">COMPLETENESS</span><h3>巡检完整性</h3></div></div>
          <div className="ring-stat" style={{ '--ring-progress': completeness } as CSSProperties}><div className="ring-content"><strong>{completeness}</strong><span>%</span></div></div>
          <p className="muted">数据完整性越高，风险结论越稳定。</p>
          <div className="mini-stats"><span><b>{maturity.coded_items}</b> 个能力已代码化</span><span><b>{maturity.enabled_items}</b> 个能力已启用</span></div>
        </section>
        <section className="panel">
          <div className="section-heading"><div><span className="eyebrow">MATURITY</span><h3>能力成熟度</h3></div><Link className="text-link" to="/evolution">看演进</Link></div>
          <div className="maturity-list">
            <div className="maturity-row"><span>代码化能力</span><strong>{maturity.coded_items}/{maturity.enabled_items || '—'}</strong><Progress percent={maturity.enabled_items ? Math.round((maturity.coded_items / maturity.enabled_items) * 100) : 0} showInfo={false} size="small" /></div>
            <div className="maturity-row"><span>资源对象覆盖</span><strong>{total(resources, 'asset_count')}</strong><Progress percent={snapshot ? Math.round(snapshot.data_completeness_rate * 100) : 0} showInfo={false} size="small" /></div>
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
