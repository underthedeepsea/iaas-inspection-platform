import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { DashboardPage } from './DashboardPage'

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DashboardPage environmentId="env-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('DashboardPage', () => {
  it('shows a loading state while resource types are loading', () => {
    vi.spyOn(apiClient, 'get').mockReturnValue(new Promise(() => {}) as never)

    renderDashboard()

    expect(screen.getByText('正在读取每日巡检')).toBeInTheDocument()
  })

  it('shows health KPIs and resource cards when ready', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        items: [
          {
            code: 'LLM_RUNTIME',
            name: '大模型运行时',
            description: '模型服务资源',
            icon: 'sparkles',
            asset_count: 12,
            inspection_item_count: 4,
            health_score: 92,
            risk_count: 2,
            p1_count: 0,
            p2_count: 1,
            last_inspection_at: '2026-08-25T08:00:00Z',
          },
        ],
        page: 1,
        page_size: 1,
        total: 1,
      },
    } as never)

    renderDashboard()

    expect((await screen.findAllByText('大模型运行时')).length).toBeGreaterThan(0)
    expect(screen.getByText('整体健康度')).toBeInTheDocument()
    expect(screen.getByText('当前风险')).toBeInTheDocument()
    expect(screen.getByText('巡检覆盖率')).toBeInTheDocument()
    expect(screen.getByText('AI 介入')).toBeInTheDocument()
    expect(screen.getByText('重点风险')).toBeInTheDocument()
    expect(screen.getByText('巡检完整性')).toBeInTheDocument()
    expect(screen.getByText('能力成熟度')).toBeInTheDocument()
    expect(screen.getAllByText('92').length).toBeGreaterThan(0)
    expect(screen.getByText('12 个对象')).toBeInTheDocument()
    expect(screen.getByText('风险 2')).toBeInTheDocument()
    expect(screen.getByText('资源健康状态')).toBeInTheDocument()
    expect([...document.querySelectorAll('[data-dashboard-section]')].map((node) => node.getAttribute('data-dashboard-section'))).toEqual([
      'kpi',
      'trend-and-risks',
      'auxiliary',
      'resource-health',
    ])
  })

  it('renders the completeness rate as a bounded percentage', async () => {
    vi.spyOn(apiClient, 'get').mockImplementation((url) => {
      if (String(url) === '/resource-types') {
        return Promise.resolve({ data: { items: [{ code: 'HOST', name: '主机基础环境', description: '基础设施资源', icon: 'host', asset_count: 1, inspection_item_count: 1, health_score: 96, risk_count: 0, p1_count: 0, p2_count: 0, last_inspection_at: null }], total: 1 } }) as never
      }
      return Promise.resolve({
        data: {
          snapshot: { snapshot_date: '2026-08-31', data_completeness_rate: 100, assets_total: 1, assets_covered: 1, risk_total: 0, p1_count: 0, p2_count: 0, ai_dependent_cases: 0 },
          top_risks: [],
          trend_7d: [],
          capability_maturity: { enabled_items: 1, coded_items: 1 },
        },
      }) as never
    })

    renderDashboard()

    expect(await screen.findByText('当前 100%')).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.queryByText('10000')).not.toBeInTheDocument()
  })

  it('shows an empty-state CTA when no resource types are returned', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [], total: 0 } } as never)

    renderDashboard()

    expect(await screen.findByText('还没有可展示的资源巡检数据')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '立即巡检' })).toBeInTheDocument()
  })

  it('shows a retry action and trace id on API errors', async () => {
    const error = Object.assign(new Error('request failed'), {
      response: { data: { error: { message: '资源服务暂不可用', trace_id: 'tr_dashboard' } } },
    })
    vi.spyOn(apiClient, 'get').mockRejectedValue(error)

    renderDashboard()

    expect(await screen.findByText('资源服务暂不可用')).toBeInTheDocument()
    expect(screen.getByText('追踪 ID：tr_dashboard')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
