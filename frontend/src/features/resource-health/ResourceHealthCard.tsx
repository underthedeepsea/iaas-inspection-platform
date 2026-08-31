import { Card, Tag } from 'antd'
import { Link } from 'react-router-dom'

import type { ResourceType } from '../../api/resources'
import { resourceCodeToSlug } from './resourceRoutes'

type ResourceVisual = {
  short: string
  label: string
  className: string
}

const RESOURCE_VISUALS: Record<string, ResourceVisual> = {
  CONTROL_PLANE: { short: 'CP', label: 'CONTROL PLANE', className: 'resource-tone-control' },
  KVM_CLUSTER: { short: 'KVM', label: 'VIRTUALIZATION', className: 'resource-tone-kvm' },
  K8S_CLUSTER: { short: 'K8S', label: 'ORCHESTRATION', className: 'resource-tone-k8s' },
  LLM_RUNTIME: { short: 'LLM', label: 'INFERENCE', className: 'resource-tone-llm' },
  GPU_POOL: { short: 'GPU', label: 'ACCELERATOR', className: 'resource-tone-gpu' },
  HOST: { short: 'HOST', label: 'COMPUTE', className: 'resource-tone-host' },
}

function resourceVisual(code: string): ResourceVisual {
  const normalizedCode = code.toUpperCase()
  return RESOURCE_VISUALS[normalizedCode] ?? {
    short: normalizedCode.slice(0, 4),
    label: normalizedCode.replaceAll('_', ' '),
    className: 'resource-tone-default',
  }
}

export function ResourceHealthCard({ resource }: { resource: ResourceType }) {
  const visual = resourceVisual(resource.code)
  const health = resource.health_score == null ? '—' : String(Math.round(resource.health_score))
  const severity = resource.p1_count ? 'P1' : resource.p2_count ? 'P2' : resource.risk_count ? 'P3' : '正常'
  const coverage = resource.coverage_rate == null ? '—' : `${Math.round(resource.coverage_rate * 100)}%`
  const coverageDetail = resource.assets_covered == null || resource.assets_total == null
    ? '等待本轮快照'
    : `${resource.assets_covered} / ${resource.assets_total} 个对象`

  return (
    <Card className={`panel resource-card ${visual.className}`} bordered={false} styles={{ body: { padding: 0 } }}>
      <div className="resource-card-header">
        <div className="resource-card-identity">
          <span aria-hidden="true" className="resource-card-glyph">{visual.short}</span>
          <Link to={`/resources/${resourceCodeToSlug(resource.code)}`}>
            <span className="resource-card-type">{visual.label}</span>
            <strong>{resource.name}</strong>
            <small>{resource.description || '资源对象健康状态'}</small>
          </Link>
        </div>
        <Tag className={`severity-badge severity-${severity.toLowerCase()}`} color={severity === 'P1' ? 'red' : severity === 'P2' ? 'orange' : severity === 'P3' ? 'blue' : 'green'}>{severity}</Tag>
      </div>
      <div className="resource-card-health">
        <strong>{health}</strong>
        <span>健康度</span>
      </div>
      {resource.data_state === 'NO_DATA' ? <p className="resource-card-no-data">无可用资源数据</p> : null}
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
    </Card>
  )
}
