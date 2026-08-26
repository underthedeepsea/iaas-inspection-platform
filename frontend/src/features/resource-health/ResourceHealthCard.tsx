import { Link } from 'react-router-dom'

import type { ResourceType } from '../../api/resources'
import { resourceCodeToSlug } from './resourceRoutes'

export function ResourceHealthCard({ resource }: { resource: ResourceType }) {
  const health = resource.health_score == null ? '—' : String(Math.round(resource.health_score))
  const severity = resource.p1_count ? 'P1' : resource.p2_count ? 'P2' : resource.risk_count ? 'P3' : '正常'
  const coverage = resource.coverage_rate == null ? '—' : `${Math.round(resource.coverage_rate * 100)}%`
  const coverageDetail = resource.assets_covered == null || resource.assets_total == null
    ? '等待本轮快照'
    : `${resource.assets_covered} / ${resource.assets_total} 个对象`

  return (
    <article className="panel resource-card">
      <div className="resource-card-header">
        <Link to={`/resources/${resourceCodeToSlug(resource.code)}`}>
          <strong>{resource.name}</strong>
          <small>{resource.description || '资源对象健康状态'}</small>
        </Link>
        <span className={`severity-badge severity-${severity.toLowerCase()}`}>{severity}</span>
      </div>
      <div className="resource-card-health">
        <strong>{health}</strong>
        <span>健康度</span>
      </div>
      <div className="resource-card-meta">
        <span>{resource.asset_count} 个对象</span>
        <span>巡检项 {resource.inspection_item_count}</span>
        <span>风险 {resource.risk_count}</span>
        <span>P1/P2 {resource.p1_count}/{resource.p2_count}</span>
      </div>
      <div className="resource-card-coverage"><span>覆盖率 {coverage}</span><small>{coverageDetail}</small></div>
      <div className="resource-card-footer">
        <span>{resource.last_inspection_at ? '最近已巡检' : '尚未巡检'}</span>
        <Link to={`/resources/${resourceCodeToSlug(resource.code)}`}>查看详情 →</Link>
      </div>
    </article>
  )
}
