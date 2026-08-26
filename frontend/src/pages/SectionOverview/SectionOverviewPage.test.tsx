import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { SectionOverviewPage } from './SectionOverviewPage'

afterEach(() => vi.restoreAllMocks())

describe('SectionOverviewPage', () => {
  it('presents the risk center with lifecycle filters and an auditable table', () => {
    render(<SectionOverviewPage page="risks" />)

    expect(screen.getByRole('heading', { name: '风险中心' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '待复验' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'AI 介入' })).toBeInTheDocument()
    expect(screen.getByText('暂无风险数据')).toBeInTheDocument()
  })

  it('explains the AI runtime boundary in the product language', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data_mode: 'LIVE', llm_provider: 'openai', security_mode: 'READ_ONLY_TOOLS' },
    } as never)
    render(<SectionOverviewPage page="ai-runtime" />)

    expect(screen.getByRole('heading', { name: 'AI 运行情况' })).toBeInTheDocument()
    expect(screen.getByText('READ_ONLY_TOOLS')).toBeInTheDocument()
    expect(screen.getByText('所有 Tool Call 都是只读的。')).toBeInTheDocument()
    expect(await screen.findByText('openai')).toBeInTheDocument()
    expect(await screen.findByText('LIVE')).toBeInTheDocument()
    expect(screen.queryByText('Ollama')).not.toBeInTheDocument()
    expect(screen.queryByText('MOCK')).not.toBeInTheDocument()
  })
})
