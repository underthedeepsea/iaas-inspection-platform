import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { getResourceRunDetail, resourceKeys } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'
import { resourceSlugToCode } from '../../features/resource-health/resourceRoutes'
import { InspectionRunSummary } from '../../features/inspection-history/InspectionRunSummary'

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
  if (!environmentId) return <section><h1>巡检详情</h1><p>请选择巡检环境。</p></section>
  if (query.isLoading) return <section><h1>巡检详情</h1><p>正在加载巡检详情</p></section>
  if (query.isError || !query.data) return <section role="alert"><h1>巡检详情</h1><p>巡检详情加载失败</p><button onClick={() => void query.refetch()} type="button">重试</button></section>
  const detail = query.data
  return (
    <section>
      <p style={{ color: '#6b7280', fontSize: 13 }}><Link to={`/resources/${resourceType}?tab=history`}>返回巡检历史</Link></p>
      <h1>{detail.run.run_date} · {code} 巡检详情</h1>
      <InspectionRunSummary detail={detail} />
      <section style={{ marginTop: 28 }}>
        <h2>主要风险</h2>
        {detail.major_risks.length ? <ul>{detail.major_risks.map((risk, index) => <li key={String(risk.id ?? index)}>{String(risk.title ?? '未命名风险')}</li>)}</ul> : <p>本轮没有主要风险。</p>}
      </section>
    </section>
  )
}

