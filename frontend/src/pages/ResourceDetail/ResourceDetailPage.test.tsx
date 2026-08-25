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

