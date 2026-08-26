import type { ResourceType } from '../../api/resources'

import { ResourceTypeCard } from './ResourceTypeCard'

export function ResourceTypeSelector({
  resources,
  selectedCodes,
  onToggle,
}: {
  resources: ResourceType[]
  selectedCodes: string[]
  onToggle: (code: string) => void
}) {
  const selected = new Set(selectedCodes)
  return <div className="inspection-resource-grid">{resources.map((resource) => <ResourceTypeCard key={resource.code} onToggle={() => onToggle(resource.code)} resource={resource} selected={selected.has(resource.code)} />)}</div>
}
