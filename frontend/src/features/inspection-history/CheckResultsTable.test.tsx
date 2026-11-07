import { fireEvent, render, screen } from '@testing-library/react'
import { CheckResultsTable } from './CheckResultsTable'
it('shows the actual check facts and expandable evidence', () => {
  render(<CheckResultsTable results={[{source:{type:'CODE',plugin_id:'llm-ttft-slo',plugin_name:'LLM TTFT SLO',plugin_version:'1.0.0',engine:'PYTHON_RULE'},id:'c',inspection_item_code:'llm.ttft_slo',inspection_item_name:'TTFT P95',asset_id:'a',asset_name:'LLM 0',status:'FAIL',summary:'超出阈值',observed_value:{p95_ms:220},expected_value:{threshold_ms:180},evidence:{sample_count:6},checked_at:'2026-09-10T00:00:00Z'}]} />)
  expect(screen.getByText('发现异常')).toBeInTheDocument()
  expect(screen.getByText('220')).toBeInTheDocument()
  expect(screen.getByText('CODE').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText('LLM TTFT SLO')).toBeInTheDocument()
  expect(screen.getByText('v1.0.0')).toBeInTheDocument()
  fireEvent.click(screen.getByText('展开证据'))
  expect(screen.getByText('超出阈值')).toBeVisible()
  expect(screen.getByText('Asset：a')).toBeVisible()
})


it('shows recorded UNKNOWN reason, impact and next step without opening evidence', () => {
 render(<CheckResultsTable results={[{id:'unknown',inspection_item_code:'hardware.host_health',inspection_item_name:'主机',asset_id:'a',asset_name:'Host',status:'UNKNOWN',summary:'硬件快照已超过有效时限',observed_value:{},expected_value:{},evidence:{reason_code:'SNAPSHOT_STALE',impact:'仅影响本项',next_step:'恢复来源后复查'},checked_at:'time'}]} />)
 expect(screen.getByText('硬件快照已超过有效时限')).toBeVisible()
 expect(screen.getByText(/原因：快照已超过有效时限/)).toBeVisible()
 expect(screen.getByText('仅影响本项')).toBeVisible()
 expect(screen.getByText('恢复来源后复查')).toBeVisible()
})
