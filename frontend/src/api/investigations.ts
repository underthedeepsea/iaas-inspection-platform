import { apiClient } from './http'
import {
  getInvestigationEventHistory,
  investigationEventStreamUrl,
} from './investigationEvents'

export type InvestigationContextType = 'RESOURCE_TYPE' | 'RESOURCE_RUN'

export interface CreateInvestigationInput {
  contextType: InvestigationContextType
  environmentId?: string
  inspectionRunId?: string
  dateFrom?: string
  dateTo?: string
}

export interface StructuredInvestigationResult {
  comparisons?: unknown[]
  root_cause_candidates?: unknown[]
  priority_actions?: unknown[]
  evidence_gaps?: unknown[]
}

export interface Investigation {
  id: string
  investigation_id: string
  status: string
  entry_reason?: string
  conclusion?: string
  confidence?: number | null
  started_at?: string | null
  finished_at?: string | null
  conversation_id?: string | null
  result?: StructuredInvestigationResult & Record<string, unknown>
}

export interface InvestigationEvent {
  sequence: number
  event_type: string
  status: string
  payload: Record<string, unknown>
}

export const investigationKeys = {
  all: ['investigations'] as const,
  detail: (id: string) => [...investigationKeys.all, 'detail', id] as const,
  events: (id: string) => [...investigationKeys.all, 'events', id] as const,
  resource: (code: string) => [...investigationKeys.all, 'resource', code] as const,
}

export async function createResourceInvestigation(code: string, input: CreateInvestigationInput) {
  const response = await apiClient.post<Investigation>(
    `/resource-types/${encodeURIComponent(code)}/analysis`,
    {
      context_type: input.contextType,
      environment_id: input.environmentId,
      inspection_run_id: input.inspectionRunId,
      date_from: input.dateFrom,
      date_to: input.dateTo,
    },
  )
  return response.data
}

export async function getInvestigation(id: string) {
  const response = await apiClient.get<Investigation>(`/investigations/${encodeURIComponent(id)}`)
  return response.data
}

export async function getInvestigationEvents(id: string) {
  return getInvestigationEventHistory(id)
}

export async function getResourceInvestigations(code: string, page = 1, pageSize = 20) {
  const response = await apiClient.get<{ items: Investigation[]; page: number; page_size: number; total: number }>(
    `/resource-types/${encodeURIComponent(code)}/investigations`,
    { params: { page, page_size: pageSize } },
  )
  return response.data
}

export function investigationEventsUrl(id: string) {
  return investigationEventStreamUrl(id)
}
