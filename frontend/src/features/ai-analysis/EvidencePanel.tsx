import type { InvestigationEvent } from '../../api/investigations'

export function EvidencePanel({ events }: { events: InvestigationEvent[] }) {
  const evidenceEvents = events.filter((event) => event.event_type === 'evidence.created')
  const completedTools = events
    .filter((event) => event.event_type === 'tool.completed')
    .map((event) => String(event.payload.capability_id ?? event.payload.tool ?? 'evidence'))
  const count = evidenceEvents.length || completedTools.length
  return (
    <section className="ai-evidence">
      <div className="section-heading"><div><span className="eyebrow">L2 · EVIDENCE</span><h3>可用证据</h3></div><span className="legend">{count} 项已完成</span></div>
      {evidenceEvents.length ? (
        <div className="evidence-list">
          {evidenceEvents.map((event) => <EvidenceItem event={event} key={event.sequence} />)}
        </div>
      ) : completedTools.length ? (
        <div className="evidence-list">{completedTools.map((tool, index) => <article className="evidence-item" key={`${tool}-${index}`}><strong>{tool}</strong><p>证据工具已完成，可用于支持当前判断。</p></article>)}</div>
      ) : <p className="muted">等待证据工具完成。</p>}
    </section>
  )
}

function EvidenceItem({ event }: { event: InvestigationEvent }) {
  const payload = event.payload
  const type = String(payload.evidence_type ?? 'TOOL_RESULT')
  const key = String(payload.evidence_key ?? payload.capability_id ?? 'evidence')
  const relatedFindings = Array.isArray(payload.related_finding_ids) ? payload.related_finding_ids.join(', ') : ''
  const relatedRisks = Array.isArray(payload.related_risk_ids) ? payload.related_risk_ids.join(', ') : ''
  const value = payload.value == null ? '' : typeof payload.value === 'string' ? payload.value : JSON.stringify(payload.value)
  return (
    <article className="evidence-item">
      <header><strong>{type} · {key}</strong>{payload.confidence == null ? null : <span className="mode-badge">置信度 {Math.round(Number(payload.confidence) * 100)}%</span>}</header>
      <p>{String(payload.summary ?? '暂无证据摘要。')}</p>
      <small>来源：{String(payload.source ?? '—')} · 时间：{String(payload.observed_at ?? payload.window_end ?? '—')}</small>
      {value ? <small>值：{value}</small> : null}
      {relatedFindings ? <small>关联 Finding：{relatedFindings}</small> : null}
      {relatedRisks ? <small>关联风险：{relatedRisks}</small> : null}
    </article>
  )
}
