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

it('loads and renders real resource risks with severity and detail links', async () => {
  vi.spyOn(apiClient, 'get').mockImplementation(async (url) => {
    if (String(url).includes('/risks')) {
      return {
        data: {
          items: [{
            id: 'risk-1',
            risk_id: 'risk-1',
            title: '调度压力',
            domain: 'LLM',
            severity: 'P1',
            status: 'PENDING_ACTION',
            occurrence_count: 3,
            primary_asset_id: 'asset-1',
            last_seen_at: '2026-08-25T10:00:00Z',
            ai_involved: true,
          }],
          page: 1,
          page_size: 20,
          total: 1,
        },
      } as never
    }
    return {
      data: {
        resource_type: { code: 'LLM_RUNTIME', name: '大模型运行时', description: '模型服务资源', icon: 'llm', asset_count: 1, inspection_item_count: 1, health_score: 92, risk_count: 1, p1_count: 1, p2_count: 0, last_inspection_at: null },
        latest: null,
        health_trend: [],
      },
    } as never
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/resources/llm-runtime?tab=risks']}>
        <Routes>
          <Route element={<ResourceDetailPage environmentId="env-1" />} path="/resources/:resourceType" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )

  expect(await screen.findByText('调度压力')).toBeInTheDocument()
  expect(screen.getByText('P1')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /查看风险详情/ })).toHaveAttribute('href', '/risks/risk-1')
})

it('keeps a zero-asset summary in the NO_DATA state', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: {
      resource_type: { code: 'HOST', name: '主机基础环境', description: '', icon: 'host', asset_count: 0, inspection_item_count: 1, health_score: null, risk_count: 0, p1_count: 0, p2_count: 0, last_inspection_at: null, data_state: 'NO_DATA' },
      latest: { health_score: null, coverage_rate: null, risk_count: 0, p1_count: 0, p2_count: 0, inspection_item_count: 1, summary: { data_state: 'NO_DATA' } },
      health_trend: [],
    },
  } as never)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/resources/host']}>
        <Routes>
          <Route element={<ResourceDetailPage environmentId="env-1" />} path="/resources/:resourceType" />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )

  expect(await screen.findByText('健康度')).toBeInTheDocument()
  expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  expect(screen.queryByText('100%')).not.toBeInTheDocument()
})
