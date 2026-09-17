import { apiClient } from './http'
import type { AnalysisSource, CheckResult, ResourceSummary } from './resources'
import type { Risk } from './risks'

export interface InspectionRunResult {
  run: { id: string; environment_id: string; status: string; trigger_type: string; run_date: string; started_at: string | null; finished_at: string | null; error_message?: string }
  scope: { resource_types: string[] }
  summary: { assets_total: number; assets_covered: number; pass_count: number; fail_count: number; unknown_count: number; error_count: number; not_applicable_count: number; risk_count: number; check_count: number }
  resource_summaries: ResourceSummary[]
  check_results: CheckResult[]
  risks: Risk[]
  code_plugins: Array<AnalysisSource & {rule_code: string; resource_types: string[]}>
}
export async function getInspectionRunResult(runId: string, environmentId: string) {
  return (await apiClient.get<InspectionRunResult>(`/inspection-runs/${runId}/result`, {params:{environment_id:environmentId}})).data
}
