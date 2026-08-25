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

  await waitFor(() => expect(FakeEventSource.instance.listeners.size).toBeGreaterThan(0))
  await act(async () => {
    FakeEventSource.instance.emit('context.ready', {}, 1, 'COMPLETED')
    FakeEventSource.instance.emit('history.loaded', {}, 2, 'COMPLETED')
    FakeEventSource.instance.emit('tool.started', { tool: 'summary' }, 3, 'STARTED')
    FakeEventSource.instance.emit('tool.completed', { tool: 'summary' }, 4, 'COMPLETED')
    FakeEventSource.instance.emit('tool.failed', { tool: 'change_history' }, 5, 'FAILED')
    FakeEventSource.instance.emit('analysis.completed', { summary: '基于成功工具完成分析。' }, 6, 'COMPLETED')
  })

  expect(screen.getByText('上下文已准备')).toBeInTheDocument()
  expect(screen.getByText('历史数据已加载')).toBeInTheDocument()
  expect(screen.getByText(/部分证据工具失败/)).toBeInTheDocument()
  expect(screen.getByText('可用证据')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText('大模型运行时健康稳定，建议继续观察风险趋势。')).toBeInTheDocument())
})
