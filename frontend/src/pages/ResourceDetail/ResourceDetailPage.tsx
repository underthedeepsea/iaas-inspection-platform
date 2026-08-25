import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'

import { getResourceHistory, getResourceOverview, resourceKeys } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'
import { resourceSlugToCode } from '../../features/resource-health/resourceRoutes'
import { InspectionHistoryTable } from '../../features/inspection-history/InspectionHistoryTable'
import { AIAnalysisPanel } from '../../features/ai-analysis/AIAnalysisPanel'

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
    enabled: Boolean(environmentId) && activeTab !== 'history',
  })
  const historyQuery = useQuery({
    queryKey: resourceKeys.history(environmentId ?? 'none', code),
    queryFn: () => getResourceHistory(code, { environmentId: environmentId as string }),
    enabled: Boolean(environmentId) && activeTab === 'history',
  })

  if (!environmentId) return <section><h1>资源详情</h1><p>请选择巡检环境。</p></section>
  const resource = overviewQuery.data?.resource_type
  return (
    <section>
      <header style={{ marginBottom: 20 }}>
        <p style={{ color: '#6b7280', fontSize: 13, marginBottom: 6 }}>资源巡检 / {code}</p>
        <h1 style={{ margin: 0 }}>{resource?.name ?? code}</h1>
      </header>
      <div role="tablist" style={{ borderBottom: '1px solid #e5e7eb', display: 'flex', gap: 22, marginBottom: 22 }}>
        {tabs.map(([value, label]) => (
          <button
            aria-selected={activeTab === value}
            onClick={() => setSearchParams({ tab: value })}
            role="tab"
            style={{ background: 'none', border: 0, borderBottom: `2px solid ${activeTab === value ? '#f97316' : 'transparent'}`, color: activeTab === value ? '#c2410c' : '#6b7280', cursor: 'pointer', padding: '10px 0' }}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === 'history' ? (
        historyQuery.isLoading ? <p>正在加载巡检历史</p> : <InspectionHistoryTable resourceCode={code} summaries={historyQuery.data?.items ?? []} />
      ) : activeTab === 'overview' ? (
        <OverviewPanel overview={overviewQuery.data} />
      ) : activeTab === 'risks' ? (
        <section><h2>当前风险</h2><p>{overviewQuery.data?.latest?.risk_count ?? 0} 项资源风险</p></section>
      ) : (
        <AIAnalysisPanel contextType="RESOURCE_TYPE" environmentId={environmentId} resourceCode={code} />
      )}
    </section>
  )
}

function OverviewPanel({ overview }: { overview?: Awaited<ReturnType<typeof getResourceOverview>> }) {
  if (!overview) return <p>正在加载资源概览</p>
  const latest = overview.latest
  return (
    <section>
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
        <div><span>健康度</span><strong style={{ display: 'block', fontSize: 30 }}>{latest?.health_score ?? '—'}</strong></div>
        <div><span>覆盖率</span><strong style={{ display: 'block', fontSize: 30 }}>{latest ? `${Math.round(latest.coverage_rate * 100)}%` : '—'}</strong></div>
        <div><span>风险</span><strong style={{ display: 'block', fontSize: 30 }}>{latest?.risk_count ?? 0}</strong></div>
      </div>
      <p style={{ color: '#6b7280', marginTop: 24 }}>最近 {overview.health_trend.length} 次巡检可用于趋势对比。</p>
    </section>
  )
}
