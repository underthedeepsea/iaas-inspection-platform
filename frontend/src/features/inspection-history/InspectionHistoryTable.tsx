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
  if (summaries.length === 0) return <div className="empty-state compact"><strong>暂无巡检历史</strong><p>完成一次巡检后，这里会记录覆盖率、Finding 和风险变化。</p></div>
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {['时间', '覆盖', '巡检项', 'Finding', '风险', 'AI', '状态'].map((label) => <th key={label}>{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {summaries.map((summary) => (
            <tr key={summary.inspection_run_id}>
              <td>
                <button className="text-link button-link" onClick={() => navigate(`/resources/${resourceCodeToSlug(resourceCode)}/runs/${summary.inspection_run_id}`)} type="button">
                  {summary.run_date}
                </button>
              </td>
              <td>{summary.coverage_rate == null ? '—' : `${Math.round(summary.coverage_rate * 100)}%`}</td>
              <td>{summary.inspection_item_count}</td>
              <td>{summary.finding_count}</td>
              <td>{summary.risk_count}</td>
              <td>{summary.ai_investigation_count}</td>
              <td><span className={`status-badge${summary.status === 'FAILED' ? ' status-critical' : ''}`}>{summary.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
