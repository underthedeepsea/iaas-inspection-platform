import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { InspectionRunEvent } from '../../api/inspections'
import {
  initialInspectionProgressState,
  reduceInspectionRunEvent,
  InspectionProgress,
} from './InspectionProgress'

const events: InspectionRunEvent[] = [
  { sequence: 1, event_type: 'scope.resolved', status: 'PENDING', payload: { asset_count: 4, inspection_item_count: 2 } },
  { sequence: 2, event_type: 'assets.discovered', status: 'PENDING', payload: { asset_count: 4 } },
  { sequence: 3, event_type: 'inspection.item.started', status: 'RUNNING', payload: {} },
  { sequence: 4, event_type: 'inspection.item.progress', status: 'RUNNING', payload: { completed_asset_count: 3 } },
]

class FakeEventSource {
  static instance: FakeEventSource
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  url: string
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    FakeEventSource.instance = this
  }
  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener as (event: MessageEvent<string>) => void)
  }
  emit(type: string, event: InspectionRunEvent) {
    this.listeners.get(type)?.(new MessageEvent(type, {
      data: JSON.stringify(event),
      lastEventId: String(event.sequence),
    }))
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('InspectionProgress', () => {
  it('reduces ordered scope and progress events into the current step', () => {
    const state = events.reduce(reduceInspectionRunEvent, initialInspectionProgressState)

    expect(state.currentStep).toBe('items')
    expect(state.totalAssets).toBe(4)
    expect(state.completedAssets).toBe(3)
  })

  it('maps the canonical backend stage events to every visible progress step', () => {
    const stageEvents: Array<[string, import('../../api/inspections').InspectionRunEvent]> = [
      ['risk-correlation', { sequence: 5, event_type: 'risk.correlation.started', status: 'RUNNING', payload: {} }],
      ['ai', { sequence: 6, event_type: 'ai.admission.started', status: 'RUNNING', payload: {} }],
      ['summary', { sequence: 7, event_type: 'summary.started', status: 'RUNNING', payload: {} }],
    ]

    for (const [step, event] of stageEvents) {
      const state = events.reduce(reduceInspectionRunEvent, initialInspectionProgressState)
      expect(reduceInspectionRunEvent(state, event).currentStep).toBe(step)
    }
  })

  it('continues an existing run from SSE events without creating a new run', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <InspectionProgress runId="run-1" />
      </QueryClientProvider>,
    )

    for (const event of events) FakeEventSource.instance.emit(event.event_type, event)
    FakeEventSource.instance.emit('run.completed', {
      sequence: 5,
      event_type: 'run.completed',
      status: 'SUCCEEDED',
      payload: { completed_asset_count: 4 },
    })

    await waitFor(() => expect(screen.getByText('巡检已完成')).toBeInTheDocument())
    expect(screen.getByText('4 / 4 个资源对象')).toBeInTheDocument()
    expect(screen.getByLabelText('巡检进度')).toHaveClass('inspection-progress')
    expect(screen.getByText('解析资源范围')).toBeInTheDocument()
    expect(FakeEventSource.instance.url).toContain('/inspection-runs/run-1/events')
  })

  it('marks the stage that failed instead of resetting the timeline to the first stage', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <InspectionProgress runId="run-2" />
      </QueryClientProvider>,
    )

    FakeEventSource.instance.emit('summary.started', {
      sequence: 1,
      event_type: 'summary.started',
      status: 'RUNNING',
      payload: {},
    })
    FakeEventSource.instance.emit('run.failed', {
      sequence: 2,
      event_type: 'run.failed',
      status: 'FAILED',
      payload: { error_message: 'summary failed' },
    })

    await waitFor(() => expect(screen.getByText('巡检失败')).toBeInTheDocument())
    expect(screen.getByText('生成摘要').closest('li')).toHaveClass('is-failed')
  })
})
