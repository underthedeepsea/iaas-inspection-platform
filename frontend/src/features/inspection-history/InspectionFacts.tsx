import { resultLabel, reportLabel, reasonLabel } from './resultLabels'
import { Link } from 'react-router-dom'
import type { FactMeasurement, HostDiagnosticPresentation, InspectionFact, InspectionFactReport } from '../../api/inspectionFacts'
import { formatBytes, formatBytesPerSecond, formatDurationSeconds } from './measurementFormat'

const gapLabels: Record<string, string> = {IDLE: '当前空闲，缺少有效请求样本', STALE: '采集数据已过期', INCOMPLETE: '采集覆盖不完整', NOT_READY: '证据尚未就绪', DYNAMIC_BASELINE_NOT_READY: '动态基线尚未就绪', EVIDENCE_INSUFFICIENT: '证据不足'}
const codes: Record<string, string> = {HOST_CPU_STATIC_LIMIT: 'CPU持续高负载', HOST_MEMORY_STATIC_LIMIT: 'Linux可用内存持续不足', XID_DEVICE_LOST: 'GPU 设备丢失事件', XID_UNCLASSIFIED: '未分类 Xid 事件（根因未确认）', ECC_DBE_NEW: '新增双比特 ECC 错误', ECC_SBE_OCCASIONAL: '单比特 ECC 事件', ECC_SBE_RECURRENT: '单比特 ECC 重复事件', ECC_SBE_ACCELERATING: '单比特 ECC 增长事件', MEMORY_SUSTAINED_DECLINE: '可用内存持续下降', SPACE_DECLINE: '文件系统可用空间下降', SUSPECT_HARDWARE_WITH_SERVICE_DEGRADATION: '硬件异常伴随性能下降，关联原因待核查', SUSPECT_MEMORY_CONSUMPTION: '内存消耗原因待核查'}
function number(value: number | undefined) { return value == null ? '未提供' : new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 3}).format(value) }
function time(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', {hour12: false}) : '时间未提供' }
function metricName(item: FactMeasurement) { return item.metric ?? item.current_metric ?? item.key ?? codes[item.code ?? ''] ?? item.code ?? '证据' }
function metricLabel(item: FactMeasurement) {
  const key = metricName(item)
  const labels: Record<string,string> = {'ttft.p95_ms':'首 Token 等待时间 P95', 'ttft.p99_ms':'首 Token 等待时间 P99', 'tpot.p95_ms':'逐 Token 生成耗时 P95', 'tpot.p99_ms':'逐 Token 生成耗时 P99', 'e2e.p95_ms':'完整请求耗时 P95', 'e2e.p99_ms':'完整请求耗时 P99', 'requests.waiting':'排队请求数', 'requests.running':'运行中请求数', 'host/memory_available_bytes':'可用内存', 'host/memory_total_bytes':'内存总量', 'host/cpu_busy_ratio':'CPU忙碌比例'}
  return labels[key] ?? key
}
function valueMetric(item: FactMeasurement) { return item.current_metric ?? item.metric ?? item.key ?? '' }
function isByteMeasurement(item: FactMeasurement) { const key = valueMetric(item); return key.endsWith('_bytes') || key.endsWith('/decline') }
function measurementValue(item: FactMeasurement, value: number | undefined, windowMedian = false) {
  if (isByteMeasurement(item)) return formatBytes(value)
  if (item.unit === 'ratio' && value != null && Number.isFinite(value)) return new Intl.NumberFormat('zh-CN', {style: 'percent', maximumFractionDigits: 2}).format(value)
  return `${number(value)}${!windowMedian && valueMetric(item).endsWith('_ms') ? ' ms' : ''}`
}
function measurementTitle(item: FactMeasurement, value: number | undefined) {
  if (item.layer === 'OBSERVATION' && valueMetric(item) === 'host/cpu_busy_ratio' && item.unit === 'ratio' && value != null) return `${valueMetric(item)}: ${value} ratio`
  return isByteMeasurement(item) && value != null ? `${valueMetric(item)}: ${value} bytes` : undefined
}
function impact(row: InspectionFact) {
  if (row.status !== 'FAIL') return row.status === 'PASS' ? '本项检查通过；仅限原规则与窗口。' : row.status === 'NOT_APPLICABLE' ? '本项不适用，无需按缺测补数。' : '本项无法确认健康；其他已确认异常仍有效。下一步核对本项采集覆盖、有效样本与原始原因。'
  const metrics = row.measurements.map(item => item.metric ?? item.key ?? '').join(' ')
  if (metrics.includes('ttft')) return '首个 token 等待时间升高，可能影响用户感知响应；不等同服务中断。'
  if (metrics.includes('tpot') || metrics.includes('e2e')) return '生成节奏或完整请求耗时异常，可能影响推理体验。'
  if (row.check.includes('gpu')) return '硬件错误可能影响该 GPU 执行可靠性；事件根因及服务关联需要核查。'
  if (row.check.includes('host')) return 'CPU负载、可用内存或存储余量异常，可能影响该机器承载能力。'
  return '规则已发现异常；具体业务影响仍需核查。'
}
function Measurement({item}: {item: FactMeasurement}) {
  const layer = ({FIXED: '固定阈值', DYNAMIC: '动态边界', TREND: '窗口趋势', HARDWARE: '硬件证据', OBSERVATION: '原始观测'} as Record<string,string>)[item.layer] ?? item.layer
  return <li className="inspection-fact-measurement"><div><strong>{codes[item.code ?? ''] ?? metricLabel(item)}</strong><details className="fact-technical"><summary>指标标识与原始字段</summary><pre>{JSON.stringify(item, null, 2)}</pre></details><span className="fact-layer">{layer}</span></div><div className="fact-values">
    {item.xid_code != null ? <span>Xid <b>{item.xid_code}</b></span> : null}
    {item.current != null ? <span>{item.value_semantics === 'EVENT' ? '事件时数值' : '当前值'} <b title={measurementTitle(item, item.current)}>{measurementValue(item, item.current)}</b></span> : null}
    {item.threshold != null ? <span>触发阈值 <b title={measurementTitle(item, item.threshold)}>{measurementValue(item, item.threshold)}</b></span> : null}
    {item.boundary != null ? <span>触发边界 <b title={measurementTitle(item, item.boundary)}>{measurementValue(item, item.boundary)}</b></span> : null}
    {item.baseline_median != null ? <span>基线 <b title={measurementTitle(item, item.baseline_median)}>{measurementValue(item, item.baseline_median)}</b></span> : null}
    {item.change_boundary != null ? <span>趋势变化边界 <b>{number(item.change_boundary * 100)}%</b></span> : null}
    {item.change_ratio != null ? <span>变化 <b>{number(item.change_ratio * 100)}%</b></span> : null}
    {item.first_half_median != null ? <span>前半窗口 <span title={measurementTitle(item, item.first_half_median)}>{measurementValue(item, item.first_half_median, true)}</span> → 后半窗口 <span title={measurementTitle(item, item.second_half_median)}>{measurementValue(item, item.second_half_median, true)}</span></span> : null}
    {item.long_slope_bytes_per_second != null ? <span title={`long_slope_bytes_per_second: ${item.long_slope_bytes_per_second} bytes/s`}>长期斜率 {formatBytesPerSecond(item.long_slope_bytes_per_second)}</span> : null}
    {item.short_slope_bytes_per_second != null ? <span title={`short_slope_bytes_per_second: ${item.short_slope_bytes_per_second} bytes/s`}>短期斜率 {formatBytesPerSecond(item.short_slope_bytes_per_second)}</span> : null}
    {item.reserve_bytes != null ? <span title={`reserve_bytes: ${item.reserve_bytes} bytes`}>保留水位 {formatBytes(item.reserve_bytes)}</span> : null}
    {item.seconds_to_reserve != null ? <span title={`seconds_to_reserve: ${item.seconds_to_reserve} s`}>到保留水位 {formatDurationSeconds(item.seconds_to_reserve)}（不是写满时间）</span> : null}
    {item.current == null && item.xid_code == null && item.first_half_median == null ? <span>未提供当前测量值</span> : null}
    {item.occurred_at ? <time>事件发生：{time(item.occurred_at)}</time> : null}
  </div>
    {item.collected_at ? <p>采集时间：{time(item.collected_at)}</p> : null}
    {item.rule_id ? <p>确认：{item.confirmation_points ?? '未记录'}/{item.confirmation_required ?? '未记录'}点，窗口{item.trigger_window_seconds ?? '未记录'}秒。{reasonLabel(item.reason)}；{item.action}</p> : null}

  </li>
}
function HostDiagnostics({details}: {details: HostDiagnosticPresentation}) {
  const labels: Record<string, string> = {branches: '实际命中分支与冻结门槛/基线/尺度', series_points: '实际近期序列点数（最多12）', direct_confirmation_points: '单点路径确认点数', cusum_confirmation_points: 'CUSUM路径确认点数', recovery_points: '当前恢复确认点数', unit: '单位', rule_id: '规则', rule_version: '规则版本', rule: '冻结阈值与恢复水位', trigger_window_seconds: '触发窗口（秒）', recovery_window_seconds: '恢复窗口（秒）', recovery_required: '恢复所需有效点', action: '处置建议', baseline_median: '基线中位数（原始值）', mad: 'MAD', current: '原记录当前值', minimum_effect: '最小效应', long_slope_bytes_per_second: '长期斜率（bytes/s）', short_slope_bytes_per_second: '短期斜率（bytes/s）', confirmation_points: '确认点数', reason: '原因'}
  const statusText = (status?: string | null) => ({NOT_READY: '无法评估', NORMAL: '单项未触发异常', PENDING: '连续观测待确认', WARNING: '发现异常', CRITICAL: '发现严重异常'} as Record<string,string>)[status ?? ''] ?? '当时未记录结果'
  return <section className="host-diagnostics" aria-label="HOST逐项诊断"><h4>实际诊断</h4>
    <p>采样窗口：{time(details.window_start)} — {time(details.window_end)}</p>
    <ul className="host-diagnostic-grid">{details.items.map(item => <li key={item.metric}><h5>{item.name} · {statusText(item.status)}</h5>
      <p>{reasonLabel(item.reason, item.reason_note)}</p>{typeof item.statistics.sample_count === 'number' ? <p>已有 {String(item.statistics.sample_count)} 个样本；{item.requirements.match(/至少\s*(\d+)\s*(?:个|点)/) ? `原规则至少${item.requirements.match(/至少\s*(\d+)\s*(?:个|点)/)![1]}点` : '所需点数见原规则'}。</p> : null}
      <dl className="check-facts">{Object.entries(item.statistics).filter(([key]) => ['sample_count', 'series_points', 'window_seconds', 'minimum_points', 'minimum_seconds', 'confirmation_points', 'confirmation_required', 'recovery_points'].includes(key)).map(([key,value]) => <div key={key}><dt>{({sample_count:'已有样本点',series_points:'近期点数',window_seconds:'实际跨度（秒）',minimum_points:'所需点数',minimum_seconds:'所需跨度（秒）',confirmation_required:'所需确认点',confirmation_points:'已有确认点',recovery_points:'恢复点数'} as Record<string,string>)[key]}</dt><dd>{String(value)}</dd></div>)}</dl>
      <p>下一步：{item.advice}</p>
      <details className="fact-technical"><summary>规则、来源与原始诊断</summary><p>{item.requirements}</p><p>{item.binding_context?.note}</p><dl className="check-facts">{Object.entries(item.statistics).map(([key,value]) => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl><pre>{JSON.stringify(item,null,2)}</pre></details>
    </li>)}</ul>
    <h4>采集覆盖与影响</h4>{details.coverage.length ? <ul>{details.coverage.map(item => <li key={item.component}>{({host:'主机基础指标',filesystem:'文件系统',disk:'磁盘'} as Record<string,string>)[item.component] ?? item.component}：{item.status === 'READY' ? '已收到输入' : '采集不完整'}；{item.status === 'READY' ? '本组件输入已收到，诊断结论见对应项目。' : '缺少此组件输入，无法判断对应维度。'}</li>)}</ul> : <p>当时未记录组件覆盖。</p>}
    <details className="fact-technical"><summary>来源、版本与原始状态说明</summary><p>{details.execution_note}</p><p>{details.observation_note}</p><p>{details.rule_reference}；{details.recorded_plugin_version}；{details.evaluation_status}</p><pre>{JSON.stringify(details.coverage,null,2)}</pre></details>
  </section>
}

function FactCard({row, report, environmentId}: {row: InspectionFact; report: InspectionFactReport; environmentId: string}) {
  return <article className={`inspection-fact-card fact-${row.status.toLowerCase()}`}><header><div><strong>{row.asset_name}</strong><small>{row.check_name}</small></div><span className={`check-status check-status-${row.status.toLowerCase()}`}>{resultLabel(row)}</span></header>
    <p>{row.summary || '当时未记录具体原因，无法判断本项健康。'}</p>
    {row.evidence_gaps.length ? <p className="fact-evidence-gap">{row.evidence_gaps.map(gap => gapLabels[gap] ?? reasonLabel(gap)).join('；')}。不据此认定故障或整体健康。</p> : null}
    <details className="fact-technical"><summary>原始状态、来源与验收边界</summary><p>{row.status} · {report.source}</p><pre>{JSON.stringify(row.quality,null,2)}</pre><p>按原始来源解释；历史Mac观测不作为Linux服务器验收。</p></details>
    {row.host_diagnostics ? <h4>CPU与容量观测</h4> : null}
    {row.measurements.length ? <ul className="inspection-fact-measurements">{row.measurements.map((item,index) => <Measurement item={item} key={index} />)}</ul> : <p className="muted">当时未记录可展示的测量值。</p>}
    {row.host_diagnostics ? <HostDiagnostics details={row.host_diagnostics} /> : null}
    <p className="fact-impact">{impact(row)}</p><p className="fact-observed-time">历史观测窗口：{time(row.window_start)} — {time(row.window_end)}<br />检查时间：{time(row.checked_at)}</p>
    <footer><Link to={`/inspection-runs/${report.inspection_run_id}?environment=${environmentId}#check-${row.id}`}>检查证据 →</Link>{row.risks.map(risk => <Link key={risk.id} to={`/risks/${risk.id}?environment=${environmentId}`}>{risk.title} · 当前 {risk.severity} / {risk.status} →</Link>)}</footer>
  </article>
}
export function InspectionFacts({report, environmentId}: {report: InspectionFactReport; environmentId: string}) {
  const attention = report.checks.filter(row => row.status !== 'PASS' || row.evidence_gaps.length || row.measurements.length)
  const normal = report.checks.filter(row => !attention.includes(row))
  return <section className="panel inspection-facts" aria-label="资源与异常指标"><div className="section-heading"><div><h3>资源与异常指标</h3><p className="panel-lede">先定位服务和机器，再看触发判定的指标。以下为本次巡检保留的事实。</p></div><span className="legend">{report.check_count} 条检查 · {reportLabel(report.checks)}</span></div>
    <p className="data-source-note">{report.risk_state_note}</p><div className="inspection-fact-grid">{attention.map(row => <FactCard environmentId={environmentId} report={report} row={row} key={row.id} />)}</div>
    {!attention.length ? <p>本次没有异常或证据缺口。</p> : null}
    {normal.length ? <details className="fact-more"><summary>查看 {normal.length} 条通过的检查</summary><div className="inspection-fact-grid">{normal.map(row => <FactCard environmentId={environmentId} report={report} row={row} key={row.id} />)}</div></details> : null}
    {report.omitted_count ? <p>事实明细省略 {report.omitted_count} 条。</p> : null}
  </section>
}
