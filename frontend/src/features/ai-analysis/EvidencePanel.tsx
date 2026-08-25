import type { InvestigationEvent } from '../../api/investigations'

export function EvidencePanel({ events }: { events: InvestigationEvent[] }) {
  const completedTools = events
    .filter((event) => event.event_type === 'tool.completed')
    .map((event) => String(event.payload.tool ?? 'evidence'))
  return (
    <section>
      <h3>可用证据</h3>
      {completedTools.length ? <ul>{completedTools.map((tool, index) => <li key={`${tool}-${index}`}>{tool}</li>)}</ul> : <p>等待证据工具完成。</p>}
    </section>
  )
}

