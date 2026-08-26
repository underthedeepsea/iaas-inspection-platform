import { useEffect, useState } from 'react'

import { investigationEventsUrl, type InvestigationEvent } from '../../api/investigations'

export const INVESTIGATION_EVENT_TYPES = [
  'context.ready',
  'history.loaded',
  'tool.started',
  'tool.completed',
  'tool.failed',
  'analysis.started',
  'analysis.completed',
  'analysis.failed',
] as const

export function useInvestigationStream(investigationId?: string) {
  const [events, setEvents] = useState<InvestigationEvent[]>([])
  const [recovering, setRecovering] = useState(false)

  useEffect(() => {
    if (!investigationId) return
    setEvents([])
    if (typeof EventSource === 'undefined') {
      setRecovering(true)
      return
    }
    const source = new EventSource(investigationEventsUrl(investigationId))
    const handle = (event: Event) => {
      const message = event as MessageEvent<string>
      try {
        const data = JSON.parse(message.data) as InvestigationEvent
        setEvents((current) => current.some((item) => item.sequence === data.sequence) ? current : [...current, data].sort((a, b) => a.sequence - b.sequence))
        setRecovering(false)
        if (data.event_type === 'analysis.completed' || data.event_type === 'analysis.failed') source.close()
      } catch {
        setRecovering(true)
      }
    }
    source.onerror = () => setRecovering(true)
    for (const type of INVESTIGATION_EVENT_TYPES) source.addEventListener(type, handle)
    return () => source.close()
  }, [investigationId])

  return { events, recovering }
}
