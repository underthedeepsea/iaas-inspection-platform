import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { MainLayout, resolveEnvironmentId } from './MainLayout'

afterEach(() => vi.restoreAllMocks())

it('renders the document navigation and runtime controls from the environment API', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({
    data: {
      items: [{ id: 'env-1', slug: 'production', name: '生产环境', environment_type: 'PROD_SIM', assets_count: 8, mock_dataset_count: 2, inspection_run_count: 2, has_mock_data: true }],
      page: 1,
      page_size: 50,
      total: 1,
    },
  } as never)
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
  expect(screen.getByRole('link', { name: 'AI运行' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '产品说明' })).toBeInTheDocument()
  expect(screen.getByText('更多')).toBeInTheDocument()
  expect(screen.getByLabelText('巡检环境')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/生产环境/)).toBeInTheDocument())
  expect(screen.getByText('AI 运行正常')).toBeInTheDocument()
  expect(screen.getByText('未登录')).toBeInTheDocument()
  expect(screen.getByText('环境数据由 API 提供')).toBeInTheDocument()
  expect(screen.queryByText('本地演示环境')).not.toBeInTheDocument()
  expect(screen.queryByText('Demo v4.1')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '收起侧边栏' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '打开主导航' })).toHaveAttribute('aria-expanded', 'false')

  fireEvent.click(screen.getByRole('button', { name: '收起侧边栏' }))
  expect(screen.getByRole('button', { name: '展开侧边栏' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: '打开主导航' }))
  expect(screen.getByRole('button', { name: '关闭主导航' })).toHaveAttribute('aria-expanded', 'true')
})

it('resolves the environment in URL, persisted state, then API order', () => {
  const environments = [
    { id: 'env-1' },
    { id: 'env-2' },
  ]

  expect(resolveEnvironmentId(environments, 'env-2', 'env-1')).toBe('env-2')
  expect(resolveEnvironmentId(environments, 'missing', 'env-1')).toBe('env-1')
  expect(resolveEnvironmentId(environments, 'missing', 'also-missing')).toBe('env-1')
})
