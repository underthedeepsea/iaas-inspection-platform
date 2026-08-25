import type { ResourceType } from '../../api/resources'

export function ResourceTypeCard({
  resource,
  selected,
  onToggle,
}: {
  resource: ResourceType
  selected: boolean
  onToggle: () => void
}) {
  return (
    <button
      aria-pressed={selected}
      onClick={onToggle}
      style={{
        background: selected ? '#fff7ed' : '#ffffff',
        border: `1px solid ${selected ? '#f97316' : '#e5e7eb'}`,
        borderRadius: 12,
        color: '#111827',
        cursor: 'pointer',
        padding: 14,
        textAlign: 'left',
      }}
      type="button"
    >
      <span style={{ display: 'block', fontWeight: 650 }}>{resource.name}</span>
      <span style={{ color: '#6b7280', display: 'block', fontSize: 12, marginTop: 6 }}>
        {resource.asset_count} 个对象 · {resource.inspection_item_count} 个巡检项
      </span>
      <span style={{ color: selected ? '#c2410c' : '#9ca3af', display: 'block', fontSize: 12, marginTop: 8 }}>
        {selected ? '已选择' : '点击选择'}
      </span>
    </button>
  )
}

