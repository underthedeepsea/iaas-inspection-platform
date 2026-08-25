import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { getResourceTypes, resourceKeys } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'
import { ResourceHealthCard } from '../../features/resource-health/ResourceHealthCard'
import { resourceCodeToSlug } from '../../features/resource-health/resourceRoutes'

export function ResourcesPage({ environmentId: providedEnvironmentId }: { environmentId?: string | null }) {
  const storeEnvironmentId = useUiStore((state) => state.environmentId)
  const environmentId = providedEnvironmentId ?? storeEnvironmentId
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: resourceKeys.list(environmentId ?? 'none'),
    queryFn: () => getResourceTypes(environmentId as string),
    enabled: Boolean(environmentId),
  })
  if (!environmentId) return <section><h1>资源巡检</h1><p>请选择巡检环境。</p></section>
  if (query.isLoading) return <section><h1>资源巡检</h1><p>正在加载资源类型</p></section>
  if (query.isError) return <section role="alert"><h1>资源巡检</h1><p>资源类型加载失败</p><button onClick={() => void query.refetch()} type="button">重试</button></section>
  const resources = query.data?.items ?? []
  return (
    <section>
      <header style={{ marginBottom: 24 }}><h1 style={{ marginBottom: 6 }}>资源巡检</h1><p style={{ color: '#6b7280', margin: 0 }}>按资源类型查看健康度、历史与风险。</p></header>
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
        {resources.map((resource) => <ResourceHealthCard key={resource.code} onOpen={() => navigate(`/resources/${resourceCodeToSlug(resource.code)}`)} resource={resource} />)}
      </div>
    </section>
  )
}

