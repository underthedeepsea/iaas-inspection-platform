import { apiClient } from './http'

export interface ResourceType {
  code: string
  name: string
  description: string
  icon: string
  asset_count: number
  assets_total?: number
  assets_covered?: number | null
  coverage_rate?: number | null
  inspection_item_count: number
  health_score: number | null
  risk_count: number
  p1_count: number
  p2_count: number
  ai_investigation_count?: number
  last_inspection_at: string | null
}

export interface ResourceSummary {
  id: string
  inspection_run_id: string
  resource_type: string
  run_date: string
  status: string
  assets_total: number
  assets_covered: number
  coverage_rate: number
  inspection_item_count: number
  success_item_count: number
  failed_item_count: number
  finding_count: number
  risk_count: number
  p1_count: number
  p2_count: number
  p3_count: number
  p4_count: number
  ai_dependent_cases: number
  ai_investigation_count: number
  health_score: number
  started_at: string | null
  finished_at: string | null
  summary: Record<string, unknown>
}

export interface ResourceOverview {
  resource_type: ResourceType
  latest: ResourceSummary | null
  health_trend: ResourceSummary[]
}

export interface Paginated<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface ResourceHistoryParams {
  environmentId: string
  dateFrom?: string
  dateTo?: string
  page?: number
  pageSize?: number
}

export interface ResourceRunDetail {
  resource_type: string
  run: {
    id: string
    status: string
    run_date: string
    started_at: string | null
    finished_at: string | null
  }
  coverage: { assets_total: number; assets_covered: number; rate: number }
  inspection_item_status_counts: Record<string, number>
  inspection_item_count: number
  finding_count: number
  risk_count: number
  severity_counts: Record<string, number>
  ai_dependent_cases: number
  ai_investigation_count: number
  major_risks: Array<Record<string, unknown>>
  summary: Record<string, unknown>
}

export const resourceKeys = {
  all: ['resource-types'] as const,
  list: (environmentId: string) => [...resourceKeys.all, 'list', environmentId] as const,
  detail: (environmentId: string, code: string) =>
    [...resourceKeys.all, 'detail', environmentId, code] as const,
  history: (environmentId: string, code: string, params?: ResourceHistoryParams) =>
    [...resourceKeys.detail(environmentId, code), 'history', params ?? {}] as const,
  run: (environmentId: string, code: string, runId: string) =>
    [...resourceKeys.detail(environmentId, code), 'run', runId] as const,
}

export async function getResourceTypes(environmentId: string) {
  const response = await apiClient.get<Paginated<ResourceType>>('/resource-types', {
    params: { environment_id: environmentId },
  })
  return response.data
}

export async function getResourceOverview(code: string, environmentId: string) {
  const response = await apiClient.get<ResourceOverview>(
    `/resource-types/${encodeURIComponent(code)}/overview`,
    { params: { environment_id: environmentId } },
  )
  return response.data
}

export async function getResourceHistory(code: string, params: ResourceHistoryParams) {
  const response = await apiClient.get<Paginated<ResourceSummary>>(
    `/resource-types/${encodeURIComponent(code)}/inspection-history`,
    {
      params: {
        environment_id: params.environmentId,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        page: params.page,
        page_size: params.pageSize,
      },
    },
  )
  return response.data
}

export async function getResourceRunDetail(code: string, runId: string, environmentId: string) {
  const response = await apiClient.get<ResourceRunDetail>(
    `/resource-types/${encodeURIComponent(code)}/inspection-history/${runId}`,
    { params: { environment_id: environmentId } },
  )
  return response.data
}
