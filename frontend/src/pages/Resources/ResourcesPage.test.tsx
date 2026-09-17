import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { ResourcesPage } from './ResourcesPage'

afterEach(() => vi.restoreAllMocks())

describe('ResourcesPage', () => {
  it('shows the resource aggregate metrics and the primary inspection action', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        items: [{
          code: 'CONTROL_PLANE', name: '控制面', description: '控制面资源', icon: 'control', asset_count: 12,
          inspection_item_count: 5, health_score: 91, risk_count: 3, p1_count: 1, p2_count: 1,
          coverage_rate: 0.96, last_inspection_at: '2026-08-25T10:00:00Z',
        }], page: 1, page_size: 1, total: 1,
      },
    } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={queryClient}><MemoryRouter><ResourcesPage environmentId="env-1" /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '资源巡检' })).toBeInTheDocument()
    expect(screen.getByText('全部资源')).toBeInTheDocument()
    expect(screen.getByText('当前风险')).toBeInTheDocument()
    expect(screen.getByText('P1/P2')).toBeInTheDocument()
    expect(screen.getByText('平均覆盖率')).toBeInTheDocument()
    expect(screen.getByText('96%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '立即巡检' })).toBeInTheDocument()
  })
})
