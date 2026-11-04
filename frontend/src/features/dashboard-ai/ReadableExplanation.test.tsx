import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it } from 'vitest'
import type { DashboardAnswer } from '../../api/dashboardAI'
import type { InspectionFact, InspectionFactReport } from '../../api/inspectionFacts'
import { matchReportFact, ReadableExplanation } from './ReadableExplanation'

const fact: InspectionFact = { id: 'check-1', check: 'hardware.host_health', check_name: '主机基础环境健康巡检', asset_id: 'asset-uuid', asset_name: 'demo-host-03', status: 'FAIL', summary: '可用内存持续下降，原因待核查', quality: { state: 'READY' }, evidence_gaps: [], measurements: [{ layer: 'HARDWARE', key: 'host/memory_available_bytes', current: 88510686035, short_slope_bytes_per_second: -9162596.9, code: 'MEMORY_SUSTAINED_DECLINE' }], risks: [{ id: 'risk-1', title: '硬件异常', status: 'NEW', severity: 'P2', state_source: 'CURRENT' }], window_start: '2026-10-09T03:19:00Z', window_end: '2026-10-09T03:20:00Z', checked_at: '2026-10-09T03:23:26Z' }
const report: InspectionFactReport = { source: 'CODE', inspection_run_id: 'run-1', check_count: 16, status_counts: { FAIL: 6, UNKNOWN: 3, PASS: 7 }, checks: [fact], omitted_count: 0, risk_state_note: '检查事实为历史记录；风险为当前处置状态。' }
const answer: DashboardAnswer = { inspection_run_id: 'run-1', source: { type: 'AI', provider: 'ollama', model: 'test' }, confidence: null, ai_status: 'ACCEPTED', answer: '模型自由文本，不应显示', references: [{ id: 'check-1', label: '原始检查链接', type: 'CHECK_RESULT', source: 'CODE' }, { id: 'risk-1', label: '原始风险链接', type: 'RISK', source: 'CODE' }], grounded_report: { source: 'CODE', ai_status: 'ACCEPTED', accepted_count: 1, coverage_text: 'AI 输入 8 / 16 条检查，省略不代表证据不足', comparison_text: '缺少前次摘要，无法比较', checks: [{ id: 'check-1', asset_name: 'demo-host-03', source: 'CODE', facts_text: '主机基础环境健康巡检 · FAIL\n原始字节 88510686035 bytes；证据检查 ID：check-1', ai_note: '', ai: { source: 'AI', check_id: 'check-1', impact: '内存下降可能影响承载；原因尚未确认', next_check: '核对进程内存；核对同期负载' } }] } }
function view(a = answer, r: InspectionFactReport | null = report) { return render(<MemoryRouter><ReadableExplanation answer={a} report={r} environmentId="env-1" /></MemoryRouter>) }
function withFact(next: Partial<InspectionFact>) { return { ...report, checks: [{ ...fact, ...next }] } }

