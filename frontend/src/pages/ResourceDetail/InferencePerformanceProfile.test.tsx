import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import type { InferenceProfile } from '../../api/inferencePerformance'
import { InferencePerformanceProfile } from './InferencePerformanceProfile'

afterEach(() => vi.restoreAllMocks())

function renderProfile() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><InferencePerformanceProfile environmentId="env-1" /></QueryClientProvider>)
}

it('renders an abnormal LLM runtime profile with deterministic reasons', async () => {
  const profile: InferenceProfile = {
    snapshot_id: 'snapshot-1', window: { start: '2026-09-22T07:59:00Z', end: '2026-09-22T08:00:00Z' },
    engine: { engine_id: 'qwen-1', engine_type: 'vllm', model_name: 'Qwen/Qwen3-32B' }, status: 'WARNING',
    current_metrics: {
      ttft: { avg_ms: 300, p90_ms: 500, p95_ms: 600, p99_ms: 700, e2e_ratio: 0.2 },
      tpot: { avg_ms: 20, p90_ms: 25, p95_ms: 30, p99_ms: 40 },
      e2e: { avg_ms: 3000, p90_ms: 4500, p95_ms: 5100, p99_ms: 6000 },
      traffic: { qps: 8, qpm: 480 }, throughput: { generation_tps: 1000, prompt_tps: 2000 },
      cache: { kv_cache_hit_rate: 0.7 }, requests: { running: 4, waiting: 12 },
    },
    fixed: { status: 'WARNING' }, dynamic: { status: 'NOT_READY' }, trend: { status: 'WATCH' }, policy_source: { level: 'ENGINE_MODEL' },
    reasons: [{ code: 'TTFT_P95_FIXED_HIGH', metric: 'ttft.p95_ms', status: 'WARNING', current: 600, threshold: 500 }],
  }
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: profile })
  renderProfile()
  expect(await screen.findByText('推理性能画像')).toBeInTheDocument()
  expect(await screen.findByText('TTFT_P95_FIXED_HIGH')).toBeInTheDocument()
  expect(screen.getByText('历史基线建立中')).toBeInTheDocument()
  expect(screen.getByText('Prompt TPS')).toBeInTheDocument()
  expect(screen.getByText('2000')).toBeInTheDocument()
})

it('shows an explicit empty state when the API has no profile', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} } as never)
  renderProfile()
  expect(await screen.findByText('暂无性能数据')).toBeInTheDocument()
})

it('shows the empty state for the backend not-found contract', async () => {
  vi.spyOn(apiClient, 'get').mockRejectedValue({ response: { status: 404, data: { error: {
    code: 'ENGINE_PERFORMANCE_NOT_FOUND', message: 'engine performance profile does not exist', details: {}, trace_id: 'tr_missing',
  } } } })
  renderProfile()
  expect(await screen.findByText('暂无性能数据')).toBeInTheDocument()
  expect(screen.queryByText('性能数据暂不可用')).not.toBeInTheDocument()
})

it('keeps non-not-found failures distinct from an empty profile', async () => {
  vi.spyOn(apiClient, 'get').mockRejectedValue({ response: { status: 500, data: { error: {
    code: 'INTERNAL_ERROR', message: 'failed', details: {}, trace_id: 'tr_failed',
  } } } })
  renderProfile()
  expect(await screen.findByText('性能数据暂不可用')).toBeInTheDocument()
  expect(screen.queryByText('暂无性能数据')).not.toBeInTheDocument()
})
