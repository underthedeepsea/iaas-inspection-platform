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
}

export async function getRules() {
  return (await apiClient.get<{ items: RuleDefinition[] }>('/rules')).data
}
