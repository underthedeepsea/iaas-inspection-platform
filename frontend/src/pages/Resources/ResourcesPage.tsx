import { useQuery } from '@tanstack/react-query'

import { getResourceTypes, resourceKeys } from '../../api/resources'
import { InspectionTriggerButton } from '../../features/inspection-trigger/InspectionTriggerButton'
import { ResourceHealthCard } from '../../features/resource-health/ResourceHealthCard'
import { ResourceKPI } from '../../features/resource-health/ResourceKPI'
import { useUiStore } from '../../stores/uiStore'

function sum(resources: Awaited<ReturnType<typeof getResourceTypes>>['items'], key: 'asset_count' | 'risk_count' | 'p1_count' | 'p2_count') {
  return resources.reduce((total, resource) => total + resource[key], 0)
}

function averageCoverage(resources: Awaited<ReturnType<typeof getResourceTypes>>['items']) {
  const values = resources.map((resource) => resource.coverage_rate).filter((value): value is number => value != null)
  return values.length ? Math.round((values.reduce((total, value) => total + value, 0) / values.length) * 100) : null
}

function severityTotal(resources: Awaited<ReturnType<typeof getResourceTypes>>['items']) {
  return resources.reduce((total, resource) => total + resource.p1_count + resource.p2_count, 0)
}

export function ResourcesPage({ environmentId: providedEnvironmentId }: { environmentId?: string | null }) {
  const storeEnvironmentId = useUiStore((state) => state.environmentId)
  const environmentId = providedEnvironmentId ?? storeEnvironmentId
  const query = useQuery({
    queryKey: resourceKeys.list(environmentId ?? 'none'),
    queryFn: () => getResourceTypes(environmentId as string),
    enabled: Boolean(environmentId),
  })

  if (!environmentId) return <section className="view"><div className="empty-state"><strong>资源巡检</strong><p>请选择顶部环境后查看各类资源的健康状态。</p></div></section>
  if (query.isLoading) return <section className="view"><div className="empty-state"><strong>正在加载资源类型</strong><p>正在读取当前环境的资源巡检状态。</p></div></section>
  if (query.isError) return <section className="view" role="alert"><div className="empty-state"><strong>资源类型加载失败</strong><p>暂时无法读取当前环境的资源状态。</p><button className="button button-secondary" onClick={() => void query.refetch()} type="button">重试</button></div></section>

  const resources = query.data?.items ?? []
  const coverage = averageCoverage(resources)
  return (
    <section aria-labelledby="resources-title" className="view">
      <div className="page-heading">
        <div><span className="eyebrow">RESOURCE INVENTORY</span><h2 id="resources-title">资源巡检</h2><p className="lede">先看哪类基础设施现在最有风险，再进入资源详情查看历史和证据。</p></div>
        <div className="heading-actions"><span className="freshness">{resources.length} 类资源</span><InspectionTriggerButton environmentId={environmentId} resourceTypes={resources} /></div>
      </div>
      <div className="metric-grid resource-summary-grid">
        <ResourceKPI label="全部资源" value={sum(resources, 'asset_count')} detail="当前环境活跃对象" />
        <ResourceKPI label="当前风险" value={sum(resources, 'risk_count')} detail={`P1/P2 ${sum(resources, 'p1_count')} / ${sum(resources, 'p2_count')}`} tone={sum(resources, 'p1_count') ? 'critical' : sum(resources, 'p2_count') ? 'warn' : undefined} />
        <ResourceKPI label="P1/P2" value={severityTotal(resources)} detail={`P1 ${sum(resources, 'p1_count')} · P2 ${sum(resources, 'p2_count')}`} tone={sum(resources, 'p1_count') ? 'critical' : sum(resources, 'p2_count') ? 'warn' : undefined} />
        <ResourceKPI label="平均覆盖率" value={coverage == null ? '—' : `${coverage}%`} detail="资源对象覆盖率" />
      </div>
      <section className="panel">
        <div className="section-heading"><div><span className="eyebrow">HEALTH OVERVIEW</span><h3>资源健康状态</h3></div><span className="legend">当前环境</span></div>
        {resources.length ? <div className="resource-grid">{resources.map((resource) => <ResourceHealthCard key={resource.code} resource={resource} />)}</div> : <div className="empty-state compact"><strong>暂无资源类型</strong><p>当前环境还没有可展示的资源巡检数据。</p></div>}
      </section>
    </section>
  )
}
