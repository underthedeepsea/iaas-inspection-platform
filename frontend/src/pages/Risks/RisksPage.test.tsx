import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { RisksPage } from './RisksPage'

afterEach(() => vi.restoreAllMocks())

describe('RisksPage', () => {
  it('renders risk lifecycle rows with severity and AI state', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        items: [{
          id: 'risk-1', risk_id: 'risk-1', risk_key: 'scheduler.pressure', title: 'Scheduler Queue Pressure', domain: 'LLM',
          severity: 'P2', status: 'PENDING_ACTION', occurrence_count: 3, ai_involved: true, last_seen_at: '2026-08-25T08:00:00Z',
        }], page: 1, page_size: 100, total: 1,
      },
    } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={queryClient}><MemoryRouter><RisksPage /></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('heading', { name: '风险中心' })).toBeInTheDocument()
    expect(await screen.findByText('Scheduler Queue Pressure')).toBeInTheDocument()
    expect(screen.getAllByText('待处置').length).toBeGreaterThan(1)
    expect(screen.getAllByText('AI 介入').length).toBeGreaterThan(1)
    expect(screen.getByRole('link', { name: '打开 →' })).toHaveAttribute('href', '/risks/risk-1')
  })
})
