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

const engine = { engine_id: 'qwen-1', engine_type: 'vllm', model_name: 'Qwen/Qwen3-32B' }

function mockProfile(profile: InferenceProfile | null, error?: unknown) {
  vi.spyOn(apiClient, 'get').mockImplementation(async (url) => {
    if (url === '/inference-performance/engines') return { data: { engines: [engine] } } as never
    if (error) throw error
    return { data: profile } as never
  })
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
    fixed: { status: 'WARNING', metrics: { 'ttft.p99_ms': { raw_status: 'WARNING', effective_status: 'NORMAL', consecutive_hits: 1, current: 700, warning: 600, critical: 900 } } }, dynamic: { status: 'NOT_READY', load_filter: 'FULL_HISTORY_FALLBACK', metrics: { 'requests.waiting': { status: 'NOT_EVALUABLE', baseline_median: 0, current: 12, quality_reason: 'ZERO_BASELINE', contributes_to_status: false } } }, trend: { status: 'WATCH', metrics: { 'ttft.p95_ms': { status: 'WATCH', first_half_median: 500, second_half_median: 600, change_ratio: 0.2 } } }, resolved_policy: { persistence: { consecutive_hits: 2 } }, policy_source: { level: 'ENGINE_MODEL' },
    quality: { state: 'READY', pending_confirmation: true },
    reasons: [{ code: 'TTFT_P95_FIXED_HIGH', metric: 'ttft.p95_ms', status: 'WARNING', current: 600, threshold: 500 }],
  }
  mockProfile(profile)
  renderProfile()
  expect(await screen.findByText('推理性能画像')).toBeInTheDocument()
  expect(await screen.findByText('TTFT_P95_FIXED_HIGH')).toBeInTheDocument()
  expect(screen.getByText('历史基线建立中')).toBeInTheDocument()
  expect(screen.getByText('全部当前指标')).toBeInTheDocument()
  expect(screen.getByText('已 1/2 点，待后续有效观测确认。')).toBeInTheDocument()
  expect(screen.getByText('零基线，比例变化不可评估；仅展示原始差值。')).toBeInTheDocument()
  expect(screen.getByText('FULL_HISTORY_FALLBACK')).toBeInTheDocument()
  expect(screen.getByText('first_half_median')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '推理性能画像' }).querySelector('.section-heading .status-badge')?.textContent).toBe('WARNING')
  expect(screen.getByText('部分原始指标待确认；已确认异常仍有效。')).toBeInTheDocument()
})

it('shows an explicit empty state when the API has no profile', async () => {
  mockProfile({} as InferenceProfile)
  renderProfile()
  expect(await screen.findByText('暂无性能数据')).toBeInTheDocument()
})

it('shows the empty state for the backend not-found contract', async () => {
  mockProfile(null, { response: { status: 404, data: { error: {
    code: 'ENGINE_PERFORMANCE_NOT_FOUND', message: 'engine performance profile does not exist', details: {}, trace_id: 'tr_missing',
  } } } })
  renderProfile()
  expect(await screen.findByText('暂无性能数据')).toBeInTheDocument()
  expect(screen.queryByText('性能数据暂不可用')).not.toBeInTheDocument()
})

it('keeps non-not-found failures distinct from an empty profile', async () => {
  mockProfile(null, { response: { status: 500, data: { error: {
    code: 'INTERNAL_ERROR', message: 'failed', details: {}, trace_id: 'tr_failed',
  } } } })
  renderProfile()
  expect(await screen.findByText('性能数据暂不可用')).toBeInTheDocument()
  expect(screen.queryByText('暂无性能数据')).not.toBeInTheDocument()
})
