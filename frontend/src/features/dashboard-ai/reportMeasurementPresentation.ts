import type { FactMeasurement } from '../../api/inspectionFacts'
import { formatBytes, formatBytesPerSecond, formatDurationSeconds } from '../inspection-history/measurementFormat'

const numeric = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2, useGrouping: false })
const labels: Record<string, string> = {
  'ttft.p95_ms': '首 Token 等待时间 P95', 'ttft.p99_ms': '首 Token 等待时间 P99',
  'tpot.p95_ms': '逐 Token 生成耗时 P95', 'tpot.p99_ms': '逐 Token 生成耗时 P99',
  'e2e.p95_ms': '完整请求耗时 P95', 'e2e.p99_ms': '完整请求耗时 P99',
  'requests.waiting': '排队请求数', 'requests.running': '运行中请求数',
  'host/memory_available_bytes': '可用内存', 'host/decline': '可用内存下降趋势',
  'gpu/xid_events': 'GPU Xid 事件', 'gpu/ecc_dbe_delta': 'GPU 新增双比特 ECC 错误',
  'gpu/ecc_sbe_delta': 'GPU 单比特 ECC 事件',
  SUSPECT_HARDWARE_WITH_SERVICE_DEGRADATION: '硬件异常伴随性能下降，关联原因待核查',
  SUSPECT_MEMORY_CONSUMPTION: '内存消耗原因待核查',
}
const codeNotes: Record<string, string> = {
  XID_DEVICE_LOST: 'GPU 设备丢失事件', XID_UNCLASSIFIED: '未分类 Xid 事件，根因未确认',
  ECC_DBE_NEW: '新增双比特 ECC 错误', ECC_SBE_OCCASIONAL: '单比特 ECC 事件',
  ECC_SBE_RECURRENT: '单比特 ECC 重复事件', ECC_SBE_ACCELERATING: '单比特 ECC 增长事件',
  MEMORY_SUSTAINED_DECLINE: '可用内存持续下降', SPACE_DECLINE: '文件系统可用空间下降',
  SPACE_RESERVE_TREND: '空间保留水位趋势',
}
export function reportMetricKey(item: FactMeasurement) { return item.current_metric ?? item.metric ?? item.key ?? '' }
export function reportMetricLabel(item: FactMeasurement) {
  const key = reportMetricKey(item)
  if (key.startsWith('filesystem:')) return `文件系统 ${key.slice('filesystem:'.length).split('/')[0]} 可用空间`
  return labels[key] ?? labels[item.code ?? ''] ?? codeNotes[item.code ?? ''] ?? (key || '检查证据')
}
export function reportMeasurementNote(item: FactMeasurement) { return codeNotes[item.code ?? ''] }
export function formatReportRatio(value: number) {
  if (!Number.isFinite(value)) return '无效数值'
  const percent = value * 100
  // Retain tiny nonzero changes instead of rounding them to 0% (or -0%).
  if (percent !== 0 && Math.abs(percent) < 0.005) {
    const [mantissa, exponent] = percent.toExponential(2).split('e')
    return `${Number(mantissa)}e${Number(exponent)}%`
  }
  return `${numeric.format(percent === 0 ? 0 : percent)}%`
}
export function formatReportTime(value?: string | null) {
  if (!value) return '未提供'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
/** Select latency units for the whole row, including both halves of a trend window. */
export function formatReportMeasurement(item: FactMeasurement, value: number | undefined) {
  if (value == null) return '未提供'
  if (!Number.isFinite(value)) return '无效数值'
  const key = reportMetricKey(item)
  if (key.endsWith('_bytes') || key.endsWith('/decline')) return formatBytes(value)
  if (key.endsWith('_ms')) {
    const values = [item.current, item.value, item.threshold, item.boundary, item.baseline_median, item.warning, item.critical, item.first_half_median, item.second_half_median].filter((v): v is number => v != null && Number.isFinite(v))
    const max = Math.max(...values.map(Math.abs))
    // Below one minute all converted fields share seconds; otherwise retain ms for consistent units.
    if (max >= 1000 && max < 60000) return formatDurationSeconds(value / 1000)
    return `${value !== 0 && Math.abs(value) < 0.005 ? value.toExponential(2) : numeric.format(value)} ms`
  }
  return value !== 0 && Math.abs(value) < 0.005 ? value.toExponential(2) : numeric.format(value)
}
export interface ReportValue { label: string; value: string }
export function reportMeasurementValues(item: FactMeasurement): ReportValue[] {
  const values: ReportValue[] = []
  const add = (label: string, raw: number | undefined, format: (value: number) => string = value => formatReportMeasurement(item, value)) => {
    if (raw != null) values.push({ label, value: format(raw) })
  }
  add('Xid', item.xid_code, value => String(value))
  add(item.value_semantics === 'EVENT' ? '事件时数值' : '历史测量值', item.current ?? item.value)
  add('触发阈值', item.threshold)
  add('触发边界', item.boundary)
  add('基线中位数', item.baseline_median)
  add('变化', item.change_ratio, formatReportRatio)
  add('趋势变化边界', item.change_boundary, formatReportRatio)
  add('前半窗口中位数', item.first_half_median)
  add('后半窗口中位数', item.second_half_median)
  add('短期斜率', item.short_slope_bytes_per_second, formatBytesPerSecond)
  add('长期斜率', item.long_slope_bytes_per_second, formatBytesPerSecond)
  add('保留水位', item.reserve_bytes, formatBytes)
  add('到保留水位（不是写满时间）', item.seconds_to_reserve, formatDurationSeconds)
  return values
}
