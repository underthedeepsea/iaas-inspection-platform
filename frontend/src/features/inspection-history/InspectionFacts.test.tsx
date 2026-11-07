import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it } from 'vitest'
import { InspectionFacts } from './InspectionFacts'
import type { FactMeasurement, InspectionFactReport } from '../../api/inspectionFacts'

export const report: InspectionFactReport = {source: 'CODE', inspection_run_id: 'run-1', check_count: 3, status_counts: {FAIL: 1, UNKNOWN: 1, PASS: 1}, omitted_count: 0, risk_state_note: '风险状态是当前状态，检查为历史事实。', checks: [
  {id:'check-1', check:'llm.performance_profile', check_name:'推理性能', asset_id:'asset-1', asset_name:'demo-dynamic / Model-8B', status:'FAIL', summary:'推理性能异常', quality:{state:'READY'}, evidence_gaps:[], checked_at:'2026-10-09T03:23:00Z', window_end:'2026-10-09T03:20:00Z', measurements:[{layer:'DYNAMIC', metric:'ttft.p95_ms', current:339.7773, boundary:308.75866, baseline_median:220.5419}], risks:[{id:'risk-1',title:'推理性能达到严重阈值',status:'RECOVERED',severity:'P1',state_source:'CURRENT'}]},
  {id:'check-idle',check:'llm.performance_profile',check_name:'推理性能',asset_id:'asset-idle',asset_name:'idle-service',status:'UNKNOWN',summary:'有效样本不足',quality:{state:'IDLE'},evidence_gaps:['IDLE'],measurements:[],risks:[]},
  {id:'check-cold',check:'llm.performance_profile',check_name:'推理性能',asset_id:'asset-cold',asset_name:'cold-service',status:'PASS',summary:'固定检查通过',quality:{state:'READY'},evidence_gaps:['DYNAMIC_BASELINE_NOT_READY'],measurements:[],risks:[]},
]}
it('renders resource, actual boundary, historical time and current risk links without AI', () => {
  render(<MemoryRouter><InspectionFacts report={report} environmentId="env-1" /></MemoryRouter>)
  expect(screen.getByText('demo-dynamic / Model-8B')).toBeInTheDocument()
  expect(screen.getByText('339.777 ms')).toBeInTheDocument()
  expect(screen.getByText('308.759 ms')).toBeInTheDocument()
  expect(screen.getByText('220.542 ms')).toBeInTheDocument()
  expect(screen.getByText(/当前 P1 \/ RECOVERED/)).toHaveAttribute('href','/risks/risk-1?environment=env-1')
  expect(screen.getAllByText('检查证据 →')[0]).toHaveAttribute('href','/inspection-runs/run-1?environment=env-1#check-check-1')
  expect(screen.getByText(/当前空闲，缺少有效请求样本/)).toBeInTheDocument()
  expect(screen.getByText(/动态基线尚未就绪/)).toBeInTheDocument()
})
it('marks ECC values as event-time values and reserve ETA separately', () => {
  const hardware: InspectionFactReport = {...report, checks:[{...report.checks[0], check:'hardware.gpu_health', measurements:[{layer:'HARDWARE',code:'ECC_DBE_NEW',current:1,value_semantics:'EVENT',occurred_at:'2026-10-09T03:20:00Z'},{layer:'HARDWARE',code:'XID_UNCLASSIFIED',xid_code:79},{layer:'HARDWARE',code:'SPACE_DECLINE',reserve_bytes:0,seconds_to_reserve:0}]}]}
  render(<MemoryRouter><InspectionFacts report={hardware} environmentId="env-1" /></MemoryRouter>)
  expect(screen.getByText(/事件时数值/)).toBeInTheDocument()
  expect(screen.getByText('1')).not.toHaveAttribute('title')
  expect(screen.getByText('79')).toBeInTheDocument()
  expect(screen.getByText(/事件发生/)).toBeInTheDocument()
  expect(screen.getByText('保留水位 0 B')).toBeInTheDocument()
  expect(screen.getByText('到保留水位 0 秒（不是写满时间）')).toBeInTheDocument()
})

function hostReport(measurements: FactMeasurement[]): InspectionFactReport {
  return {...report, checks:[{...report.checks[0], check:'hardware.host_health', asset_name:'demo-host03', measurements}]}
}

