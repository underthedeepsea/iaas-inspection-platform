import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { MainLayout } from './MainLayout'

it('renders the shared navigation and runtime controls', () => {
  render(
    <MemoryRouter>
      <MainLayout>
        <div>页面内容</div>
      </MainLayout>
    </MemoryRouter>,
  )

  expect(screen.getByText('IaaS 智能巡检')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '总览' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '资源巡检' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '风险中心' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '巡检能力' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '能力演进' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'AI 运行' })).toBeInTheDocument()
  expect(screen.getByLabelText('巡检环境')).toBeInTheDocument()
  expect(screen.getByText('AI 运行正常')).toBeInTheDocument()
})
