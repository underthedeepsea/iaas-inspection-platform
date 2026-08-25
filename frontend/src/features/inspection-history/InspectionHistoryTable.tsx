import { useNavigate } from 'react-router-dom'

import type { ResourceSummary } from '../../api/resources'
import { resourceCodeToSlug } from '../resource-health/resourceRoutes'

export function InspectionHistoryTable({
  resourceCode,
  summaries,
}: {
  resourceCode: string
  summaries: ResourceSummary[]
}) {
  const navigate = useNavigate()
  if (summaries.length === 0) return <p>暂无巡检历史</p>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', minWidth: 720, width: '100%' }}>
        <thead>
          <tr>
            {['时间', '覆盖', '巡检项', 'Finding', '风险', 'AI', '状态'].map((label) => <th key={label} style={{ borderBottom: '1px solid #e5e7eb', color: '#6b7280', fontSize: 12, padding: '10px 8px', textAlign: 'left' }}>{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {summaries.map((summary) => (
            <tr key={summary.inspection_run_id}>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>
                <button onClick={() => navigate(`/resources/${resourceCodeToSlug(resourceCode)}/runs/${summary.inspection_run_id}`)} style={{ background: 'none', border: 0, color: '#c2410c', cursor: 'pointer', padding: 0 }} type="button">
                  {summary.run_date}
                </button>
              </td>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>{Math.round(summary.coverage_rate * 100)}%</td>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>{summary.inspection_item_count}</td>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>{summary.finding_count}</td>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>{summary.risk_count}</td>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>{summary.ai_investigation_count}</td>
              <td style={{ borderBottom: '1px solid #f1f5f9', padding: '12px 8px' }}>{summary.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

