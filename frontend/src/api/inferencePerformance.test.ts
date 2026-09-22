import { expect, it, vi } from 'vitest'

import { apiClient } from './http'
import { getInferenceProfile } from './inferencePerformance'

it('requests the latest performance profile for its environment', async () => {
  const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: {} } as never)
  await getInferenceProfile('env-1')
  expect(get).toHaveBeenCalledWith('/inference-performance/engines/latest/profile', { params: { environment_id: 'env-1' } })
})
