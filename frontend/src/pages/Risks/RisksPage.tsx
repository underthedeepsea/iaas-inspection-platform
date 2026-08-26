import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { getRisks, riskKeys, type Risk } from '../../api/risks'
import { useUiStore } from '../../stores/uiStore'

const filters = [
  ['全部', '', ''],
  ['P1', 'P1', ''],
  ['P2', 'P2', ''],
  ['P3', 'P3', ''],
  ['待处置', '', 'PENDING_ACTION'],
  ['待复验', '', 'PENDING_REVERIFY'],
] as const

const statusLabels: Record<string, string> = {
  NEW: '首次发现',
  PERSISTING: '风险持续',
  WORSENED: '风险加重',
  INVESTIGATING: '调查中',
  LOCATED: '已定位',
  PENDING_ACTION: '待处置',
  PENDING_REVERIFY: '待复验',
  RECOVERED: '已恢复',
  IGNORED: '已忽略',
}

function formatDate(value?: string | null) {
  return value ? value.slice(0, 10) : '—'
}

export function RisksPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const environmentId = useUiStore((state) => state.environmentId)
  const severity = searchParams.get('severity') ?? ''
  const status = searchParams.get('status') ?? ''
  const query = useQuery({
    queryKey: riskKeys.list({ environmentId: environmentId ?? undefined, severity: severity || undefined, status: status || undefined }),
    queryFn: () => getRisks({ environmentId: environmentId ?? undefined, severity: severity || undefined, status: status || undefined }),
  })

  const selectFilter = (nextSeverity: string, nextStatus: string) => {
    const next = new URLSearchParams()
    if (nextSeverity) next.set('severity', nextSeverity)
    if (nextStatus) next.set('status', nextStatus)
    setSearchParams(next)
  }

  return (
    <section aria-labelledby="risks-title" className="view">
      <div className="page-heading">
        <div><span className="eyebrow">RISK CENTER</span><h2 id="risks-title">风险中心</h2><p className="lede">按影响和生命周期管理风险，处置后仍需自动复验。</p></div>
        <button className="button button-secondary" onClick={() => void query.refetch()} type="button">刷新数据</button>
      </div>
      <div aria-label="风险筛选" className="filter-bar">
        {filters.map(([label, filterSeverity, filterStatus]) => <button aria-pressed={severity === filterSeverity && status === filterStatus} className={`filter-chip${severity === filterSeverity && status === filterStatus ? ' is-active' : ''}`} key={label} onClick={() => selectFilter(filterSeverity, filterStatus)} type="button">{label}</button>)}
      </div>
      <section className="panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>风险</th><th>领域</th><th>级别</th><th>状态</th><th>出现次数</th><th>AI 介入</th><th /></tr></thead>
            <tbody>
              {query.isLoading ? <tr><td className="empty-cell" colSpan={7}>正在加载风险…</td></tr> : null}
              {query.isError ? <tr><td className="empty-cell" colSpan={7}>风险数据加载失败，请重试。</td></tr> : null}
              {!query.isLoading && !query.isError && (query.data?.items ?? []).length === 0 ? <tr><td className="empty-cell" colSpan={7}>没有符合条件的风险。</td></tr> : null}
              {!query.isLoading && !query.isError ? (query.data?.items ?? []).map((risk) => <RiskRow key={risk.risk_id ?? risk.id} risk={risk} />) : null}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  )
}

function RiskRow({ risk }: { risk: Risk }) {
  const riskId = risk.risk_id ?? risk.id
  return <tr><td><Link className="risk-name risk-row-link" to={`/risks/${riskId}`}><strong>{risk.title || '未命名风险'}</strong><small>{risk.risk_key || '—'}</small></Link></td><td>{risk.domain || '—'}</td><td><span className={`severity-badge severity-${risk.severity.toLowerCase()}`}>{risk.severity}</span></td><td><span className={`status-badge${risk.severity === 'P1' ? ' status-critical' : ''}`}>{statusLabels[risk.status] ?? risk.status}</span></td><td>{risk.occurrence_count}</td><td>{risk.ai_involved ? <span className="ai-mark">AI 介入</span> : <span className="muted">代码判断</span>}</td><td><Link className="text-link" to={`/risks/${riskId}`}>打开 →</Link></td></tr>
}