it('renders actual demo host capacity and decline rates with exact raw values available', () => {
  const demo = hostReport([
    {layer:'HARDWARE', key:'host/decline', code:'MEMORY_SUSTAINED_DECLINE', current_metric:'host/memory_available_bytes', current:88510686035, long_slope_bytes_per_second:-9162596.9, short_slope_bytes_per_second:-9162596.9},
    {layer:'HARDWARE', key:'filesystem:demo-data/decline', code:'SPACE_DECLINE', current_metric:'filesystem:demo-data/available_bytes', current:185597562768, reserve_bytes:219902325555.2, long_slope_bytes_per_second:-87960930.22222222, short_slope_bytes_per_second:-87960930.22361112, seconds_to_reserve:0},
    {layer:'HARDWARE', metric:'host/decline', code:'SUSPECT_MEMORY_CONSUMPTION', current_metric:'host/memory_available_bytes', current:88510686035},
  ])
  const source = structuredClone(demo)
  render(<MemoryRouter><InspectionFacts report={demo} environmentId="env-1" /></MemoryRouter>)
  expect(screen.getByText('demo-host03')).toBeInTheDocument()
  expect(screen.getAllByText('88.51 GB')).toHaveLength(2)
  expect(screen.getByText('185.6 GB')).toHaveAttribute('title','filesystem:demo-data/available_bytes: 185597562768 bytes')
  expect(screen.getAllByText('88.51 GB')[0]).toHaveAttribute('title','host/memory_available_bytes: 88510686035 bytes')
  expect(screen.getByText('长期斜率 -9.16 MB/s')).toHaveAttribute('title','long_slope_bytes_per_second: -9162596.9 bytes/s')
  expect(screen.getByText('短期斜率 -9.16 MB/s')).toBeInTheDocument()
  expect(screen.getByText('长期斜率 -87.96 MB/s')).toHaveAttribute('title','long_slope_bytes_per_second: -87960930.22222222 bytes/s')
  expect(screen.getByText('短期斜率 -87.96 MB/s')).toBeInTheDocument()
  expect(screen.getByText('保留水位 219.9 GB')).toHaveAttribute('title','reserve_bytes: 219902325555.2 bytes')
  expect(screen.getByText('到保留水位 0 秒（不是写满时间）')).toHaveAttribute('title','seconds_to_reserve: 0 s')
  expect(screen.getByText('检查证据 →')).toHaveAttribute('href','/inspection-runs/run-1?environment=env-1#check-check-1')
  expect(demo).toEqual(source)
})

it('formats byte thresholds, boundaries, baselines and window medians consistently', () => {
  const capacity = hostReport([
    {layer:'DYNAMIC', metric:'host/memory_available_bytes', current:1000, threshold:2000, boundary:3000, baseline_median:4000, first_half_median:5000, second_half_median:6000, change_ratio:-0.123456, change_boundary:-0.05},
    {layer:'HARDWARE', metric:'host/decline', current:1000000, seconds_to_reserve:5400},
    {layer:'HARDWARE', key:'filesystem:demo-data/decline', current:2000000, seconds_to_reserve:129600},
  ])
  render(<MemoryRouter><InspectionFacts report={capacity} environmentId="env-1" /></MemoryRouter>)
  for (const text of ['1 kB', '2 kB', '3 kB', '4 kB', '5 kB', '6 kB', '1 MB', '2 MB']) {
    expect(screen.getByText(text)).toBeInTheDocument()
  }
  expect(screen.getByText('5 kB')).toHaveAttribute('title','host/memory_available_bytes: 5000 bytes')
  expect(screen.getByText('-12.346%')).toBeInTheDocument()
  expect(screen.getByText('-5%')).toBeInTheDocument()
  expect(screen.getByText('到保留水位 1.5 小时（不是写满时间）')).toBeInTheDocument()
  expect(screen.getByText('到保留水位 1.5 天（不是写满时间）')).toBeInTheDocument()
})

it('does not turn tiny, missing or nonfinite byte measurements into zero', () => {
  const edge = hostReport([
    {layer:'HARDWARE', metric:'host/memory_available_bytes', current:NaN, boundary:Infinity, first_half_median:0.001, long_slope_bytes_per_second:-0.000001, short_slope_bytes_per_second:-Infinity},
    {layer:'HARDWARE', metric:'host/memory_available_bytes'},
  ])
  render(<MemoryRouter><InspectionFacts report={edge} environmentId="env-1" /></MemoryRouter>)
  expect(screen.getAllByText('无效数值')).toHaveLength(2)
  expect(screen.getByText('短期斜率 无效数值')).toBeInTheDocument()
  expect(screen.getByText('1e-3 B')).toBeInTheDocument()
  expect(screen.getByText('长期斜率 -1e-6 B/s')).toBeInTheDocument()
  const medians = screen.getByText('1e-3 B').parentElement!
  expect(within(medians).getByText('未提供')).toBeInTheDocument()
  expect(screen.getByText('未提供当前测量值')).toBeInTheDocument()
})
