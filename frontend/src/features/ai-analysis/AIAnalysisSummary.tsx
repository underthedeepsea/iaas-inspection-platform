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
    <section style={{ background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 12, padding: 16 }}>
      <h3 style={{ marginTop: 0 }}>综合判断</h3>
      <p>{summary || '分析结果将在 timeline 完成后显示。'}</p>
      <div style={{ color: '#6b7280', fontSize: 13 }}>置信度：{investigation?.confidence == null ? '—' : `${Math.round(investigation.confidence * 100)}%`}</div>
    </section>
  )
}

