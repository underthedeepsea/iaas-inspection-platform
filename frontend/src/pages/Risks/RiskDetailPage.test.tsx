import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { RiskDetailPage } from './RiskDetailPage'

afterEach(() => vi.restoreAllMocks())

describe('RiskDetailPage', () => {
  it('renders the decision, evidence, lifecycle, and action surfaces', async () => {
    vi.spyOn(apiClient, 'get').mockImplementation(async (url) => {
      if (url === '/risks/risk-1') {
        return {
          data: {
            id: 'risk-1', risk_id: 'risk-1', risk_key: 'scheduler.pressure', title: 'Scheduler Queue Pressure',
            domain: 'LLM', severity: 'P2', status: 'PENDING_ACTION', occurrence_count: 3,
            ai_involved: true, first_seen_at: '2026-08-20T08:00:00Z', last_seen_at: '2026-08-25T08:00:00Z',
            current_conclusion: '队列压力正在影响调度延迟。', impact_summary: '部分推理请求可能出现排队。',
            recommendation: '检查调度队列和并发上限。',
            codeization: { execution_mode: 'HYBRID', code_status: 'PARTIAL', code_coverage_percent: 65 },
            recent_investigation: { investigation_id: 'inv-1', status: 'COMPLETED', confidence: 0.88 },
          },
        }
      }
      if (url === '/risks/risk-1/timeline') {
        return { data: { risk_id: 'risk-1', events: [{ id: 'event-1', at: '2026-08-20T08:00:00Z', label: '首次发现', to_status: 'NEW', source: 'SYSTEM', reason: '首次达到阈值' }] } }
      }
      return { data: { risk_id: 'risk-1', items: [{ id: 'evidence-1', evidence_key: 'queue.depth', evidence_type: 'METRIC', summary: '队列深度连续超过阈值。', source: 'scheduler.metrics', confidence: 0.93 }], limit: 50, total: 1 } }
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/risks/risk-1']}>
          <Routes>
            <Route element={<RiskDetailPage />} path="/risks/:riskId" />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: 'Scheduler Queue Pressure' })).toBeInTheDocument()
    expect(screen.getByText('当前判断')).toBeInTheDocument()
    expect(screen.getByText('关键证据')).toBeInTheDocument()
    expect(screen.getByText('风险生命周期')).toBeInTheDocument()
    expect(screen.getByText('队列深度连续超过阈值。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '记录已处理' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '立即复验' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '询问 AI' })).toBeInTheDocument()
  })
})
