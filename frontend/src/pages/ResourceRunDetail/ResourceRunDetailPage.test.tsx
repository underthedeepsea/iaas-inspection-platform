import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { ResourceRunDetailPage } from './ResourceRunDetailPage'

afterEach(() => vi.restoreAllMocks())

describe('ResourceRunDetailPage', () => {
  it('shows the run summary and evidence entry points in the document layout', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        resource_type: 'LLM_RUNTIME',
        run: { id: 'run-1', status: 'SUCCEEDED', run_date: '2026-08-25', started_at: null, finished_at: null },
        coverage: { assets_total: 1, assets_covered: 1, rate: 1 },
        inspection_item_status_counts: { SUCCEEDED: 1 },
        inspection_item_count: 1,
        finding_count: 1,
        risk_count: 1,
        severity_counts: { P1: 0, P2: 1 },
        ai_dependent_cases: 0,
        ai_investigation_count: 0,
        major_risks: [{ id: 'risk-1', title: '调度压力', severity: 'P1', conclusion: '需要关注' }],
        summary: {},
      },
    } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/resources/llm-runtime/runs/run-1']}>
          <Routes><Route element={<ResourceRunDetailPage environmentId="env-1" />} path="/resources/:resourceType/runs/:runId" /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: /2026-08-25/ })).toBeInTheDocument()
    expect(screen.getByText('覆盖率')).toBeInTheDocument()
    expect(screen.getByText('主要风险')).toBeInTheDocument()
    expect(screen.getByText('P1')).toHaveClass('severity-p1')
    expect(screen.getByRole('region', { name: 'AI 分析面板' })).toBeInTheDocument()
  })
})
