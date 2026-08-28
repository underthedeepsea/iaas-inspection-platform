import { useEffect, useRef, useState } from 'react'

import {
  getInspectionRun,
  inspectionKeys,
  inspectionRunEventsUrl,
  type InspectionRunEvent,
} from '../../api/inspections'
import { queryClient } from '../../app/queryClient'

import {
  initialInspectionProgressState,
  reduceInspectionRunEvent,
  type InspectionProgressState,
} from './InspectionProgress'

export const INSPECTION_RUN_EVENT_TYPES = [
  'scope.resolved',
  'assets.discovered',
  'inspection.started',
  'inspection.item.started',
  'inspection.item.progress',
  'inspection.item.completed',
  'inspection.item.failed',
  'inspection.completed',
  'risk.correlation.started',
  'risk.correlation.completed',
  'ai.admission.started',
  'ai.admission.completed',
  'summary.started',
  'summary.completed',
  'run.completed',
  'run.failed',
] as const

export function useInspectionRunStream(runId: string) {
  const [state, setState] = useState<InspectionProgressState>(initialInspectionProgressState)
  const [recovering, setRecovering] = useState(false)
  const lastEventId = useRef(0)
  useEffect(() => {
    let source: EventSource | null = null
    let pollTimer: number | undefined
    let disposed = false

    const applyEvent = (event: InspectionRunEvent) => {
      if (event.sequence <= lastEventId.current) return
      lastEventId.current = Math.max(lastEventId.current, event.sequence)
      setState((current) => reduceInspectionRunEvent(current, event))
      if (event.event_type === 'run.completed' || event.event_type === 'run.failed') {
        source?.close()
        if (pollTimer !== undefined) window.clearInterval(pollTimer)
        void queryClient.invalidateQueries({ queryKey: inspectionKeys.detail(runId) })
      }
    }

    const poll = async () => {
      setRecovering(true)
      try {
        const run = await getInspectionRun(runId)
        if (run.status === 'SUCCEEDED' || run.status === 'PARTIAL' || run.status === 'FAILED') {
          applyEvent({
            sequence: lastEventId.current + 1,
            event_type: run.status === 'SUCCEEDED' ? 'run.completed' : 'run.failed',
            status: run.status,
            payload: {},
          })
        }
      } catch {
        // Polling is a best-effort recovery path; the durable stream remains
        // the source of truth when the API is temporarily unavailable.
      } finally {
        if (!disposed) setRecovering(false)
      }
    }

    const startPolling = (immediate = true) => {
      if (pollTimer === undefined) {
        if (immediate) void poll()
        pollTimer = window.setInterval(() => void poll(), 5000)
      }
    }

    if (typeof EventSource === 'undefined') {
      startPolling(false)
    } else {
      source = new EventSource(inspectionRunEventsUrl(runId))
      source.onopen = () => setRecovering(false)
      source.onerror = () => startPolling()
      const handle = (event: Event) => {
        const message = event as MessageEvent<string>
        try {
          const data = JSON.parse(message.data) as InspectionRunEvent
          applyEvent({
            ...data,
            sequence: data.sequence || Number(message.lastEventId) || lastEventId.current + 1,
          })
        } catch {
          setRecovering(true)
        }
      }
      for (const type of INSPECTION_RUN_EVENT_TYPES) source.addEventListener(type, handle)
    }

    return () => {
      disposed = true
      source?.close()
      if (pollTimer !== undefined) window.clearInterval(pollTimer)
    }
  }, [queryClient, runId])

  return { ...state, recovering, lastEventId: lastEventId.current }
}
