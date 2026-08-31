import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { AIAnalysisPanel } from './AIAnalysisPanel'

class FakeEventSource {
  static instance: FakeEventSource
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  close = vi.fn()
  constructor(public url: string) {
    FakeEventSource.instance = this
  }
  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener as (event: MessageEvent<string>) => void)
  }
  emit(type: string, payload: Record<string, unknown>, sequence: number, status: string) {
    this.listeners.get(type)?.(new MessageEvent(type, {
      data: JSON.stringify({ sequence, event_type: type, status, payload }),
      lastEventId: String(sequence),
    }))
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('renders investigation timeline, partial failure, evidence and final conclusion', async () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: {
      id: 'investigation-1',
      investigation_id: 'investigation-1',
      status: 'RESOLVED',
      conclusion: '大模型运行时健康稳定，建议继续观察风险趋势。',
      confidence: 0.8,
      result: {
        comparisons: [{ metric: 'health', current: 92, previous: 86 }],
        root_cause_candidates: [{ title: '调度压力', confidence: 0.78 }],
        priority_actions: [{ priority: 'P1', action: '扩容调度器' }],
        evidence_gaps: ['变更负责人'],
      },
    },
  } as never)

  render(
    <AIAnalysisPanel
      contextType="RESOURCE_RUN"
      environmentId="env-1"
      inspectionRunId="run-1"
      initialInvestigationId="investigation-1"
      resourceCode="LLM_RUNTIME"
    />,
  )

  expect(screen.getByRole('region', { name: 'AI 分析面板' })).toHaveClass('ai-analysis-panel')

  await waitFor(() => expect(FakeEventSource.instance.listeners.size).toBeGreaterThan(0))
  await act(async () => {
    FakeEventSource.instance.emit('context.ready', {}, 1, 'COMPLETED')
    FakeEventSource.instance.emit('history.loaded', {}, 2, 'COMPLETED')
    FakeEventSource.instance.emit('tool.started', { tool: 'summary' }, 3, 'STARTED')
    FakeEventSource.instance.emit('tool.completed', { tool: 'summary' }, 4, 'COMPLETED')
    FakeEventSource.instance.emit('evidence.created', {
      evidence_key: 'queue.depth:1',
      evidence_type: 'METRIC',
      source: 'scheduler.metrics',
      value: { last: 90 },
      summary: '队列深度连续升高',
      confidence: 0.93,
    }, 5, 'COMPLETED')
    FakeEventSource.instance.emit('tool.failed', { tool: 'change_history' }, 6, 'FAILED')
    FakeEventSource.instance.emit('analysis.completed', { summary: '基于成功工具完成分析。' }, 7, 'COMPLETED')
  })

  expect(screen.getByText('上下文已准备')).toBeInTheDocument()
  expect(screen.getByText('历史数据已加载')).toBeInTheDocument()
  expect(screen.getByText(/部分证据工具失败/)).toBeInTheDocument()
    expect(screen.getByText('可用证据')).toBeInTheDocument()
    expect(screen.getByText('METRIC · queue.depth:1')).toBeInTheDocument()
    expect(screen.getByText('相比上一轮')).toBeInTheDocument()
    expect(screen.getByText('调度压力')).toBeInTheDocument()
    expect(screen.getByText(/扩容调度器/)).toBeInTheDocument()
    expect(screen.getByText('变更负责人')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText('大模型运行时健康稳定，建议继续观察风险趋势。')).toBeInTheDocument())
})

it('refreshes persisted investigation state after a terminal stream event', async () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  let detailCalls = 0
  const get = vi.spyOn(apiClient, 'get').mockImplementation(async (url) => {
    if (String(url).endsWith('/events')) return { data: { items: [] } } as never
    detailCalls += 1
    return {
      data: detailCalls === 1
        ? {
            id: 'investigation-2',
            investigation_id: 'investigation-2',
            status: 'RUNNING',
            conclusion: '',
            result: {},
          }
        : {
            id: 'investigation-2',
            investigation_id: 'investigation-2',
            status: 'RESOLVED',
            conclusion: '持久化后的完整结论',
            confidence: 0.94,
            result: {
              comparisons: [{ metric: 'health_score', current: 88, previous: 76 }],
              root_cause_candidates: [{ title: '调度器压力' }],
              priority_actions: [{ priority: 'P2', action: '复核队列与调度策略' }],
              evidence_gaps: [],
            },
          },
    } as never
  })

  render(
    <AIAnalysisPanel
      contextType="RESOURCE_RUN"
      environmentId="env-1"
      inspectionRunId="run-2"
      initialInvestigationId="investigation-2"
      resourceCode="LLM_RUNTIME"
    />,
  )

  await waitFor(() => expect(FakeEventSource.instance.listeners.size).toBeGreaterThan(0))
  await act(async () => {
    FakeEventSource.instance.emit('analysis.completed', {
      summary: '事件结论',
      confidence: 0.94,
      status: 'RESOLVED',
    }, 1, 'COMPLETED')
  })

  await waitFor(() => expect(screen.getByText('持久化后的完整结论')).toBeInTheDocument())
  expect(detailCalls).toBeGreaterThanOrEqual(2)
  expect(get).toHaveBeenCalledWith('/investigations/investigation-2')
  expect(screen.getByText('RESOLVED')).toBeInTheDocument()
})

it('handles conversational follow-up terminal events without reconnecting', async () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.spyOn(apiClient, 'get').mockImplementation(async (url) => {
    if (String(url).endsWith('/events')) return { data: { items: [] } } as never
    return {
      data: {
        id: 'investigation-3',
        investigation_id: 'investigation-3',
        status: 'RUNNING',
        result: {},
      },
    } as never
  })

  render(
    <AIAnalysisPanel
      contextType="RESOURCE_RUN"
      environmentId="env-1"
      inspectionRunId="run-3"
      initialInvestigationId="investigation-3"
      resourceCode="LLM_RUNTIME"
    />,
  )

  await waitFor(() => expect(FakeEventSource.instance.listeners.size).toBeGreaterThan(0))
  await act(async () => {
    FakeEventSource.instance.emit('turn.completed', {
      status: 'RESOLVED',
      summary: '追问已完成',
    }, 1, 'COMPLETED')
  })

  expect(screen.getAllByText('追问已完成')).toHaveLength(2)
  expect(FakeEventSource.instance.close).toHaveBeenCalled()
})
