import type { ResourceRunDetail } from '../../api/resources'

export function InspectionRunSummary({ detail }: { detail: ResourceRunDetail }) {
  const metrics = [
    ['状态', detail.run.status],
    ['覆盖', `${Math.round(detail.coverage.rate * 100)}%`],
    ['巡检项', detail.inspection_item_count],
    ['Finding', detail.finding_count],
    ['风险', detail.risk_count],
    ['P1 / P2', `${detail.severity_counts.P1 ?? 0} / ${detail.severity_counts.P2 ?? 0}`],
    ['AI 分析', detail.ai_investigation_count],
  ]
  return (
    <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
      {metrics.map(([label, value]) => (
        <div key={label} style={{ background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 14 }}>
          <div style={{ color: '#6b7280', fontSize: 12 }}>{label}</div>
          <div style={{ fontSize: 20, fontWeight: 700, marginTop: 5 }}>{value}</div>
        </div>
      ))}
    </div>
  )
}

