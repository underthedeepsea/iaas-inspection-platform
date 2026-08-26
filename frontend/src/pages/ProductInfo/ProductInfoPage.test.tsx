import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ProductInfoPage } from './ProductInfoPage'

describe('ProductInfoPage', () => {
  it('explains the product flow, code and AI division, and security boundary', () => {
    render(<ProductInfoPage />)

    expect(screen.getByRole('heading', { name: /让巡检结果/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '每日巡检如何工作' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '安全边界：只读 Tool Calling' })).toBeInTheDocument()
    expect(screen.getByText('数据源：MOCK')).toBeInTheDocument()
  })
})
