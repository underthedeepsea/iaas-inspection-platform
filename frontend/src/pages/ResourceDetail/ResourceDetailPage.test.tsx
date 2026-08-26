import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { ResourceDetailPage } from './ResourceDetailPage'

afterEach(() => vi.restoreAllMocks())

it('restores the history tab from the URL after refresh', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: { items: [], page: 1, page_size: 20, total: 0 },
  } as never)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/resources/llm-runtime?tab=history']}>
        <Routes>
          <Route element={<ResourceDetailPage environmentId="env-1" />} path="/resources/:resourceType" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )

  expect(screen.getByRole('tab', { name: '巡检历史' })).toHaveAttribute('aria-selected', 'true')
  expect(await screen.findByText('暂无巡检历史')).toBeInTheDocument()
})

it('uses the document visual hierarchy for a resource overview', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: {
      resource_type: {
        code: 'LLM_RUNTIME',
        name: '大模型运行时',
        description: '模型服务资源',
        icon: 'llm',
        asset_count: 24,
        inspection_item_count: 6,
        health_score: 92,
        risk_count: 1,
        p1_count: 0,
        p2_count: 1,
        last_inspection_at: '2026-08-25T10:00:00Z',
      },
      latest: {
        health_score: 92,
        coverage_rate: 1,
        risk_count: 1,
        p1_count: 0,
        p2_count: 1,
        inspection_item_count: 6,
      },
      health_trend: [],
    },
  } as never)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/resources/llm-runtime']}>
        <Routes>
          <Route element={<ResourceDetailPage environmentId="env-1" />} path="/resources/:resourceType" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )

  expect(await screen.findByRole('heading', { name: '大模型运行时' })).toBeInTheDocument()
  expect(screen.getByText('巡检覆盖率')).toBeInTheDocument()
  expect(screen.getAllByText('当前风险').length).toBeGreaterThan(1)
  expect(screen.getByText('健康趋势')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: '概览' })).toHaveAttribute('aria-selected', 'true')
})
