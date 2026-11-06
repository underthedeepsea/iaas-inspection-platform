import { MemoryRouter } from 'react-router-dom'
import { useInspectionSessionStore } from '../../stores/inspectionSessionStore'
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

afterEach(() => { vi.restoreAllMocks(); useInspectionSessionStore.setState({active:null,lastCompleted:null}) })

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

    const { rerender } = render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={resources} />, {wrapper:MemoryRouter})

    expect(screen.getByLabelText('本次巡检环境')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveClass('inspection-drawer')
    expect(document.querySelector('.ant-drawer')).toBeInTheDocument()
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

    // A dashboard refresh supplies a new callback and refreshed resources.
    const refreshedOnClose = vi.fn()
    rerender(<InspectionDrawer environmentId="env-1" open onClose={refreshedOnClose} resourceTypes={[...resources]} />)
    expect(screen.getByText('巡检任务已创建')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '开始巡检' })).not.toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(refreshedOnClose).toHaveBeenCalled()
  })

  it('blocks an empty selection with inline validation', () => {
    render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={resources} />, {wrapper:MemoryRouter})

    fireEvent.click(screen.getByRole('button', { name: '开始巡检' }))

    expect(screen.getByText('请至少选择一种巡检资源')).toBeInTheDocument()
  })

  it('keeps an unconnected K8S entry visible but cannot submit it, and enables it once ready', () => {
    const cluster = { ...resources[0], code: 'K8S_CLUSTER', name: 'Kubernetes 集群', release_state: 'PLANNED', inspection_item_count: 0 }
    const { rerender } = render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[cluster]} />, {wrapper:MemoryRouter})
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).toBeDisabled()
    expect(screen.getByText('暂无可用巡检插件')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始巡检' })).toBeDisabled()
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[{ ...cluster, release_state: 'READY', inspection_item_count: 1 }]} />)
    fireEvent.click(screen.getByRole('button', { name: /Kubernetes 集群/ }))
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText('范围预览：24 个资源对象 / 1 个巡检项')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始巡检' })).toBeEnabled()
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[cluster]} />)
    expect(screen.getByRole('button', { name: '开始巡检' })).toBeDisabled()
    expect(screen.getByText('范围预览：0 个资源对象 / 0 个巡检项')).toBeInTheDocument()
  })

  it('clears an invalid K8S choice before it becomes ready again and submits only the newly selected host', async () => {
    const ready: ResourceType = { ...resources[0], code: 'K8S_CLUSTER', name: 'Kubernetes 集群', release_state: 'READY', asset_count: 1, inspection_item_count: 1 }
    const planned = { ...ready, release_state: 'PLANNED', inspection_item_count: 0 }
    const host: ResourceType = { ...resources[0], code: 'HOST', name: '宿主机', asset_count: 1, inspection_item_count: 1 }
    const post = vi.spyOn(apiClient, 'post').mockReturnValue(new Promise(() => {}) as never)
    const { rerender } = render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[ready, host]} />, {wrapper:MemoryRouter})
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).toHaveTextContent('已接入正式插件')
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).not.toHaveTextContent('未接入正式插件')
    fireEvent.click(screen.getByRole('button', { name: /Kubernetes 集群/ }))
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[planned, host]} />)
    fireEvent.click(screen.getByRole('button', { name: /宿主机/ }))
    expect(screen.getByText('范围预览：1 个资源对象 / 1 个巡检项')).toBeInTheDocument()
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[ready, host]} />)
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('button', { name: /宿主机/ })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('button', { name: '开始巡检' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/inspection-runs/trigger', { environment_id: 'env-1', scope: { resource_types: ['HOST'] }, trigger_options: { ai_mode: 'DEFERRED' } }))
  })

  it('retains a valid selection while resources are loading but clears a confirmed removal', () => {
    const ready: ResourceType = { ...resources[0], code: 'K8S_CLUSTER', name: 'Kubernetes 集群', release_state: 'READY', inspection_item_count: 1 }
    const host: ResourceType = { ...resources[0], code: 'HOST', name: '宿主机' }
    const { rerender } = render(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[]} resourceTypesLoaded={false} />, {wrapper:MemoryRouter})
    expect(screen.getByText('正在加载资源类型')).toBeInTheDocument()
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[ready, host]} />)
    fireEvent.click(screen.getByRole('button', { name: /Kubernetes 集群/ }))
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[]} resourceTypesLoaded={false} />)
    expect(screen.getByRole('button', { name: '开始巡检' })).toBeDisabled()
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[ready, host]} />)
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).toHaveAttribute('aria-checked', 'true')
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[host]} />)
    rerender(<InspectionDrawer environmentId="env-1" open onClose={vi.fn()} resourceTypes={[ready, host]} />)
    expect(screen.getByRole('button', { name: /Kubernetes 集群/ })).toHaveAttribute('aria-checked', 'false')
  })
})
