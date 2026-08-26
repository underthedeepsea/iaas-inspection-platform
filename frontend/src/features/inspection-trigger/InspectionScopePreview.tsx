import type { ResourceType } from '../../api/resources'

export function InspectionScopePreview({ resources, selectedCodes }: { resources: ResourceType[]; selectedCodes: string[] }) {
  const selected = new Set(selectedCodes)
  const chosen = resources.filter((resource) => selected.has(resource.code))
  const assetCount = chosen.reduce((sum, resource) => sum + resource.asset_count, 0)
  const itemCount = chosen.reduce((sum, resource) => sum + resource.inspection_item_count, 0)
  return <div aria-label="巡检范围预览" className="scope-summary"><span className="eyebrow">SELECTED SCOPE</span><strong>范围预览：{assetCount} 个资源对象 / {itemCount} 个巡检项</strong><small>{chosen.length ? `已选择 ${chosen.length} 类资源` : '请选择至少一种资源类型'}</small></div>
}
