import { apiClient } from './http'

export type InspectionAiMode = 'DEFERRED' | 'DISABLED'

export interface TriggerInspectionInput {
  environmentId: string
  resourceTypes: string[]
  aiMode?: InspectionAiMode
}

export interface TriggerInspectionResponse {
  id: string
  inspection_run_id: string
  status: string
  trigger_type: string
  scope: {
    resource_types: string[]
    asset_count: number
    inspection_item_count: number
  }
}

export interface InspectionRunEvent {
  sequence: number
  event_type: string
  status: string
  payload: Record<string, unknown>
}

export interface InspectionRunDetail {
  id?: string
  inspection_run_id?: string
  status: string
  [key: string]: unknown
}

export const inspectionKeys = {
  all: ['inspection-runs'] as const,
  detail: (runId: string) => [...inspectionKeys.all, 'detail', runId] as const,
  events: (runId: string) => [...inspectionKeys.all, 'events', runId] as const,
}

export async function triggerInspection(input: TriggerInspectionInput) {
  const response = await apiClient.post<TriggerInspectionResponse>('/inspection-runs/trigger', {
    environment_id: input.environmentId,
    scope: { resource_types: input.resourceTypes },
    trigger_options: { ai_mode: input.aiMode ?? 'DEFERRED' },
  })
  return response.data
}

export async function getInspectionRun(runId: string) {
  const response = await apiClient.get<InspectionRunDetail>(`/inspection-runs/${runId}`)
  return response.data
}

export function inspectionRunEventsUrl(runId: string) {
  return `/api/v1/inspection-runs/${encodeURIComponent(runId)}/events`
}
