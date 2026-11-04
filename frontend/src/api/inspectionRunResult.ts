import type { InspectionFactReport } from './inspectionFacts'
import { apiClient } from './http'
import type { AnalysisSource, CheckResult, ResourceSummary } from './resources'
import type { Risk } from './risks'

export interface FrozenMappingInputs {
  source_ref?: string | null
  batch_id?: string | null
  revision_id?: string | null
  content_hash?: string | null
  environment_id?: string | null
  window_start?: string | null
  window_end?: string | null
  snapshot_ids?: string[] | null
  asset_ids?: string[] | null
  activation_id?: string | null
  validation_id?: string | null
  cluster_uid?: string | null
  monitor_cluster_id?: string | null
  raw_hash?: string | null
  baseline_status?: string | null
  versions?: Record<string, string> | null
  limitations?: string[] | null
}

export interface FrozenMappingInputQuality {
  status?: 'COMPLETE' | 'PARTIAL' | null
  required_fields?: number | null
  valid_fields?: number | null
  coverage?: number | null
  missing_count?: number | null
  missing?: Array<{ asset_id: string; component?: string; field: string; quality?: string }> | null
  missing_truncated?: boolean
  binding_errors?: string[] | null
  baseline_status?: string | null
  basis?: string | null
}

export interface InspectionRunResult {
  mapping_inputs?: FrozenMappingInputs | null
  mapping_input_quality?: FrozenMappingInputQuality | null
  run: { id: string; environment_id: string; status: string; trigger_type: string; run_date: string; started_at: string | null; finished_at: string | null; error_message?: string }
  scope: { resource_types: string[] }
  summary: { assets_total: number; assets_covered: number; pass_count: number; fail_count: number; unknown_count: number; error_count: number; not_applicable_count: number; risk_count: number; check_count: number }
  resource_summaries: ResourceSummary[]
  fact_report?: InspectionFactReport
  check_results: CheckResult[]
  risks: Risk[]
  code_plugins: Array<AnalysisSource & {rule_code: string; resource_types: string[]}>
}
export async function getInspectionRunResult(runId: string, environmentId: string) {
  return (await apiClient.get<InspectionRunResult>(`/inspection-runs/${runId}/result`, {params:{environment_id:environmentId}})).data
}
