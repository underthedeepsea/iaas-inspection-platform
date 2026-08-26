import type { ResourceType } from '../../api/resources'
import { useUiStore } from '../../stores/uiStore'

import { InspectionDrawer } from './InspectionDrawer'

export function InspectionTriggerButton({
  environmentId,
  resourceTypes,
}: {
  environmentId: string
  resourceTypes: ResourceType[]
}) {
  const open = useUiStore((state) => state.inspectionDrawerOpen)
  const setOpen = useUiStore((state) => state.setInspectionDrawerOpen)
  return (
    <>
      <button className="button button-primary" onClick={() => setOpen(true)} type="button">立即巡检</button>
      <InspectionDrawer
        environmentId={environmentId}
        onClose={() => setOpen(false)}
        open={open}
        resourceTypes={resourceTypes}
      />
    </>
  )
}
