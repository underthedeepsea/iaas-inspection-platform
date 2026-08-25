import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './http'
import { getResourceOverview, resourceKeys } from './resources'
import { triggerInspection } from './inspections'

afterEach(() => vi.restoreAllMocks())

describe('frontend API contracts', () => {
  it('sends the manual inspection scope exactly as the backend contract expects', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'run-1' } } as never)

    await triggerInspection({
      environmentId: 'env-1',
      resourceTypes: ['CONTROL_PLANE', 'LLM_RUNTIME'],
      aiMode: 'DEFERRED',
    })

    expect(post).toHaveBeenCalledWith('/inspection-runs/trigger', {
      environment_id: 'env-1',
      scope: { resource_types: ['CONTROL_PLANE', 'LLM_RUNTIME'] },
      trigger_options: { ai_mode: 'DEFERRED' },
    })
  })

  it('keeps environment and resource code in the resource query key', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { resource_type: { code: 'LLM_RUNTIME' } } } as never)

    await getResourceOverview('LLM_RUNTIME', 'env-1')

    expect(resourceKeys.detail('env-1', 'LLM_RUNTIME')).toEqual([
      'resource-types',
      'detail',
      'env-1',
      'LLM_RUNTIME',
    ])
  })
})

