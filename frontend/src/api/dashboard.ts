import { apiClient } from './http'

export interface DashboardSnapshot {
  id: string
  snapshot_id: string
  environment_id: string
  date?: string
  snapshot_date: string
  inspection_run_id: string
  assets_total: number
  assets_covered: number
  inspection_item_count: number
  risk_total: number
  p1_count: number
  p2_count: number
  new_count: number
  worsened_count: number
  recovered_count: number
  pending_action_count: number
  pending_reverify_count: number
  code_only_cases: number
  ai_dependent_cases: number
  code_coverage_rate: number
  deterministic_deflection_rate: number
  ai_displacement_rate: number
  data_completeness_rate: number
  summary: Record<string, unknown>
}

export interface DashboardRisk {
  id: string
  href?: string
  risk_id?: string
  risk_key?: string
  title: string
  domain: string
  severity: string
  status: string
  occurrence_count: number
  ai_involved?: boolean
  ai_involved_last?: boolean
  last_seen_at: string | null
}

export interface DashboardToday {
  snapshot: DashboardSnapshot
  top_risks: DashboardRisk[]
  yesterday_diff: Record<string, number>
  trend_7d: DashboardSnapshot[]
  capability_maturity: {
    enabled_items: number
    coded_items: number
  }
}

export async function getDashboardToday(environmentId: string) {
  const response = await apiClient.get<DashboardToday>('/dashboard/today', {
    params: { environment: environmentId },
  })
  return response.data
}
