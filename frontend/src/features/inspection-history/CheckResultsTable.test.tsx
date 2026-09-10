import { fireEvent, render, screen } from '@testing-library/react'
import { CheckResultsTable } from './CheckResultsTable'
it('shows the actual check facts and expandable evidence', () => {
  render(<CheckResultsTable results={[{id:'c',inspection_item_code:'llm.ttft_slo',inspection_item_name:'TTFT P95',asset_id:'a',asset_name:'LLM 0',status:'FAIL',summary:'超出阈值',observed_value:{p95_ms:220},expected_value:{threshold_ms:180},evidence:{sample_count:6},checked_at:'2026-09-10T00:00:00Z'}]} />)
  expect(screen.getByText('FAIL')).toBeInTheDocument()
  expect(screen.getByText('{"p95_ms":220}')).toBeInTheDocument()
  fireEvent.click(screen.getByText('展开证据'))
  expect(screen.getByText('超出阈值')).toBeVisible()
  expect(screen.getByText('Asset：a')).toBeVisible()
})
