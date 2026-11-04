import { apiClient } from './http'

export interface ProfileMetric {
  series?: PortraitPoint[]; series_truncated?: boolean; series_note?: string
  value_kind?: 'POINT' | 'POINT_AGGREGATE' | 'WINDOW_STATISTIC'; collected_at?: string | null; participating_collected_at?: string[]; window_start?: string | null; window_end?: string | null
  key: string; label: string; unit: string; current: number | null; latest_observed: number | null; observed_at: string | null; state: string
  history: { n: number; start: string | null; end: string | null; median: number | null; min: number | null; max: number | null; state: string }
  difference: number | null; missing_context: string[]; coverage?: { covered: number; total: number }
  high_observation: { at: string; value: number } | null; low_observation: { at: string; value: number } | null
}
export interface ProfileEntity { portrait_id?: string; asset_id?: string | null; relationships?: PortraitRelation[]; id: string; name: string; metrics: ProfileMetric[]; context: Record<string, unknown>; missing_context: string[]; freshness: string; current_asset_configuration?: Record<string, unknown>; note?: string }
export interface HostRiskItem { key: string; level: string; current: number | null; unit: string; rule_id: string; rule_version: string; rule?: Record<string, unknown>; reason?: string; confirmation_points?: number | null; confirmation_required?: number | null; collected_at: string | null }
export interface HostRisk { level: 'CRITICAL' | 'WARNING' | 'UNKNOWN' | 'NORMAL'; complete: boolean; incomplete: boolean; triggers: HostRiskItem[]; items: HostRiskItem[]; missing: string[]; sample_time: string | null }
export interface RiskSummary { counts: Record<string, number>; risk_hosts: number; incomplete: number; coverage: { covered: number; total: number }; metric_coverage: Record<string, { covered: number; total: number }>; truncated?: boolean }
export interface ProfileNode extends ProfileEntity { risk?: HostRisk; control_plane_group?: string; roles: string[]; shared_load: boolean; stable_identity: string; cpu_cores: number | null; memory_semantics: string; frozen_diagnostics: Record<string, unknown>; diagnostic_note: string }
export interface ProfileGroup { risk?: RiskSummary; node_ids: string[]; node_count: number; metrics: ProfileMetric[]; window_aligned: boolean; note: string }
export interface ProfileCluster { portrait_id?: string; relationships?: PortraitRelation[]; id: string; name: string; control_plane_deployment: string; total: ProfileGroup; classified?: ProfileGroup; groups: (ProfileGroup & { role: string })[]; shared_nodes: string[] }
export interface PerformanceProfileData { resource_type: string; generated_at: string; history_days: number; llm: ProfileEntity[]; nodes: ProfileNode[]; clusters: ProfileCluster[]; note: string; truncated: boolean; deployment_edit: { writable: boolean; note: string } }
export async function getPerformanceProfile(environmentId: string, resourceCode: string) {
  return (await apiClient.get<PerformanceProfileData>('/hardware-health/performance-profiles', { params: { environment_id: environmentId, resource_type: resourceCode } })).data
}
export async function saveControlPlaneDeployment(environmentId: string, clusterId: string, deployment: string) {
  return (await apiClient.patch(`/hardware-health/clusters/${encodeURIComponent(clusterId)}/deployment`, { control_plane_deployment: deployment }, { params: { environment_id: environmentId } })).data
}

export type PortraitKind = 'cluster' | 'node' | 'llm'
export interface PortraitPoint {
  snapshot_id: string; at: string | null; collected_at: string | null; window_start: string | null; window_end: string | null
  value: number | null; unit: string; source: string | null; value_kind: string; is_current: boolean; quality: string; continuity: 'UNKNOWN'; reference_bounds: null
}
export interface PortraitRelation { kind: PortraitKind; id: string; name: string }
export async function getPortraits(environmentId: string, detail?: { kind: string; id: string }) {
  return (await apiClient.get<PerformanceProfileData>('/hardware-health/performance-profiles', { params: { environment_id: environmentId, resource_type: 'CLUSTER', view: 'portraits', ...(detail ?? {}) } })).data
}
