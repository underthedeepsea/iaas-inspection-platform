import { apiClient } from './http'

export type InferenceStatus = 'NORMAL' | 'WARNING' | 'CRITICAL'
export type EvaluationStatus = InferenceStatus | 'NOT_READY'

export interface LatencyMetrics {
  avg_ms: number
  p90_ms: number
  p95_ms: number
  p99_ms: number
}

export interface CurrentInferenceMetrics {
  ttft: LatencyMetrics & { e2e_ratio: number }
  tpot: LatencyMetrics
  e2e: LatencyMetrics
  traffic: { qps: number; qpm: number }
  throughput: { generation_tps: number; prompt_tps: number }
  cache: { kv_cache_hit_rate: number }
  requests: { running: number; waiting: number }
}

export interface InferenceReason {
  code: string
  metric: string
  status: Exclude<InferenceStatus, 'NORMAL'>
  current: number
  threshold?: number
  baseline_median?: number
  boundary?: number
  change_ratio?: number
}

export interface InferenceProfile {
  snapshot_id: string
  engine: { engine_id: string; engine_type: string; model_name: string }
  window: { start: string; end: string }
  status: InferenceStatus | 'UNKNOWN'
  evaluation_status?: InferenceStatus | 'UNKNOWN'
  freshness?: { state: 'FRESH' | 'STALE'; age_seconds: number; max_age_seconds: number }
  plugin?: { id?: string; version?: string; rule_code?: string }
  quality?: { state?: string; pending_confirmation?: boolean }
  current_metrics: CurrentInferenceMetrics
  fixed: { status?: InferenceStatus }
  dynamic: { status?: EvaluationStatus; baseline_state?: 'READY' | 'NOT_READY' }
  trend: { status?: 'STABLE' | 'WATCH' | 'DEGRADING' | 'NOT_READY' }
  policy_source: { level?: 'DEFAULT' | 'ENGINE' | 'ENGINE_MODEL'; config_hash?: string }
  reasons: InferenceReason[]
}

export interface InferenceEngine { engine_id: string; engine_type: string; model_name: string }

export async function getInferenceEngines(environmentId: string) {
  const response = await apiClient.get<{ engines: InferenceEngine[] }>('/inference-performance/engines', {
    params: { environment_id: environmentId },
  })
  return response.data.engines
}

export async function getInferenceProfile(environmentId: string, engineId = 'latest', engineType?: string, modelName?: string) {
  const response = await apiClient.get<InferenceProfile>(
    `/inference-performance/engines/${encodeURIComponent(engineId)}/profile`,
    { params: { environment_id: environmentId, engine_type: engineType, model_name: modelName } },
  )
  return response.data
}
