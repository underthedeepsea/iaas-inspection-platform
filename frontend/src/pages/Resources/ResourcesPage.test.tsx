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
          code: 'LLM_RUNTIME', name: 'LLM 运行时', description: '推理性能资源', icon: 'llm', asset_count: 12,
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

  it('offers Kubernetes in the current resource list while omitting KVM', async () => {
    const base = { description: '', icon: '', asset_count: 1, inspection_item_count: 0, health_score: null, risk_count: 0, p1_count: 0, p2_count: 0, last_inspection_at: null }
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [
      { ...base, code: 'K8S_CLUSTER', name: 'Kubernetes 集群' },
      { ...base, code: 'KVM_CLUSTER', name: 'KVM 集群' },
    ] } } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><MemoryRouter><ResourcesPage environmentId="env-1" /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('link', { name: /Kubernetes 集群/ })).toHaveAttribute('href', '/resources/k8s-cluster')
    expect(screen.queryByText('KVM 集群')).not.toBeInTheDocument()
  })
})
