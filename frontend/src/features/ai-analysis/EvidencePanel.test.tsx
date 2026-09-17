import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { EvidencePanel } from './EvidencePanel'

describe('EvidencePanel', () => {
  it('renders evidence type, source, value, confidence and related records', () => {
    render(
      <EvidencePanel
        events={[{
          sequence: 1,
          event_type: 'evidence.created',
          status: 'COMPLETED',
          payload: {
            evidence_key: 'queue.depth:1',
            evidence_type: 'METRIC',
            source: 'scheduler.metrics',
            observed_at: '2026-08-25T00:00:00Z',
            value: { last: 90 },
            summary: '队列深度连续升高',
            confidence: 0.93,
            related_finding_ids: ['finding-1'],
            related_risk_ids: ['risk-1'],
          },
        }]}
      />,
    )

    expect(screen.getByText('METRIC · queue.depth:1')).toBeInTheDocument()
    expect(screen.getByText(/scheduler\.metrics/)).toBeInTheDocument()
    expect(screen.getByText('队列深度连续升高')).toBeInTheDocument()
    expect(screen.getByText(/置信度 93%/)).toBeInTheDocument()
    expect(screen.getByText(/finding-1/)).toBeInTheDocument()
    expect(screen.getByText(/risk-1/)).toBeInTheDocument()
  })
})
