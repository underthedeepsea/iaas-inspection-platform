import type { Investigation, InvestigationEvent } from '../../api/investigations'

export function AIAnalysisSummary({
  investigation,
  events,
}: {
  investigation: Investigation | null
  events: InvestigationEvent[]
}) {
  const terminal = [...events].reverse().find((event) => (
    event.event_type === 'analysis.completed'
    || event.event_type === 'analysis.failed'
    || event.event_type === 'turn.completed'
    || event.event_type === 'turn.error'
  ))
  const resultEvent = [...events].reverse().find((event) => (
    event.event_type === 'analysis.completed'
    || event.event_type === 'analysis.failed'
    || event.event_type === 'assistant.final'
  ))
  const persistedResult = investigation?.result && Object.keys(investigation.result).length
    ? investigation.result
    : undefined
  const summary = investigation?.conclusion || String(resultEvent?.payload.summary ?? terminal?.payload.summary ?? '')
  const result = persistedResult ?? resultEvent?.payload ?? terminal?.payload
  const comparisons = listValue(result?.comparisons)
  const rootCauses = listValue(result?.root_cause_candidates)
  const priorityActions = listValue(result?.priority_actions)
  const evidenceGaps = listValue(result?.evidence_gaps)
  const confidence = investigation?.confidence ?? numberValue(resultEvent?.payload.confidence ?? terminal?.payload.confidence)
  const status = terminal
    ? String(terminal.payload.status ?? (terminal.event_type === 'analysis.failed' || terminal.event_type === 'turn.error' ? 'FAILED' : 'RESOLVED'))
    : investigation?.status ?? '执行中'
  return (
    <section className="ai-summary">
      <div className="section-heading"><div><span className="eyebrow">L1 · DECISION</span><h3>综合判断</h3></div><span className="mode-badge">只读调查</span></div>
      <p className="decision-copy">{summary || '分析结果将在时间线完成后显示。'}</p>
      <div className="ai-structured-grid">
        <StructuredSection title="相比上一轮" items={comparisons} empty="暂无对比数据" />
        <StructuredSection title="潜在共因" subtitle="Root Cause Candidates" items={rootCauses} empty="暂无共因候选" />
        <StructuredSection title="建议优先级" items={priorityActions} empty="暂无优先行动" />
        <StructuredSection title="Evidence Gaps" items={evidenceGaps} empty="暂无证据缺口" />
      </div>
      <div className="definition-list ai-summary-meta"><div><dt>置信度</dt><dd>{confidence == null ? '—' : `${Math.round(Number(confidence) * 100)}%`}</dd></div><div><dt>调查状态</dt><dd>{status}</dd></div></div>
    </section>
  )
}

function listValue(value: unknown) {
  return Array.isArray(value) ? value : []
}

function numberValue(value: unknown) {
  return typeof value === 'number' ? value : null
}

function displayValue(value: unknown) {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>
    if (item.metric != null) return `${String(item.metric)}：${String(item.current ?? '—')}（上一轮 ${String(item.previous ?? '—')}）`
    if (item.title != null && item.action != null) return `${String(item.title)}：${String(item.action)}`
    if (item.priority != null && item.action != null) return `${String(item.priority)} · ${String(item.action)}`
    if (item.title != null) return String(item.title)
    try { return JSON.stringify(value) }
    catch { return '结构化结果' }
  }
  return String(value ?? '—')
}

function StructuredSection({ title, subtitle, items, empty }: { title: string; subtitle?: string; items: unknown[]; empty: string }) {
  return <section className="ai-structured-section"><h4>{title}</h4>{subtitle ? <small>{subtitle}</small> : null}{items.length ? <ul>{items.map((item, index) => <li key={`${title}-${index}`}>{displayValue(item)}</li>)}</ul> : <p>{empty}</p>}</section>
}
