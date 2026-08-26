import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import type { ResourceType } from '../../api/resources'
import { InspectionDrawer } from './InspectionDrawer'

const resources: ResourceType[] = [
  {
    code: 'CONTROL_PLANE',
    name: '控制面',
    description: '控制面资源',
    icon: 'control',
    asset_count: 24,
    inspection_item_count: 6,
    health_score: 96,
    risk_count: 0,
    p1_count: 0,
    p2_count: 0,
    last_inspection_at: null,
  },
  {
    code: 'LLM_RUNTIME',
    name: '大模型运行时',
    description: '模型服务资源',
    icon: 'llm',
    asset_count: 24,
    inspection_item_count: 6,
    health_score: 92,
    risk_count: 1,
    p1_count: 0,
    p2_count: 1,
    last_inspection_at: null,
  },
]

afterEach(() => vi.restoreAllMocks())

describe('InspectionDrawer', () => {
  it('previews selected resource scope and submits both resource types', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        id: 'run-1',
        inspection_run_id: 'run-1',
        status: 'PENDING',
        trigger_type: 'MANUAL',
        scope: { resource_types: ['CONTROL_PLANE', 'LLM_RUNTIME'], asset_count: 48, inspection_item_count: 12 },
      },
    } as never)

    render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={resources} />)

    expect(screen.getByLabelText('本次巡检环境')).toHaveValue('env-1')
    expect(screen.getByRole('button', { name: /控制面/ })).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('button', { name: /开始巡检/ })).toHaveClass('button-primary')
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
    expect(screen.getByTestId('inspection-drawer-overlay')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /控制面/ }))
    fireEvent.click(screen.getByRole('button', { name: /大模型运行时/ }))
    expect(screen.getByRole('button', { name: /控制面/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('范围预览：48 个资源对象 / 12 个巡检项')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '开始巡检' }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/inspection-runs/trigger', {
      environment_id: 'env-1',
      scope: { resource_types: ['CONTROL_PLANE', 'LLM_RUNTIME'] },
      trigger_options: { ai_mode: 'DEFERRED' },
    }))
    expect(screen.getByText('巡检任务已创建')).toBeInTheDocument()
  })

  it('blocks an empty selection with inline validation', () => {
    render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={resources} />)

    fireEvent.click(screen.getByRole('button', { name: '开始巡检' }))

    expect(screen.getByText('请至少选择一种巡检资源')).toBeInTheDocument()
  })
})
