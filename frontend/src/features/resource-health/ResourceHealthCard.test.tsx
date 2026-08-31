import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { ResourceType } from '../../api/resources'
import { ResourceHealthCard } from './ResourceHealthCard'

const baseResource: ResourceType = {
  code: 'CONTROL_PLANE',
  name: '控制面',
  description: '资源对象健康状态',
  icon: 'control-plane',
  asset_count: 7,
  assets_total: 7,
  assets_covered: 7,
  coverage_rate: 1,
  inspection_item_count: 1,
  health_score: 88,
  risk_count: 1,
  p1_count: 0,
  p2_count: 1,
  last_inspection_at: '2026-09-16T00:00:00Z',
}

describe('ResourceHealthCard', () => {
  it.each([
    ['CONTROL_PLANE', 'CP', 'CONTROL PLANE', 'resource-tone-control'],
    ['KVM_CLUSTER', 'KVM', 'VIRTUALIZATION', 'resource-tone-kvm'],
    ['K8S_CLUSTER', 'K8S', 'ORCHESTRATION', 'resource-tone-k8s'],
    ['LLM_RUNTIME', 'LLM', 'INFERENCE', 'resource-tone-llm'],
    ['GPU_POOL', 'GPU', 'ACCELERATOR', 'resource-tone-gpu'],
    ['HOST', 'HOST', 'COMPUTE', 'resource-tone-host'],
  ])('gives %s a visible type identity', (code, short, label, toneClass) => {
    render(
      <MemoryRouter>
        <ResourceHealthCard resource={{ ...baseResource, code, name: code }} />
      </MemoryRouter>,
    )

    expect(screen.getAllByText(short).some((element) => element.classList.contains('resource-card-glyph'))).toBe(true)
    expect(screen.getByText(label)).toHaveClass('resource-card-type')
    expect(screen.getByText(code, { selector: 'strong' }).closest('.resource-card')).toHaveClass(toneClass)
  })
})
