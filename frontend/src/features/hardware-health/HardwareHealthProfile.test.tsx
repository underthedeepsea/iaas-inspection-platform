import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi, test, expect } from 'vitest'
import { apiClient } from '../../api/http'
import { HardwareHealthProfile } from './HardwareHealthProfile'
import { isLaunchResource } from '../resource-health/resourceRoutes'

test('hardware resources are selectable and stale/missing metrics remain explicit', async () => {
  expect(isLaunchResource({ code: 'GPU_POOL' })).toBe(true)
  expect(isLaunchResource({ code: 'HOST' })).toBe(true)
  const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { profiles: [{ snapshot_id: 's', asset_id: 'a', asset_name: 'GPU-1', host_id: 'host-1', status: 'UNKNOWN', freshness: 'STALE', window_start: 'start', window_end: 'end', metrics: { gpu: { identity: {}, values: { temperature_celsius: { value: null, quality: 'UNSUPPORTED', collected_at: 'end' } } } }, evaluation: { diagnostics: { 'gpu/output': { status: 'NOT_READY', sample_count: 0 } }, issues: [], correlations: [], limitations: ['没有证据不能确诊热降频。'] } }] } })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwareHealthProfile environmentId="env" resourceCode="GPU_POOL" /></QueryClientProvider>)
  expect(await screen.findByText(/数据过期，当前状态未知/)).toBeInTheDocument()
  expect(screen.getByText('UNSUPPORTED')).toBeInTheDocument()
  expect(screen.getByText(/gpu\/output · NOT_READY/)).toBeInTheDocument()
  expect(get).toHaveBeenCalledWith('/hardware-health/profiles', { params: { environment_id: 'env', resource_type: 'GPU_POOL' } })
  get.mockRestore()
})


test('capacity initialization is observation and HOST uses versioned CPU requirements', async () => {
  const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { profiles: [{ snapshot_id: 's', asset_id: 'a', asset_name: 'Host-1', host_id: 'h', status: 'UNKNOWN', freshness: 'FRESH', window_start: 'start', window_end: 'end', metrics: {}, evaluation: { diagnostics: { 'host/memory_total_bytes': { status: 'NORMAL', current: 1024 }, 'host/cpu_static': { status: 'PENDING', confirmation_points: 1, confirmation_required: 3, reason: 'TRIGGER_CONFIRMATION_PENDING' } }, issues: [], correlations: [], limitations: [] } }] } })
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwareHealthProfile environmentId="env" resourceCode="HOST" /></QueryClientProvider>)
  expect(await screen.findByText(/OBSERVATION · 容量观测/)).toBeInTheDocument()
  expect(screen.getByText(/HOST v2 CPU漂移需14天30/)).toBeInTheDocument()
  expect(screen.getByText('confirmation_points')).toBeInTheDocument()
  expect(screen.getByText(/host\/cpu_static · PENDING/)).toBeInTheDocument()
  get.mockRestore()
})
