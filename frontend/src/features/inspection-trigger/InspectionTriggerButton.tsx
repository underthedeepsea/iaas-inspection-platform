import { useInspectionSessionStore } from '../../stores/inspectionSessionStore'
import type { ResourceType } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'

import { InspectionDrawer } from './InspectionDrawer'

export function InspectionTriggerButton({
  environmentId,
  environmentName,
  resourceTypes,
}: {
  environmentId: string
  environmentName?: string
  resourceTypes: ResourceType[]
}) {
  const selectedEnvironmentName = useUiStore(state => state.environmentName)
  const active = useInspectionSessionStore(state => state.active)
  const current = active?.environmentId === environmentId ? active : null
  const open = useUiStore((state) => state.inspectionDrawerOpen)
  const setOpen = useUiStore((state) => state.setInspectionDrawerOpen)
  return (
    <>
      <button className="button button-primary" onClick={() => setOpen(true)} type="button">{current ? current.status === 'RUNNING' ? '查看正在进行的巡检' : '查看巡检完成摘要' : '立即巡检'}</button>
      <InspectionDrawer
        environmentId={environmentId}
        environmentName={environmentName ?? selectedEnvironmentName}
        onClose={() => setOpen(false)}
        open={open}
        resourceTypes={resourceTypes}
      />
    </>
  )
}
