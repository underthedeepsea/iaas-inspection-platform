import { apiClient } from './http'

export interface CodePlugin {
  plugin_id: string
  name: string
  version: string
  rule_code: string
  resource_types: string[]
  engine: 'PYTHON_RULE'
  status: 'ACTIVE'
  deterministic: true
  description: string
}
export async function getCodePlugins() {
  return (await apiClient.get<{ items: CodePlugin[] }>('/code-plugins')).data
}

export interface RuleDefinition {
  rule_code: string
  name: string
  rule_version: string
  plugin_id: string
  plugin_version: string
  operation_key: string
  resource_types: string[]
  parameters: Record<string, unknown>
  status: 'ACTIVE'
  deterministic: true
  description: string
  input_source?: string
  input_contract?: string
  supported_metrics?: SupportedMetric[]
  judgment_rules?: JudgmentRule[]
  policy_profiles?: RulePolicyProfile[]
}

export interface SupportedMetric {
  field: string
  input_path: string
  name: string
  unit: string
  range: string
  purpose: string
}

export interface JudgmentRule {
  title: string
  items: string[]
}

export interface RulePolicyProfile {
  label: string
  level: 'DEFAULT' | 'ENGINE' | 'ENGINE_MODEL'
  engine_type: string | null
  model_name: string | null
  overrides: Record<string, unknown>
  policy: {
    fixed: Record<string, { warning: number; critical: number }>
    dynamic: { warning_z: number; critical_z: number; warning_change_ratio: number; critical_change_ratio: number }
    trend: { window_minutes: number; watch_change_ratio: number; degrading_change_ratio: number }
    persistence: { consecutive_hits: number }
    quality?: { max_age_seconds?: number; max_gap_seconds?: number }
  }
  fixed_thresholds: { field: string; unit: string; warning: number; critical: number }[]
}

export async function getRules() {
  return (await apiClient.get<{ items: RuleDefinition[] }>('/rules')).data
}
