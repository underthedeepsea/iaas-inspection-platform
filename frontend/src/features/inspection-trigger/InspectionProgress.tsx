import { useEffect, useRef } from 'react'
import type { TerminalStatus } from '../../stores/inspectionSessionStore'
import { Progress } from 'antd'
import type { InspectionRunEvent } from '../../api/inspections'

import { useInspectionRunStream } from './useInspectionRunStream'

export type InspectionProgressStep =
  | 'scope'
  | 'assets'
  | 'items'
  | 'risk-correlation'
  | 'summary'
  | 'completed'
  | 'failed'

export interface InspectionProgressState {
  currentStep: InspectionProgressStep
  runStatus: string | null
  totalAssets: number
  completedAssets: number
  totalItems: number
  completedItems: number
  progress: number
  lastEventId: number
  events: InspectionRunEvent[]
}

export const initialInspectionProgressState: InspectionProgressState = {
  currentStep: 'scope',
  runStatus: null,
  totalAssets: 0,
  completedAssets: 0,
  totalItems: 0,
  completedItems: 0,
  progress: 0,
  lastEventId: 0,
  events: [],
}

const stepIndexByEventType: Record<string, number> = {
  'scope.resolved': 0,
  'assets.discovered': 1,
  'inspection.started': 2,
  'inspection.item.started': 2,
  'inspection.item.progress': 2,
  'inspection.item.completed': 2,
  'inspection.item.failed': 2,
  'inspection.completed': 2,
  'risk.correlation.started': 3,
  'risk.correlation.completed': 3,
  'summary.started': 5,
  'summary.completed': 5,
}

const stepIndexByStep: Record<InspectionProgressStep, number> = {
  scope: 0,
  assets: 1,
  items: 2,
  'risk-correlation': 3,
  summary: 5,
  completed: 6,
  failed: -1,
}

function eventProgress(state: InspectionProgressState, event: InspectionRunEvent, totalItems: number, completedItems: number) {
  switch (event.event_type) {
    case 'scope.resolved':
      return 5
    case 'assets.discovered':
      return 15
    case 'inspection.started':
    case 'inspection.item.started':
    case 'inspection.item.progress':
      return 15 + (totalItems ? (55 * completedItems) / totalItems : 0)
    case 'inspection.item.completed':
    case 'inspection.item.failed':
      return 15 + (totalItems ? (55 * completedItems) / totalItems : 0)
    case 'inspection.completed':
      return 70
    case 'risk.correlation.started':
      return 70
    case 'risk.correlation.completed':
      return 80
    case 'summary.started':
      return 90
    case 'summary.completed':
    case 'run.completed':
      return 100
    default:
      return state.progress
  }
}

function getActiveStep(state: InspectionProgressState) {
  const indices = { scope: 0, assets: 0, items: 1, 'risk-correlation': 2, summary: 3, completed: 4, failed: 0 }
  if (state.currentStep !== 'failed') return indices[state.currentStep]
  const last = [...state.events].reverse().find(event => stepIndexByEventType[event.event_type] !== undefined)
  const index = last ? stepIndexByEventType[last.event_type] : 0
  return index <= 1 ? 0 : index === 2 ? 1 : index === 3 ? 2 : 3
}