it('shows exact CODE check counts, resource identity, compact measurements and separated AI sections', () => {
  view()
  const overview = screen.getByRole('region', { name: '检查概览' })
  expect(overview).toHaveTextContent('本次 CODE 检查 16 条')
  expect(overview).toHaveTextContent('异常 · FAIL6')
  expect(overview).toHaveTextContent('待确认 · UNKNOWN3')
  expect(overview).toHaveTextContent('通过 · PASS7')
  expect(overview).toHaveTextContent('下方展示 1 条检查')
  expect(screen.getByText('异常 · FAIL', { selector: '.check-status' })).toBeInTheDocument()
  expect(screen.getByText('88.51 GB')).toBeInTheDocument()
  expect(screen.getByText('-9.16 MB/s')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '潜在影响' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: '建议核查' })).toBeInTheDocument()
  expect(screen.getByText('原因尚未确认')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看证据 ↗' })).toHaveAttribute('href', '/inspection-runs/run-1?environment=env-1#check-check-1')
  expect(screen.getByRole('navigation', { name: '定位报告资源' })).toHaveTextContent('demo-host-03')
  expect(screen.queryByText(answer.answer)).not.toBeInTheDocument()
})
it.each(['run', 'check', 'asset', 'duplicate'])('keeps original CODE facts and does not substitute mismatched %s facts', kind => {
  const other = kind === 'run' ? { ...report, inspection_run_id: 'other-run' } : kind === 'duplicate' ? { ...report, checks: [fact, fact] } : withFact(kind === 'check' ? { id: 'other-check' } : { asset_name: 'other-host' })
  expect(matchReportFact(other, answer, answer.grounded_report!.checks[0])).toBeUndefined()
  view(answer, other)
  expect(screen.getByText('结构化明细未与本条检查匹配，以下保留本条 CODE 原始事实。')).toBeInTheDocument()
  expect(screen.queryByText('88.51 GB')).not.toBeInTheDocument()
  expect(screen.getByText('原始字节 88510686035 bytes')).toBeInTheDocument()
  expect(screen.getByText('核对进程内存')).toBeInTheDocument()
})
it.each(['invalid-report', 'invalid-answer', 'wrong-check'])('displays accepted AI advice only and rejects %s suggestions', kind => {
  const changed: DashboardAnswer = { ...answer, ...(kind === 'invalid-answer' ? { ai_status: 'INVALID_PROTOCOL' as const } : {}), grounded_report: { ...answer.grounded_report!, ...(kind === 'invalid-report' ? { ai_status: 'INVALID_PROTOCOL' as const } : {}), checks: answer.grounded_report!.checks.map(row => ({ ...row, ai: { ...row.ai!, check_id: kind === 'wrong-check' ? 'other' : row.id } })) } }
  view(changed)
  expect(screen.queryByRole('heading', { name: '建议核查' })).not.toBeInTheDocument()
  expect(screen.queryByText('核对进程内存')).not.toBeInTheDocument()
  expect(screen.getByText('88.51 GB')).toBeInTheDocument()
})
it.each([
  ['UNKNOWN', 'IDLE', '当前空闲，缺少有效请求样本'],
  ['UNKNOWN', 'INVALID_FROZEN_RESULT', '冻结结果版本、身份或时效无效'],
  ['PASS', 'DYNAMIC_BASELINE_NOT_READY', '动态基线尚未就绪'],
])('keeps %s evidence gap %s prominent without declaring overall health', (status, gap, label) => {
  view(answer, withFact({ status, evidence_gaps: [gap], measurements: [], quality: { state: gap, pending_confirmation: true } }))
  const aside = screen.getByRole('complementary')
  expect(aside).toHaveTextContent(label)
  expect(aside).toHaveTextContent('当时数据质量标记为待确认')
  expect(aside).toHaveTextContent('不据此认定故障或整体健康')
  if (status === 'PASS') expect(aside).toHaveTextContent('PASS 仅表示本条代码检查通过')
})
it('preserves Xid/ECC event times, all hidden metrics, reserve meaning and raw IDs/links', () => {
  const measurements: InspectionFact['measurements'] = [
    { layer: 'HARDWARE', key: 'gpu/xid_events', xid_code: 79, occurred_at: '2026-10-09T10:24:25+08:00', code: 'XID_DEVICE_LOST' },
    { layer: 'HARDWARE', key: 'gpu/ecc_dbe_delta', current: 1, value_semantics: 'EVENT', occurred_at: '2026-10-09T10:36:00+08:00', code: 'ECC_DBE_NEW' },
    { layer: 'HARDWARE', key: 'filesystem:data/available_bytes', current: 185597562768, reserve_bytes: 219902325555.2, seconds_to_reserve: 0 },
    { layer: 'DYNAMIC', metric: 'ttft.p95_ms', current: 339.7773, boundary: 308.75866, change_ratio: .540647378 },
    { layer: 'HARDWARE', key: 'gpu/xid_events', xid_code: 999, occurred_at: '2026-10-09T10:26:25+08:00', code: 'XID_UNCLASSIFIED' },
  ]
  view(answer, withFact({ measurements }))
  expect(screen.getByText('事件时数值')).toBeInTheDocument()
  expect(screen.getAllByText('独立于观测窗口', { exact: false })).toHaveLength(3)
  expect(document.querySelector('time[datetime="2026-10-09T10:24:25+08:00"]')).toBeInTheDocument()
  expect(screen.getByText('到保留水位（不是写满时间）')).toBeInTheDocument()
  expect(screen.getByText('0 秒')).toBeInTheDocument()
  expect(screen.getByText('54.06%')).toBeInTheDocument()
  const more = screen.getByText('展开其余 1 项指标 / 事件（共 5 项）').closest('details')!
  expect(more).not.toHaveAttribute('open')
  fireEvent.click(within(more).getByText(/展开其余/))
  expect(more).toHaveAttribute('open')
  expect(within(more).getByText('999')).toBeInTheDocument()
  expect(screen.getByText('未分类 Xid 事件，根因未确认')).toBeInTheDocument()
  const original = screen.getByText('原始事实与检查标识').closest('details')!
  expect(original).toHaveTextContent('asset-uuid')
  expect(original.querySelector('.ai-answer-copy')!.textContent).toBe(answer.grounded_report!.checks[0].facts_text)
  expect(screen.getByText('原始风险链接').closest('a')).toHaveAttribute('href', '/risks/risk-1?environment=env-1')
  expect(screen.getByText('原始检查链接').closest('a')).toHaveAttribute('href', '/inspection-runs/run-1?environment=env-1#check-check-1')
  expect(screen.getByText('关联风险 · 当前处置状态')).toBeInTheDocument()
  expect(screen.getByText(/历史观测窗口/)).toBeInTheDocument()
})
it('retains every grounded row, renders semicolon advice as safe text and preserves coverage omissions', () => {
  const ai = answer.grounded_report!.checks[0].ai!
  const changed: DashboardAnswer = { ...answer, grounded_report: { ...answer.grounded_report!, checks: [...answer.grounded_report!.checks, { ...answer.grounded_report!.checks[0], id: 'second', asset_name: 'second-resource', ai: { ...ai, check_id: 'second', impact: '<script>alert(1)</script>；原因未确认', next_check: '[执行](javascript:bad)' } }] } }
  const { container } = view(changed)
  expect(container.querySelectorAll('article')).toHaveLength(2)
  expect(screen.getAllByRole('link', { name: '查看证据 ↗' })).toHaveLength(2)
  expect(screen.getByText('<script>alert(1)</script>')).toBeInTheDocument()
  expect(container.querySelector('script')).toBeNull()
  expect(screen.getByText('[执行](javascript:bad)')).toBeInTheDocument()
  expect(screen.getByText('AI 输入 8 / 16 条检查，省略不代表证据不足')).toBeInTheDocument()
})
