import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './http'
import { getDashboardToday } from './dashboard'

afterEach(() => vi.restoreAllMocks())

describe('dashboard API contract', () => {
  it('requests the latest daily snapshot for the selected environment', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { snapshot: {} } } as never)

    await getDashboardToday('env-1')

    expect(get).toHaveBeenCalledWith('/dashboard/today', { params: { environment: 'env-1' } })
  })
})
