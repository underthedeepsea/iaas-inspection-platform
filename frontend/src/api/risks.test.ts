import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './http'
import { getRiskEvidence, getRiskTimeline, getRisk, getRisks } from './risks'

afterEach(() => vi.restoreAllMocks())

describe('risk API contract', () => {
  it('keeps lifecycle filters in the risk list request', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } } as never)

    await getRisks({ severity: 'P1', status: 'PENDING_ACTION' })

    expect(get).toHaveBeenCalledWith('/risks', { params: { severity: 'P1', status: 'PENDING_ACTION', page_size: 100 } })
  })

  it('scopes the risk list to the selected environment', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } } as never)

    await getRisks({ environmentId: 'staging' })

    expect(get).toHaveBeenCalledWith('/risks', { params: { environment_id: 'staging', page_size: 100 } })
  })

  it('loads risk detail, lifecycle, and evidence through their public endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} } as never)

    await getRisk('risk-1')
    await getRiskTimeline('risk-1')
    await getRiskEvidence('risk-1')

    expect(get).toHaveBeenNthCalledWith(1, '/risks/risk-1')
    expect(get).toHaveBeenNthCalledWith(2, '/risks/risk-1/timeline')
    expect(get).toHaveBeenNthCalledWith(3, '/risks/risk-1/evidence', { params: { limit: 50 } })
  })
})
