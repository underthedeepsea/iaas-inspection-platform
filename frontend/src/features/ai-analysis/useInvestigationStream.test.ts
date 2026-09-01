import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { useInvestigationStream } from './useInvestigationStream'

class FakeEventSource {
  static instance: FakeEventSource
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  close = vi.fn()
  url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instance = this
  }

  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener as (event: MessageEvent<string>) => void)
  }

  emit(event: { sequence: number; event_type: string; status: string; payload: Record<string, unknown> }) {
    this.listeners.get(event.event_type)?.(new MessageEvent(event.event_type, {
      data: JSON.stringify(event),
      lastEventId: String(event.sequence),
    }))
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useInvestigationStream', () => {
  it('merges history and live events by sequence without duplicates', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: {
        items: [
          { sequence: 1, event_type: 'context.ready', status: 'COMPLETED', data: {} },
          { sequence: 2, event_type: 'history.loaded', status: 'COMPLETED', data: {} },
        ],
      },
    } as never)

    const { result } = renderHook(() => useInvestigationStream('investigation-1'))

    await waitFor(() => expect(result.current.events).toHaveLength(2))
    expect(FakeEventSource.instance.url).toBe('/api/v1/investigations/investigation-1/events/stream')

    act(() => {
      FakeEventSource.instance.emit({ sequence: 2, event_type: 'history.loaded', status: 'COMPLETED', payload: {} })
      FakeEventSource.instance.emit({ sequence: 3, event_type: 'analysis.completed', status: 'COMPLETED', payload: {} })
    })

    await waitFor(() => expect(result.current.events).toHaveLength(3))
    expect(result.current.events.map((event) => event.sequence)).toEqual([1, 2, 3])
  })
})
