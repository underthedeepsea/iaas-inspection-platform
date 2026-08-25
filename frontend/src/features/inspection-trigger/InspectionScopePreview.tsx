import type { ResourceType } from '../../api/resources'

export function InspectionScopePreview({
  resources,
  selectedCodes,
}: {
  resources: ResourceType[]
  selectedCodes: string[]
}) {
  const selected = new Set(selectedCodes)
  const assetCount = resources
    .filter((resource) => selected.has(resource.code))
    .reduce((sum, resource) => sum + resource.asset_count, 0)
  const itemCount = resources
    .filter((resource) => selected.has(resource.code))
    .reduce((sum, resource) => sum + resource.inspection_item_count, 0)
  return (
    <div aria-label="巡检范围预览" style={{ background: '#f8fafc', borderRadius: 10, color: '#4b5563', padding: 12 }}>
      范围预览：{assetCount} 个资源对象 / {itemCount} 个巡检项
    </div>
  )
}

