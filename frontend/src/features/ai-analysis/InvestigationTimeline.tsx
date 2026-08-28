import type { InvestigationEvent } from '../../api/investigations'
import { Timeline } from 'antd'

const labels: Record<string, string> = {
  'context.ready': '上下文已准备',
  'history.loaded': '历史数据已加载',
  'tool.started': '证据工具运行中',
  'tool.completed': '证据工具已完成',
  'tool.failed': '证据工具失败',
  'evidence.created': '证据已创建',
  'analysis.started': '分析生成中',
  'analysis.completed': '分析已完成',
  'analysis.failed': '分析失败',
}

export function InvestigationTimeline({ events }: { events: InvestigationEvent[] }) {
  return (
    <Timeline
      aria-label="AI 分析时间线"
      className="timeline ai-timeline"
      items={events.map((event) => ({
        className: `ai-timeline-item status-${event.status.toLowerCase()}`,
        color: event.status === 'FAILED' ? 'red' : 'orange',
        children: <><span>{labels[event.event_type] ?? event.event_type}</span>{event.status === 'FAILED' ? <span className="timeline-failure">失败</span> : null}</>,
        key: event.sequence,
      }))}
    />
  )
}
