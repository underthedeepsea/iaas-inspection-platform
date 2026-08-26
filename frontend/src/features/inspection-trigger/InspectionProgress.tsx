import type { InspectionRunEvent } from '../../api/inspections'

import { useInspectionRunStream } from './useInspectionRunStream'

export type InspectionProgressStep =
  | 'scope'
  | 'assets'
  | 'items'
  | 'risk-correlation'
  | 'ai'
  | 'summary'
  | 'completed'
  | 'failed'

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

const stepIndexByEventType: Record<string, number> = {
  'scope.resolved': 0,
  'assets.discovered': 1,
  'inspection.item.started': 2,
  'inspection.item.progress': 2,
  'inspection.item.completed': 2,
  'inspection.item.failed': 2,
  'risk.correlation.started': 3,
  'risk.correlation.completed': 3,
  'ai.admission.started': 4,
  'ai.admission.completed': 4,
  'summary.started': 5,
  'summary.completed': 5,
}

function getActiveStep(state: InspectionProgressState) {
  if (state.currentStep === 'failed') {
    const lastVisibleStep = [...state.events]
      .reverse()
      .map((event) => stepIndexByEventType[event.event_type])
      .find((index) => index !== undefined)
    return lastVisibleStep ?? 0
  }
  return {
    scope: 0,
    assets: 1,
    items: 2,
    'risk-correlation': 3,
    ai: 4,
    summary: 5,
    completed: 6,
    failed: 0,
  }[state.currentStep]
}

export function reduceInspectionRunEvent(
  state: InspectionProgressState,
  event: InspectionRunEvent,
): InspectionProgressState {
  if (state.events.some((existing) => existing.sequence === event.sequence)) return state
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
  if (event.event_type === 'inspection.item.started' || event.event_type === 'inspection.item.progress' || event.event_type === 'inspection.item.completed' || event.event_type === 'inspection.item.failed') currentStep = 'items'
  if (event.event_type === 'inspection.item.completed' || event.event_type === 'inspection.item.failed') {
    currentStep = 'items'
    completedItems = Math.max(completedItems, Number(payload.completed_items ?? state.completedItems + 1))
  }
  if (event.event_type === 'risk.correlation.started' || event.event_type === 'risk.correlation.completed') currentStep = 'risk-correlation'
  if (event.event_type === 'ai.admission.started' || event.event_type === 'ai.admission.completed') currentStep = 'ai'
  if (event.event_type === 'summary.started' || event.event_type === 'summary.completed') currentStep = 'summary'
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
  const statusLabel = state.currentStep === 'completed'
    ? '巡检已完成'
    : state.currentStep === 'failed'
      ? '巡检失败'
      : '巡检执行中'
  const activeStep = getActiveStep(state)
  const progress = state.currentStep === 'completed'
    ? 100
    : activeStep <= 2 && state.totalAssets > 0
      ? Math.min(99, Math.round((state.completedAssets / state.totalAssets) * 100))
      : Math.round((activeStep / 5) * 100)
  const steps = [
    { label: '解析资源范围', detail: '确认本次巡检的资源类型与巡检项' },
    { label: '发现资源对象', detail: '读取环境中的资源对象清单' },
    { label: '执行巡检项', detail: '按资源类型执行规则检查' },
    { label: '风险关联', detail: '归并检查结果并计算风险等级' },
    { label: 'AI 补充研判', detail: '对重点风险进行证据补充' },
    { label: '生成摘要', detail: '形成可追溯的巡检结果摘要' },
  ]
  return (
    <section aria-label="巡检进度" className="inspection-progress">
      <div className="progress-heading">
        <div>
          <span className="eyebrow">RUN PROGRESS</span>
          <h3>{statusLabel}</h3>
        </div>
        <strong>{progress}%</strong>
      </div>
      <div aria-label="巡检完成度" className="progress-track">
        <i style={{ width: `${progress}%` }} />
      </div>
      <div className="progress-counts">
        <span>{state.completedAssets} / {state.totalAssets} 个资源对象</span>
        {state.totalItems ? <span>{state.completedItems} / {state.totalItems} 个巡检项</span> : null}
      </div>
      {state.recovering ? <p className="progress-recovering" role="status">正在恢复巡检状态…</p> : null}
      <ol className="inspection-timeline">
        {steps.map((step, index) => {
          const status = state.currentStep === 'failed' && index === activeStep
            ? 'failed'
            : index < activeStep || state.currentStep === 'completed'
              ? 'completed'
              : index === activeStep
                ? 'current'
                : 'pending'
          return (
            <li className={`inspection-timeline-item is-${status}`} key={step.label}>
              <span className="inspection-timeline-marker" aria-hidden="true">{status === 'completed' ? '✓' : index + 1}</span>
              <span className="inspection-timeline-copy"><strong>{step.label}</strong><small>{step.detail}</small></span>
            </li>
          )
        })}
      </ol>
      <details className="disclosure">
        <summary>查看事件流（{state.events.length}）</summary>
        <ol className="inspection-event-list">
          {state.events.map((event) => <li key={event.sequence}>{event.event_type}</li>)}
        </ol>
      </details>
    </section>
  )
}
