import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { useInspectionRunStream } from './useInspectionRunStream'

class FakeEventSource {
  static instance: FakeEventSource
  onerror: (() => void) | null = null
  close = vi.fn()

  constructor(_url: string) {
    FakeEventSource.instance = this
  }

  addEventListener(_type: string, _listener: EventListener) {}

  triggerError() {
    this.onerror?.()
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useInspectionRunStream', () => {
  it('recovers a PARTIAL polling status as a completed run', async () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { id: 'run-partial', inspection_run_id: 'run-partial', status: 'PARTIAL' },
    } as never)
    const { result } = renderHook(() => useInspectionRunStream('run-partial'))

    act(() => FakeEventSource.instance.triggerError())

    await waitFor(() => expect(get).toHaveBeenCalledWith('/inspection-runs/run-partial'))
    await waitFor(() => expect(result.current.currentStep).toBe('completed'))
    expect(result.current.runStatus).toBe('PARTIAL')
  })
})
