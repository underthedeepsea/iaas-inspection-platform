import type { InvestigationEvent } from '../../api/investigations'

const labels: Record<string, string> = {
  'context.ready': '上下文已准备',
  'history.loaded': '历史数据已加载',
  'tool.started': '证据工具运行中',
  'tool.completed': '证据工具已完成',
  'tool.failed': '证据工具失败',
  'analysis.started': '分析生成中',
  'analysis.completed': '分析已完成',
}

export function InvestigationTimeline({ events }: { events: InvestigationEvent[] }) {
  return (
    <ol aria-label="AI 分析时间线" style={{ display: 'grid', gap: 10, listStyle: 'none', margin: 0, padding: 0 }}>
      {events.map((event) => (
        <li data-status={event.status.toLowerCase()} key={event.sequence} style={{ alignItems: 'center', display: 'flex', gap: 10 }}>
          <span aria-hidden="true" style={{ color: event.status === 'FAILED' ? '#dc2626' : event.status === 'COMPLETED' ? '#16a34a' : '#f97316' }}>●</span>
          <span>{labels[event.event_type] ?? event.event_type}</span>
          {event.status === 'FAILED' ? <span style={{ color: '#dc2626', fontSize: 12 }}>失败</span> : null}
        </li>
      ))}
    </ol>
  )
}

