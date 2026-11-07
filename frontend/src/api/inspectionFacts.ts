import { apiClient } from './http'

export interface FactMeasurement {
  layer: string
  code?: string
  metric?: string
  key?: string
  status?: string
  current?: number
  current_metric?: string
  value?: number
  branches?: Record<string, {threshold: number; base: number; scale: number}>
  rule_id?: string
  rule_version?: string
  rule?: Record<string, number | string>
  confirmation_points?: number
  confirmation_required?: number
  trigger_window_seconds?: number
  recovery_required?: number
  recovery_window_seconds?: number
  reason?: string
  action?: string
  threshold?: number
  boundary?: number
  baseline_median?: number
  change_boundary?: number
  change_ratio?: number
  warning?: number
  critical?: number
  xid_code?: number
  occurred_at?: string
  value_semantics?: 'EVENT' | 'OBSERVATION'
  unit?: string
  quality?: string
  collected_at?: string
  source?: string | null
  config_id?: string | null
  measurement_semantics?: string
  event_id?: string
  reserve_bytes?: number
  seconds_to_reserve?: number
  short_slope_bytes_per_second?: number
  long_slope_bytes_per_second?: number
  first_half_median?: number
  second_half_median?: number
}
export interface HostDiagnosticPresentation {
  rule_reference: string
  recorded_plugin_version?: string | null
  evaluation_status?: string | null
  window_start?: string | null
  window_end?: string | null
  execution_note: string
  observation_note: string
  items: Array<{
    metric: string
    name: string
    recorded: boolean
    status?: string | null
    statistics: Record<string, unknown>
    reason?: string | null
    reason_note: string
    requirements: string
    advice: string
    binding_context?: {recorded: boolean; complete?: boolean; engine_count?: number; note: string}
  }>
  coverage: Array<{component: string; status: string; impact: string}>
}
export interface InspectionFact {
  id: string
  check: string
  check_name: string
  asset_id: string
  asset_name: string
  status: string
  summary: string
  checked_at?: string | null
  window_start?: string | null
  window_end?: string | null
  quality: {state?: string; pending_confirmation?: boolean}
  evidence_gaps: string[]
  measurements: FactMeasurement[]
  host_diagnostics?: HostDiagnosticPresentation
  risks: Array<{id: string; title: string; status: string; severity: string; state_source: 'CURRENT'}>
}
export interface InspectionFactReport {
  source: 'CODE'
  inspection_run_id: string
  check_count: number
  status_counts: Record<string, number>
  checks: InspectionFact[]
  omitted_count: number
  risk_state_note: string
}
export async function getDashboardFacts(environmentId: string, runId?: string) {
  return (await apiClient.get<InspectionFactReport>('/dashboard/facts', {params: {environment_id: environmentId, ...(runId ? {inspection_run_id: runId} : {})}})).data
}
