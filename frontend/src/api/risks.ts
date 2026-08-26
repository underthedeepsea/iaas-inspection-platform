import { apiClient } from './http'

export interface RiskCodeization {
  code_status?: string
  execution_mode?: string
  code_coverage_percent?: number | null
  resolved_claims?: string[]
}

export interface Risk {
  id: string
  risk_id?: string
  environment_id?: string
  inspection_item_id?: string
  primary_asset_id?: string | null
  risk_key?: string
  fingerprint?: string
  title: string
  domain: string
  severity: string
  status: string
  occurrence_count: number
  duration_days?: number
  llm_involved_last?: boolean
  ai_involved?: boolean
  first_seen_at?: string | null
  last_seen_at?: string | null
  recovered_at?: string | null
  current_conclusion?: string
  impact_summary?: string
  recommendation?: string
  codeization?: RiskCodeization
  current_investigation_id?: string | null
  recent_investigation?: {
    investigation_id: string
    status: string
    conclusion?: string
    confidence?: number | null
  } | null
}

export interface RiskTimelineEvent {
  id?: string
  at?: string | null
  label?: string
  to_status?: string
  source?: string
  reason?: string
}

export interface RiskEvidence {
  id: string
  evidence_id?: string
  evidence_key?: string
  evidence_type?: string
  summary?: string
  source?: string
  confidence?: number | null
}

export interface RiskListParams {
  environmentId?: string
  severity?: string
  status?: string
  pageSize?: number
}

export const riskKeys = {
  all: ['risks'] as const,
  list: (params: RiskListParams = {}) => [...riskKeys.all, 'list', params] as const,
  detail: (riskId: string) => [...riskKeys.all, 'detail', riskId] as const,
  timeline: (riskId: string) => [...riskKeys.detail(riskId), 'timeline'] as const,
  evidence: (riskId: string) => [...riskKeys.detail(riskId), 'evidence'] as const,
}

export async function getRisks(params: RiskListParams = {}) {
  const response = await apiClient.get<{ items: Risk[]; page: number; page_size: number; total: number }>('/risks', {
    params: {
      ...(params.environmentId ? { environment_id: params.environmentId } : {}),
      severity: params.severity,
      status: params.status,
      page_size: params.pageSize ?? 100,
    },
  })
  return response.data
}

export async function getRisk(riskId: string) {
  const response = await apiClient.get<Risk>(`/risks/${encodeURIComponent(riskId)}`)
  return response.data
}

export async function getRiskTimeline(riskId: string) {
  const response = await apiClient.get<{ risk_id: string; events: RiskTimelineEvent[] }>(`/risks/${encodeURIComponent(riskId)}/timeline`)
  return response.data
}

export async function getRiskEvidence(riskId: string, limit = 50) {
  const response = await apiClient.get<{ risk_id: string; items: RiskEvidence[]; limit: number; total: number }>(`/risks/${encodeURIComponent(riskId)}/evidence`, { params: { limit } })
  return response.data
}

export async function markRiskHandled(riskId: string, comment: string) {
  const response = await apiClient.post<{ risk_id: string; status: string }>(`/risks/${encodeURIComponent(riskId)}/mark-handled`, { comment })
  return response.data
}

export async function reverifyRisk(riskId: string) {
  const response = await apiClient.post<{ risk_id: string; status: string; inspection_run_id?: string }>(`/risks/${encodeURIComponent(riskId)}/reverify`, {})
  return response.data
}

export async function startRiskInvestigation(riskId: string, question: string) {
  const response = await apiClient.post<{ investigation_id: string; status: string }>(`/risks/${encodeURIComponent(riskId)}/investigations`, { question, trigger_type: 'HUMAN' })
  return response.data
}