export function reduceInspectionRunEvent(
  state: InspectionProgressState,
  event: InspectionRunEvent,
): InspectionProgressState {
  if (state.events.some((existing) => existing.sequence === event.sequence) || state.currentStep === 'completed' || state.currentStep === 'failed') return state
  const payload = event.payload ?? {}
  const totalAssets = Math.max(state.totalAssets, Number(payload.asset_count ?? state.totalAssets) || 0)
  const totalItems = Math.max(state.totalItems, Number(payload.total_items ?? payload.inspection_item_count ?? state.totalItems) || 0)
  const completedAssets = Number(
    payload.completed_asset_count ?? payload.assets_covered ?? state.completedAssets,
  )
  let currentStep: InspectionProgressStep = state.currentStep
  let runStatus = state.runStatus
  let completedItems = state.completedItems
  if (event.event_type === 'scope.resolved' && stepIndexByStep[state.currentStep] <= 0) currentStep = 'scope'
  if (event.event_type === 'assets.discovered' && stepIndexByStep[state.currentStep] <= 1) currentStep = 'assets'
  if (event.event_type === 'inspection.started' || event.event_type === 'inspection.item.started' || event.event_type === 'inspection.item.progress' || event.event_type === 'inspection.item.completed' || event.event_type === 'inspection.item.failed' || event.event_type === 'inspection.completed') {
    if (stepIndexByStep[state.currentStep] <= 2) currentStep = 'items'
  }
  if (event.event_type === 'inspection.item.completed' || event.event_type === 'inspection.item.failed') {
    completedItems = Math.max(completedItems, Number(payload.completed_items ?? state.completedItems + 1))
  }
  if (event.event_type === 'risk.correlation.started' || event.event_type === 'risk.correlation.completed') {
    if (stepIndexByStep[state.currentStep] <= 3) currentStep = 'risk-correlation'
  }
  if (event.event_type === 'summary.started' || event.event_type === 'summary.completed') {
    if (stepIndexByStep[state.currentStep] <= 5) currentStep = 'summary'
  }
  if (event.event_type === 'run.completed') {
    currentStep = 'completed'
    runStatus = String(payload.status ?? event.status)
  }
  if (event.event_type === 'run.failed') {
    currentStep = 'failed'
    runStatus = 'FAILED'
  }
  const nextProgress = Math.min(100, Math.max(state.progress, eventProgress(state, event, totalItems, completedItems)))
  return {
    ...state,
    currentStep,
    runStatus,
    totalAssets,
    completedAssets: Math.max(state.completedAssets, completedAssets),
    totalItems,
    completedItems,
    progress: nextProgress,
    lastEventId: Math.max(state.lastEventId, event.sequence),
    events: [...state.events, event].sort((left, right) => left.sequence - right.sequence),
  }
}

export function progressForInspectionState(state: InspectionProgressState) {
  return state.progress
}

export function InspectionProgress({ runId, onTerminal }: { runId: string; onTerminal?: (result: { runId: string; status: TerminalStatus }) => void }) {
  const state = useInspectionRunStream(runId)
  const notified = useRef('')
  useEffect(() => {
    if (state.currentStep !== 'completed' && state.currentStep !== 'failed') return
    if (notified.current === runId || !onTerminal) return
    const status = state.runStatus === 'PARTIAL' ? 'PARTIAL' : state.runStatus === 'FAILED' ? 'FAILED' : 'SUCCEEDED'
    notified.current = runId
    onTerminal({ runId, status })
  }, [runId, state.currentStep, state.runStatus, onTerminal])
  const statusLabel = state.currentStep === 'completed'
    ? state.runStatus === 'PARTIAL' ? '巡检部分完成' : '巡检已完成'
    : state.currentStep === 'failed'
      ? '巡检失败'
      : '巡检执行中'
  const activeStep = getActiveStep(state)
  const progress = progressForInspectionState(state)
  const steps = [
    { label: '确认资源范围', detail: '冻结本次资源对象与巡检项' },
    { label: '执行代码插件', detail: '按资源类型执行规则检查' },
    { label: '关联风险', detail: '归并检查结果并计算风险等级' },
    { label: '生成巡检摘要', detail: '形成可追溯的巡检结果摘要' },
  ]
  return (
    <section aria-label="巡检进度" className="inspection-progress">
      <div className="progress-heading">
        <div>
          <span className="eyebrow">RUN PROGRESS</span>
          <h3>{statusLabel}</h3>
        </div>
        <strong>{Math.round(progress)}%</strong>
      </div>
      <Progress aria-label="巡检完成度" percent={progress} showInfo={false} />
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
          {state.events.filter(event => !event.event_type.startsWith('ai.admission.')).map((event) => <li key={event.sequence}>{event.event_type}</li>)}
        </ol>
      </details>
    </section>
  )
}
