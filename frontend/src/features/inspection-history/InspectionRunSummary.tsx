import type { ResourceRunDetail } from '../../api/resources'

export function InspectionRunSummary({ detail }: { detail: ResourceRunDetail }) {
  const metrics = [
    ['状态', detail.run.status],
    ['覆盖率', detail.coverage.rate == null ? '—' : `${Math.round(detail.coverage.rate * 100)}%`],
    ['巡检项', detail.inspection_item_count],
    ['Finding', detail.finding_count],
    ['风险', detail.risk_count],
    ['P1/P2', `${detail.severity_counts.P1 ?? 0} / ${detail.severity_counts.P2 ?? 0}`],
    ['AI 分析', detail.ai_investigation_count],
  ]
  return (
    <div className="metric-grid run-summary-grid">
      {metrics.map(([label, value]) => (
        <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong></article>
      ))}
    </div>
  )
}
