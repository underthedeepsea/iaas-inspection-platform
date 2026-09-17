import { apiClient } from './http'
import type { AnalysisSource } from './resources'

export interface DashboardAnswer {
  answer: string
  confidence: number
  inspection_run_id: string
  source: AnalysisSource
  references: Array<{ type: 'CHECK_RESULT' | 'CODE_PLUGIN' | 'RISK'; id: string; label: string; source: 'CODE' }>
  truncated?: boolean
}
export async function askDashboard(environmentId: string, question: string, runId?: string) {
  return (await apiClient.post<DashboardAnswer>('/dashboard/ask', {environment_id:environmentId,question,...(runId ? {inspection_run_id:runId} : {})})).data
}
