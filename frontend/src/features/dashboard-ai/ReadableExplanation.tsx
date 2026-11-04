import { Link } from 'react-router-dom'
import type { DashboardAnswer } from '../../api/dashboardAI'
import type { FactMeasurement, InspectionFact, InspectionFactReport } from '../../api/inspectionFacts'
import { formatReportTime, reportMeasurementNote, reportMeasurementValues, reportMetricKey, reportMetricLabel } from './reportMeasurementPresentation'

type GroundedRow = NonNullable<DashboardAnswer['grounded_report']>['checks'][number]
const statuses: Record<string, string> = { FAIL: '异常', UNKNOWN: '待确认', PASS: '通过', ERROR: '检查错误', NOT_APPLICABLE: '不适用' }
const gaps: Record<string, string> = {
  IDLE: '当前空闲，缺少有效请求样本', INCOMPLETE: '采集覆盖不完整', STALE: '采集数据已过期', NOT_READY: '证据尚未就绪',
  DYNAMIC_BASELINE_NOT_READY: '动态基线尚未就绪', EVIDENCE_INSUFFICIENT: '证据不足', INVALID_FROZEN_RESULT: '冻结结果版本、身份或时效无效',
}
const layers: Record<string, string> = { FIXED: '固定阈值', DYNAMIC: '动态边界', TREND: '窗口趋势', HARDWARE: '硬件证据' }
function evidenceUrl(runId: string, id: string, environmentId: string) {
  return `/inspection-runs/${encodeURIComponent(runId)}?environment=${encodeURIComponent(environmentId)}#check-${encodeURIComponent(id)}`
}
export function matchReportFact(report: InspectionFactReport | null | undefined, answer: DashboardAnswer, row: GroundedRow) {
  if (!report || report.source !== 'CODE' || report.inspection_run_id !== answer.inspection_run_id) return undefined
  const matches = report.checks.filter(fact => fact.id === row.id)
  return matches.length === 1 && matches[0].asset_name === row.asset_name ? matches[0] : undefined
}
function rawStatus(row: GroundedRow) {
  // Only read the exact CODE status on the header line; never infer a status from an AI sentence.
  return row.facts_text.split('\n')[0].match(/ · (FAIL|UNKNOWN|PASS|ERROR|NOT_APPLICABLE)$/)?.[1]
}
function Paragraphs({ text, splitSemicolons = false }: { text: string; splitSemicolons?: boolean }) {
  return <>{text.split(splitSemicolons ? /[；;\n]+/ : /\n+/).filter(part => part.trim()).map((part, index) => <p key={index}>{part.trim()}</p>)}</>
}
function Measurement({ item }: { item: FactMeasurement }) {
  const values = reportMeasurementValues(item)
  return <li className="readable-measurement"><div className="readable-measurement-heading"><strong>{reportMetricLabel(item)}</strong><span>{layers[item.layer] ?? item.layer}</span></div>
    {reportMeasurementNote(item) ? <small>{reportMeasurementNote(item)}</small> : null}
    {values.length ? <dl>{values.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p className="muted">本项未提供数值，核查方向见原始证据。</p>}
    {item.occurred_at ? <p className="readable-event-time"><time dateTime={item.occurred_at} title={item.occurred_at}>事件发生：{formatReportTime(item.occurred_at)}</time> · 独立于观测窗口</p> : null}
    <small className="readable-metric-key">{reportMetricKey(item)}{item.code ? ` · ${item.code}` : ''}</small>
  </li>
}
function Resource({ row, fact, answer, environmentId }: { row: GroundedRow; fact?: InspectionFact; answer: DashboardAnswer; environmentId: string }) {
  const status = fact?.status ?? rawStatus(row)
  const accepted = answer.grounded_report?.ai_status === 'ACCEPTED' && answer.ai_status !== 'INVALID_PROTOCOL' && row.ai?.source === 'AI' && row.ai.check_id === row.id
  return <article className={`grounded-resource readable-resource readable-status-${status?.toLowerCase() ?? 'unmatched'}`} id={`report-check-${row.id}`}>
    <header className="readable-resource-heading"><div><h4>{row.asset_name}</h4><p>{fact?.check_name ?? (rawStatus(row) ? row.facts_text.split('\n')[0].split(' · ')[0] : '检查事实')} <span className="analysis-source-code source-badge">CODE</span></p></div><div className="readable-resource-actions">{status ? <span className={`check-status check-status-${status.toLowerCase()}`}>{statuses[status] ?? status} · {status}</span> : <span className="muted">状态见原始事实</span>}<Link to={evidenceUrl(answer.inspection_run_id, row.id, environmentId)}>查看证据 ↗</Link></div></header>
    {fact ? <>
      <p className="readable-summary">{fact.summary}</p>
      {fact.evidence_gaps.length || fact.quality.pending_confirmation ? <aside className="readable-evidence-gap"><strong>证据缺口 / 待确认</strong>{fact.evidence_gaps.length ? <p>{fact.evidence_gaps.map(gap => gaps[gap] ?? gap).join('；')}</p> : null}{fact.quality.pending_confirmation ? <p>当时数据质量标记为待确认。</p> : null}<p>不据此认定故障或整体健康。{fact.status === 'PASS' ? 'PASS 仅表示本条代码检查通过。' : ''}</p></aside> : null}
      {fact.measurements.length ? <><ul className="readable-measurements">{fact.measurements.slice(0, 4).map((item, index) => <Measurement item={item} key={index} />)}</ul>{fact.measurements.length > 4 ? <details className="readable-more"><summary>展开其余 {fact.measurements.length - 4} 项指标 / 事件（共 {fact.measurements.length} 项）</summary><ul className="readable-measurements">{fact.measurements.slice(4).map((item, index) => <Measurement item={item} key={index} />)}</ul></details> : null}</> : <p className="muted">本条未提供可确认异常的测量值。</p>}
      <p className="readable-observation">历史观测窗口：<time title={fact.window_start ?? undefined}>{formatReportTime(fact.window_start)}</time> — <time title={fact.window_end ?? undefined}>{formatReportTime(fact.window_end)}</time><br />检查时间：<time title={fact.checked_at ?? undefined}>{formatReportTime(fact.checked_at)}</time>{fact.quality.state ? ` · 当时数据状态 ${fact.quality.state}` : ''}</p>
      {fact.risks.length ? <div className="readable-risks"><span>关联风险 · 当前处置状态</span>{fact.risks.map(risk => <Link to={`/risks/${encodeURIComponent(risk.id)}?environment=${encodeURIComponent(environmentId)}`} key={risk.id}>{risk.title} · {risk.severity} / {risk.status} ↗</Link>)}</div> : null}
    </> : <div className="readable-fallback"><p className="muted">结构化明细未与本条检查匹配，以下保留本条 CODE 原始事实。</p><Paragraphs text={row.facts_text} splitSemicolons /></div>}
    {accepted && row.ai ? <section className="grounded-ai-advice readable-advice"><span className="analysis-source-ai source-badge">AI · 潜在影响与核查建议</span><div className="readable-advice-columns"><div><h5>潜在影响</h5><Paragraphs text={row.ai.impact} splitSemicolons /></div><div><h5>建议核查</h5><Paragraphs text={row.ai.next_check} splitSemicolons /></div></div><small>原因尚未确认；AI 选择核查方向，不参与代码判定。</small></section> : <p className="muted">{row.ai_note || '本条未展示已校验的 AI 建议。'}</p>}
    <details className="readable-more readable-original"><summary>原始事实与检查标识</summary><dl><div><dt>巡检 ID</dt><dd>{answer.inspection_run_id}</dd></div><div><dt>检查 ID</dt><dd>{row.id}</dd></div>{fact ? <div><dt>资源 ID</dt><dd>{fact.asset_id}</dd></div> : null}</dl><p className="ai-answer-copy">{row.facts_text}</p></details>
  </article>
}
export function ReadableExplanation({ answer, report, environmentId }: { answer: DashboardAnswer; report?: InspectionFactReport | null; environmentId: string }) {
  const grounded = answer.grounded_report
  if (!grounded) return <p className="ai-answer-copy">{answer.answer}</p>
  const sameRun = report?.source === 'CODE' && report.inspection_run_id === answer.inspection_run_id
  const counts: Record<string, number> = sameRun ? report.status_counts : grounded.checks.reduce<Record<string, number>>((result, row) => { const status = rawStatus(row); if (status) result[status] = (result[status] ?? 0) + 1; return result }, {})
  return <div className="grounded-explanation readable-explanation">
    <section className="readable-overview" aria-label="检查概览"><div><strong>{sameRun ? `本次 CODE 检查 ${report.check_count} 条` : `本报告展示 ${grounded.checks.length} 条检查`}</strong><p>{sameRun ? `下方展示 ${grounded.checks.length} 条检查的事实与建议` : '未取得同次巡检的完整结构化概览，状态以本报告原始事实为准。'}</p></div><ul>{Object.entries(statuses).map(([status, label]) => <li key={status}><span>{label} · {status}</span><b>{counts[status] ?? 0}</b></li>)}</ul></section>
    <details className="readable-more readable-coverage"><summary>检查覆盖与 AI 输入范围</summary><p>{grounded.coverage_text}</p>{sameRun && report.omitted_count ? <p>结构化事实明细省略 {report.omitted_count} 条；完整检查请查看巡检证据。</p> : null}</details>
    <p className="readable-comparison muted">{grounded.comparison_text}</p>
    <p className="readable-observation">{sameRun ? report.risk_state_note : '检查事实为该次巡检的历史记录；关联风险显示当前处置状态。'}</p>
    {grounded.ai_status !== 'ACCEPTED' || answer.ai_status === 'INVALID_PROTOCOL' ? <p className="readable-evidence-gap">AI 解读未通过受约束协议；以下仅为 CODE 事实，未采纳模型自由文本。</p> : null}
    <nav className="readable-resource-index" aria-label="定位报告资源"><span>定位资源</span>{grounded.checks.map((row, index) => { const fact = matchReportFact(report, answer, row); const status = fact?.status ?? rawStatus(row); return <a href={`#report-check-${row.id}`} key={`${row.id}-${index}`}><span>{statuses[status ?? ''] ?? '见证据'}</span>{row.asset_name}</a> })}</nav>
    {grounded.checks.map((row, index) => <Resource key={`${row.id}-${index}`} row={row} fact={matchReportFact(report, answer, row)} answer={answer} environmentId={environmentId} />)}
    {answer.references.length ? <details className="readable-more readable-references"><summary>全部依据链接（{answer.references.length} 条）</summary><div className="ai-references">{answer.references.map((ref, index) => <Link className="ai-reference" key={`${ref.type}-${ref.id}-${index}`} to={ref.type === 'RISK' ? `/risks/${encodeURIComponent(ref.id)}?environment=${encodeURIComponent(environmentId)}` : ref.type === 'CODE_PLUGIN' ? `/rules#${encodeURIComponent(ref.id)}` : evidenceUrl(answer.inspection_run_id, ref.id, environmentId)}><span className="analysis-source-code source-badge">CODE</span><span>{ref.label}</span></Link>)}</div></details> : null}
  </div>
}
