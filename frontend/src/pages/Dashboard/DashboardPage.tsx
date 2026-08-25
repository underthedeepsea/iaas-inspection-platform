import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { getApiError } from '../../api/http'
import { getResourceTypes, resourceKeys } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'
import { HealthTrendChart } from '../../features/resource-health/HealthTrendChart'
import { ResourceHealthCard } from '../../features/resource-health/ResourceHealthCard'
import { ResourceKPI } from '../../features/resource-health/ResourceKPI'
import { resourceCodeToSlug } from '../../features/resource-health/resourceRoutes'

export function DashboardPage({
  environmentId: providedEnvironmentId,
  onOpenInspection,
}: {
  environmentId?: string | null
  onOpenInspection?: () => void
}) {
  const storeEnvironmentId = useUiStore((state) => state.environmentId)
  const environmentId = providedEnvironmentId ?? storeEnvironmentId
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: resourceKeys.list(environmentId ?? 'none'),
    queryFn: () => getResourceTypes(environmentId as string),
    enabled: Boolean(environmentId),
  })

  if (!environmentId) {
    return (
      <section>
        <h1>总览</h1>
        <p>请选择巡检环境后查看资源健康度。</p>
      </section>
    )
  }
  if (query.isLoading) {
    return <section aria-label="资源健康度加载中">正在加载资源健康度</section>
  }
  if (query.isError) {
    const error = getApiError(query.error)
    return (
      <section role="alert">
        <h1>资源健康度</h1>
        <p>{error?.message ?? '资源健康度加载失败'}</p>
        {error?.trace_id ? <p>追踪 ID：{error.trace_id}</p> : null}
        <button onClick={() => void query.refetch()} type="button">重试</button>
      </section>
    )
  }

  const resources = query.data?.items ?? []
  if (resources.length === 0) {
    return (
      <section>
        <h1>总览</h1>
        <p>还没有可展示的资源巡检数据</p>
        <button onClick={onOpenInspection} type="button">立即巡检</button>
      </section>
    )
  }

  const healthScores = resources.map((resource) => resource.health_score).filter((value): value is number => value != null)
  const averageHealth = healthScores.length
    ? Math.round(healthScores.reduce((sum, value) => sum + value, 0) / healthScores.length)
    : '—'
  const riskCount = resources.reduce((sum, resource) => sum + resource.risk_count, 0)
  const assetCount = resources.reduce((sum, resource) => sum + resource.asset_count, 0)
  const p1p2Count = resources.reduce((sum, resource) => sum + resource.p1_count + resource.p2_count, 0)

  return (
    <section>
      <header style={{ alignItems: 'center', display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ marginBottom: 6 }}>总览</h1>
          <p style={{ color: '#6b7280', margin: 0 }}>按资源对象查看平台巡检健康度与变化趋势。</p>
        </div>
        <button onClick={onOpenInspection} type="button">⚡ 立即巡检</button>
      </header>
      <div style={{ background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 14, display: 'grid', gap: 20, gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', marginBottom: 24, padding: 20 }}>
        <ResourceKPI label="平均健康度" value={averageHealth} detail="资源类型平均值" />
        <ResourceKPI label="资源对象" value={assetCount} detail="当前环境活跃对象" />
        <ResourceKPI label="当前风险" value={riskCount} detail="资源级汇总" />
        <ResourceKPI label="P1 / P2" value={p1p2Count} detail="需优先关注" />
      </div>
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
        {resources.map((resource) => (
          <ResourceHealthCard
            key={resource.code}
            onOpen={() => navigate(`/resources/${resourceCodeToSlug(resource.code)}`)}
            resource={resource}
          />
        ))}
      </div>
      <div style={{ background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 14, marginTop: 24, padding: 20 }}>
        <h2 style={{ fontSize: 16, marginTop: 0 }}>健康趋势</h2>
        <p style={{ color: '#6b7280', fontSize: 13 }}>点击资源卡片查看具体资源类型的历史趋势。</p>
        <HealthTrendChart trend={[]} />
      </div>
    </section>
  )
}

