import type { InvestigationEvent } from '../../api/investigations'

export function EvidencePanel({ events }: { events: InvestigationEvent[] }) {
  const completedTools = events
    .filter((event) => event.event_type === 'tool.completed')
    .map((event) => String(event.payload.tool ?? 'evidence'))
  return (
    <section className="ai-evidence">
      <div className="section-heading"><div><span className="eyebrow">L2 · EVIDENCE</span><h3>可用证据</h3></div><span className="legend">{completedTools.length} 项已完成</span></div>
      {completedTools.length ? <div className="evidence-list">{completedTools.map((tool, index) => <article className="evidence-item" key={`${tool}-${index}`}><strong>{tool}</strong><p>证据工具已完成，可用于支持当前判断。</p></article>)}</div> : <p className="muted">等待证据工具完成。</p>}
    </section>
  )
}
