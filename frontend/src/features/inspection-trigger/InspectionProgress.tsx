import type { InspectionRunEvent } from '../../api/inspections'

import { useInspectionRunStream } from './useInspectionRunStream'

export type InspectionProgressStep = 'scope' | 'assets' | 'items' | 'completed' | 'failed'

export interface InspectionProgressState {
  currentStep: InspectionProgressStep
  totalAssets: number
  completedAssets: number
  totalItems: number
  completedItems: number
  lastEventId: number
  events: InspectionRunEvent[]
}

export const initialInspectionProgressState: InspectionProgressState = {
  currentStep: 'scope',
  totalAssets: 0,
  completedAssets: 0,
  totalItems: 0,
  completedItems: 0,
  lastEventId: 0,
  events: [],
}

export function reduceInspectionRunEvent(
  state: InspectionProgressState,
  event: InspectionRunEvent,
): InspectionProgressState {
  const payload = event.payload ?? {}
  const totalAssets = Number(payload.asset_count ?? state.totalAssets)
  const totalItems = Number(payload.inspection_item_count ?? state.totalItems)
  const completedAssets = Number(
    payload.completed_asset_count ?? payload.assets_covered ?? state.completedAssets,
  )
  let currentStep = state.currentStep
  let completedItems = state.completedItems
  if (event.event_type === 'scope.resolved') currentStep = 'scope'
  if (event.event_type === 'assets.discovered') currentStep = 'assets'
  if (event.event_type === 'inspection.item.started' || event.event_type === 'inspection.item.progress') currentStep = 'items'
  if (event.event_type === 'inspection.item.completed') {
    currentStep = 'items'
    completedItems += 1
  }
  if (event.event_type === 'run.completed') currentStep = 'completed'
  if (event.event_type === 'run.failed') currentStep = 'failed'
  return {
    ...state,
    currentStep,
    totalAssets,
    completedAssets: Math.max(state.completedAssets, completedAssets),
    totalItems,
    completedItems,
    lastEventId: Math.max(state.lastEventId, event.sequence),
    events: [...state.events, event],
  }
}

export function InspectionProgress({ runId }: { runId: string }) {
  const state = useInspectionRunStream(runId)
  const labels: Record<InspectionProgressStep, string> = {
    scope: '已解析巡检范围',
    assets: '已发现资源对象',
    items: '正在执行巡检项',
    completed: '巡检已完成',
    failed: '巡检失败',
  }
  return (
    <section aria-label="巡检进度" style={{ marginTop: 20 }}>
      <h3>{labels[state.currentStep]}</h3>
      <p style={{ color: '#4b5563' }}>{state.completedAssets} / {state.totalAssets} 个资源对象</p>
      {state.totalItems ? <p style={{ color: '#4b5563' }}>{state.completedItems} / {state.totalItems} 个巡检项</p> : null}
      {state.recovering ? <p role="status">正在恢复巡检状态…</p> : null}
      <ol>
        {state.events.map((event) => <li key={event.sequence}>{event.event_type}</li>)}
      </ol>
    </section>
  )
}

