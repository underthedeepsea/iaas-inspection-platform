import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { ProductInfoPage } from './ProductInfoPage'

afterEach(() => vi.restoreAllMocks())

describe('ProductInfoPage', () => {
  it('explains the product flow, code and AI division, and security boundary', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data_mode: 'LIVE', llm_provider: 'openai', security_mode: 'READ_ONLY_TOOLS' },
    } as never)
    render(<ProductInfoPage />)

    expect(screen.getByRole('heading', { name: /让巡检结果/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '每日巡检如何工作' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '安全边界：只读 Tool Calling' })).toBeInTheDocument()
    expect(screen.queryByText('PRODUCT NOTE · DEMO V4.1')).not.toBeInTheDocument()
    expect(screen.getByText('当前数据源与运行时')).toBeInTheDocument()
    expect(await screen.findByText('数据源：LIVE')).toBeInTheDocument()
    expect(await screen.findByText('Provider：openai')).toBeInTheDocument()
  })
})
