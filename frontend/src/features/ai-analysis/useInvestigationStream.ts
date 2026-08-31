import { useEffect, useState } from 'react'

import { getInvestigationEvents, investigationEventsUrl, type InvestigationEvent } from '../../api/investigations'

export const INVESTIGATION_EVENT_TYPES = [
  'context.ready',
  'history.loaded',
  'tool.started',
  'tool.completed',
  'tool.failed',
  'evidence.created',
  'analysis.started',
  'analysis.completed',
  'analysis.failed',
  'turn.started',
  'assistant.final',
  'turn.completed',
  'turn.error',
] as const

function isTerminalEvent(eventType: string) {
  return eventType === 'analysis.completed'
    || eventType === 'analysis.failed'
    || eventType === 'turn.completed'
    || eventType === 'turn.error'
}

function mergeEvents(current: InvestigationEvent[], incoming: InvestigationEvent[]) {
  const bySequence = new Map(current.map((event) => [event.sequence, event]))
  for (const event of incoming) bySequence.set(event.sequence, event)
  return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence)
}

export function useInvestigationStream(investigationId?: string) {
  const [events, setEvents] = useState<InvestigationEvent[]>([])
  const [recovering, setRecovering] = useState(false)

  useEffect(() => {
    if (!investigationId) return
    setEvents([])
    let active = true
    void getInvestigationEvents(investigationId)
      .then((history) => {
        if (!active) return
        setEvents((current) => mergeEvents(current, history))
        setRecovering(false)
      })
      .catch(() => {
        if (active) setRecovering(true)
      })
    if (typeof EventSource === 'undefined') {
      setRecovering(true)
      return () => { active = false }
    }
    const source = new EventSource(investigationEventsUrl(investigationId))
    const handle = (event: Event) => {
      const message = event as MessageEvent<string>
      try {
        const data = JSON.parse(message.data) as InvestigationEvent
        setEvents((current) => mergeEvents(current, [data]))
        setRecovering(false)
        if (isTerminalEvent(data.event_type)) source.close()
      } catch {
        setRecovering(true)
      }
    }
    source.onerror = () => setRecovering(true)
    for (const type of INVESTIGATION_EVENT_TYPES) source.addEventListener(type, handle)
    return () => { active = false; source.close() }
  }, [investigationId])

  return { events, recovering }
}
