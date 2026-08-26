import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { MainLayout } from './MainLayout'

it('renders the document navigation and runtime controls', () => {
  render(
    <MemoryRouter>
      <MainLayout>
        <div>页面内容</div>
      </MainLayout>
    </MemoryRouter>,
  )

  expect(screen.getByText('IaaS 智能巡检')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '每日巡检' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '资源巡检' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '风险中心' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '历史趋势' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '待处置' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '巡检能力' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '规则与经验' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '能力演进' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'AI 运行情况' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '产品说明' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '系统设置' })).toBeInTheDocument()
  expect(screen.getByLabelText('巡检环境')).toBeInTheDocument()
  expect(screen.getByText('AI 运行正常')).toBeInTheDocument()
  expect(screen.getByText('管理员')).toBeInTheDocument()
  expect(screen.getByText('本地演示环境')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '收起侧边栏' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: '收起侧边栏' }))
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toBeInTheDocument()
})
