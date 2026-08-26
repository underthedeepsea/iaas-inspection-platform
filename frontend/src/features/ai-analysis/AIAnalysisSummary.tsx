import type { Investigation, InvestigationEvent } from '../../api/investigations'

export function AIAnalysisSummary({
  investigation,
  events,
}: {
  investigation: Investigation | null
  events: InvestigationEvent[]
}) {
  const completed = [...events].reverse().find((event) => event.event_type === 'analysis.completed')
  const summary = investigation?.conclusion || String(completed?.payload.summary ?? '')
  return (
    <section className="ai-summary">
      <div className="section-heading"><div><span className="eyebrow">L1 · DECISION</span><h3>综合判断</h3></div><span className="mode-badge">只读调查</span></div>
      <p className="decision-copy">{summary || '分析结果将在时间线完成后显示。'}</p>
      <div className="definition-list ai-summary-meta"><div><dt>置信度</dt><dd>{investigation?.confidence == null ? '—' : `${Math.round(investigation.confidence * 100)}%`}</dd></div><div><dt>调查状态</dt><dd>{investigation?.status ?? '执行中'}</dd></div></div>
    </section>
  )
}
