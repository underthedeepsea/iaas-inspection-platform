import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { AiRuntimePage } from './AiRuntimePage'

afterEach(() => vi.restoreAllMocks())

it('shows the configured provider and the one-shot read-only boundary', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: { data_mode: 'LIVE', llm_provider: 'openai', security_mode: 'READ_ONLY_TOOLS' },
  } as never)

  render(<AiRuntimePage />)

  expect(screen.getByRole('heading', { name: 'AI 运行情况' })).toBeInTheDocument()
  expect(screen.getByText('单轮')).toBeInTheDocument()
  expect(screen.getByText('0')).toBeInTheDocument()
  expect(screen.getByText('禁止')).toBeInTheDocument()
  expect(await screen.findByText('openai')).toBeInTheDocument()
  expect(await screen.findByText('LIVE')).toBeInTheDocument()
})
