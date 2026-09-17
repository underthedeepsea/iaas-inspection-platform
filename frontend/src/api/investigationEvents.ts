import { apiClient } from './http'
import type { InvestigationEvent } from './investigations'

interface InvestigationEventResponse {
  sequence: number
  event_type: string
  event?: string
  status: string
  data?: Record<string, unknown>
  payload?: Record<string, unknown>
}

export async function getInvestigationEventHistory(id: string) {
  const response = await apiClient.get<{ items: InvestigationEventResponse[] }>(
    `/investigations/${encodeURIComponent(id)}/events`,
    { params: { page: 1, page_size: 100 } },
  )
  return (response.data.items ?? []).map((event): InvestigationEvent => ({
    sequence: event.sequence,
    event_type: event.event_type || event.event || 'turn.error',
    status: event.status,
    payload: event.payload ?? event.data ?? {},
  }))
}

export function investigationEventStreamUrl(id: string) {
  return `/api/v1/investigations/${encodeURIComponent(id)}/events/stream`
}
