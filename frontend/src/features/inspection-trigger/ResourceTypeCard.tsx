import { Card } from 'antd'
import type { ResourceType } from '../../api/resources'
import { isResourceInspectable } from '../resource-health/resourceRoutes'

const tagsByCode: Record<string, string[]> = {
  GPU_POOL: ['条件基线', 'GPU 事件', '持续退化', '处置复验'],
  HOST: ['CPU / 内存', '文件系统', 'IO 趋势', '组件证据'],
  LLM_RUNTIME: ['推理性能', '固定阈值', '动态基线', '趋势'],
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
  const tags = resource.code === 'K8S_CLUSTER' && resource.release_state === 'READY' ? ['已接入正式插件'] : resource.code === 'K8S_CLUSTER' && !resource.release_state && resource.inspection_item_count > 0 ? ['巡检项已配置'] : tagsByCode[resource.code] ?? ['未接入正式插件']
  const available = isResourceInspectable(resource)
  return (
    <Card className="inspection-resource-card-shell" bordered={false} styles={{ body: { padding: 0 } }}>
      <button aria-checked={selected} aria-pressed={selected} className={`inspection-resource-card${selected ? ' is-selected' : ''}`} disabled={!available} onClick={onToggle} type="button">
      <span className="inspection-resource-title"><span className="check-mark" aria-hidden="true">{selected ? '✓' : ''}</span><strong>{resource.name}</strong></span>
      <span className="inspection-resource-count">{resource.asset_count} 个对象 · {resource.inspection_item_count} 个巡检项</span>
      <span className="inspection-resource-tags">{tags.map((tag) => <span key={tag}>{tag}</span>)}</span>
      <span className="inspection-resource-state">{available ? selected ? '已选择' : '点击选择' : '暂无可用巡检插件'}</span>
      </button>
    </Card>
  )
}
