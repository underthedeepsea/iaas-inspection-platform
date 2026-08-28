import { Card } from 'antd'
import type { ResourceType } from '../../api/resources'

const tagsByCode: Record<string, string[]> = {
  CONTROL_PLANE: ['反亲和', '冗余度', '容量'],
  KVM_CLUSTER: ['容量', '健康度', '超分'],
  K8S_CLUSTER: ['组件容量', '调度', '告警'],
  LLM_RUNTIME: ['性能', 'GPU', '调度', '容量'],
  GPU_POOL: ['ECC', '利用率', '健康度'],
  HOST: ['基础服务', '内核参数', '容量'],
}

export function ResourceTypeCard({
  resource,
  selected,
  onToggle,
}: {
  resource: ResourceType
  selected: boolean
  onToggle: () => void
}) {
  const tags = tagsByCode[resource.code] ?? ['健康度', '容量']
  return (
    <Card className="inspection-resource-card-shell" bordered={false} styles={{ body: { padding: 0 } }}>
      <button aria-checked={selected} aria-pressed={selected} className={`inspection-resource-card${selected ? ' is-selected' : ''}`} onClick={onToggle} type="button">
      <span className="inspection-resource-title"><span className="check-mark" aria-hidden="true">{selected ? '✓' : ''}</span><strong>{resource.name}</strong></span>
      <span className="inspection-resource-count">{resource.asset_count} 个对象 · {resource.inspection_item_count} 个巡检项</span>
      <span className="inspection-resource-tags">{tags.map((tag) => <span key={tag}>{tag}</span>)}</span>
      <span className="inspection-resource-state">{selected ? '已选择' : '点击选择'}</span>
      </button>
    </Card>
  )
}
