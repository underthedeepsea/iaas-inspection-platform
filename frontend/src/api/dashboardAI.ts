import { apiClient } from './http'
import type { AnalysisSource } from './resources'

export interface DashboardAnswer {
  prompt?: {key: string; revision: number}
  saved?: {message_id: string; conversation_id: string; generated_at: string; created_at: string; environment_id: string; inspection_run_id: string; execution_id?: string | null; audit_id?: string | null}
  fact_cutoff?: string | null
  scope_note?: string
  answer: string
  confidence: number | null
  ai_status?: 'ACCEPTED' | 'INVALID_PROTOCOL'
  grounded_report?: {
    source: 'CODE'
    coverage_text: string
    comparison_text: string
    ai_status: 'ACCEPTED' | 'INVALID_PROTOCOL'
    accepted_count: number
    checks: Array<{id: string; asset_name: string; source: 'CODE'; facts_text: string; ai_note: string; ai: null | {source: 'AI'; check_id: string; impact: string; next_check: string}}>
  }
  inspection_run_id: string
  source: AnalysisSource
  references: Array<{ type: 'CHECK_RESULT' | 'CODE_PLUGIN' | 'RISK'; id: string; label: string; source: 'CODE' }>
  selected_count?: number
  omitted_count?: number
  check_count?: number
  truncated?: boolean
}
export async function askDashboard(environmentId: string, question: string, runId?: string) {
  return (await apiClient.post<DashboardAnswer>('/dashboard/ask', {environment_id:environmentId,question,...(runId ? {inspection_run_id:runId} : {})})).data
}

export type DashboardStreamEvent =
  | { type: 'facts'; data: import('./inspectionFacts').InspectionFactReport }
  | { type: 'status'; data: { stage: 'generating' | 'validating' } }
  | { type: 'progress'; data: { fragments: number; content_bytes: number } }

const streamFailure = () => new Error('解读连接未完整结束，请重试。CODE 巡检事实已保留。')

export async function streamDashboard(
  environmentId: string, question: string, runId: string | undefined,
  signal: AbortSignal, onEvent: (event: DashboardStreamEvent) => void,
): Promise<DashboardAnswer> {
  const controller = new AbortController()
  const abort = () => controller.abort(signal.reason)
  signal.addEventListener('abort', abort, {once: true})
  if (signal.aborted) abort()
  const deadline = setTimeout(() => controller.abort(new Error('解读等待超过 130 秒，请重试。CODE 巡检事实已保留。')), 130_000)
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  try {
    const response = await fetch('/api/v1/dashboard/ask/stream', {
      method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'text/event-stream'},
      body: JSON.stringify({environment_id: environmentId, question, ...(runId ? {inspection_run_id: runId} : {})}),
      signal: controller.signal,
    })
    if (!response.ok) {
      let body: unknown
      try { body = await response.json() } catch { throw streamFailure() }
      throw {response: {data: body}}
    }
    if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) throw streamFailure()
    reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8', {fatal: true})
    let buffer = '', wireBytes = 0, sawFacts = false
    let factIds = new Set<string>()
    let result: DashboardAnswer | null = null, error: string | null = null
    const frame = (text: string): DashboardAnswer | null => {
      let name = ''
      const data: string[] = []
      for (const line of text.split(/\r?\n/)) {
        if (line.startsWith(':') || !line) continue
        if (line.startsWith('event:')) name = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
        else throw streamFailure()
      }
      if (!name && !data.length) return null
      const value = JSON.parse(data.join('\n'))
      if (!value || typeof value !== 'object') throw streamFailure()
      if (!sawFacts && name !== 'facts' && name !== 'error') throw streamFailure()
      if ((result || error) && name !== 'done') throw streamFailure()
      if (name === 'facts') {
        if ((runId && value.inspection_run_id !== runId) || sawFacts || value.source !== 'CODE' || !Array.isArray(value.checks) || typeof value.check_count !== 'number') throw streamFailure()
        factIds = new Set(value.checks.map((row: {id: string}) => row.id))
        sawFacts = true
        onEvent({type: 'facts', data: value})
      } else if (name === 'status') {
        if (!['generating', 'validating'].includes(value.stage)) throw streamFailure()
        onEvent({type: 'status', data: value})
      } else if (name === 'progress') {
        if (![value.fragments, value.content_bytes].every(n => Number.isSafeInteger(n) && n >= 0)) throw streamFailure()
        onEvent({type: 'progress', data: value})
      } else if (name === 'result') {
        // Only the server's grounded, accepted report is a displayable result.
        if (!sawFacts || value.ai_status !== 'ACCEPTED' || value.grounded_report?.source !== 'CODE'
          || value.grounded_report?.ai_status !== 'ACCEPTED' || !Array.isArray(value.grounded_report?.checks)
          || !Array.isArray(value.references) || !value.source || typeof value.inspection_run_id !== 'string'
          || (runId && value.inspection_run_id !== runId)) throw streamFailure()
        if (value.references.some((ref: {type: string; id: string}) => ref.type !== 'CHECK_RESULT' || !factIds.has(ref.id)) || value.grounded_report.checks.some((row: {id: string}) => !factIds.has(row.id))) throw streamFailure()
        result = value
      } else if (name === 'error') {
        error = typeof value.message === 'string' ? value.message : streamFailure().message
      } else if (name === 'done') {
        if (value.outcome === 'error' && error) throw new Error(error)
        if (value.outcome !== 'success' || !result || error) throw streamFailure()
        return result
      } else throw streamFailure()
      return null
    }
    while (true) {
      const chunk = await reader.read()
      if (controller.signal.aborted) throw controller.signal.reason
      if (chunk.done) {
        buffer += decoder.decode()
        throw streamFailure() // EOF never substitutes for the done event.
      }
      wireBytes += chunk.value.byteLength
      if (wireBytes > 4 * 1024 * 1024) throw streamFailure()
      buffer += decoder.decode(chunk.value, {stream: true})
      let delimiter: RegExpExecArray | null
      while ((delimiter = /\r?\n\r?\n/.exec(buffer))) {
        const text = buffer.slice(0, delimiter.index)
        buffer = buffer.slice(delimiter.index + delimiter[0].length)
        const answer = frame(text)
        if (answer) return answer
      }
      if (buffer.length > 2 * 1024 * 1024) throw streamFailure()
    }
  } catch (failure) {
    if (controller.signal.aborted) throw controller.signal.reason ?? failure
    if (failure instanceof SyntaxError || failure instanceof TypeError) throw streamFailure()
    throw failure
  } finally {
    clearTimeout(deadline)
    signal.removeEventListener('abort', abort)
    if (reader) {
      try { await reader.cancel() } catch { /* Aborted fetch may have already closed the body. */ }
      reader.releaseLock()
    }
    controller.abort()
  }
}

export async function getSavedDashboard(environmentId: string, runId: string) {
  return (await apiClient.get<{status: 'SAVED' | 'EMPTY'; answer: DashboardAnswer | null; saved: DashboardAnswer['saved']}>(`/inspection-runs/${runId}/explanations/latest`, {params: {environment_id: environmentId}})).data
}
