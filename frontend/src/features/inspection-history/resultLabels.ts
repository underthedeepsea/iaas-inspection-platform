import type { InspectionFact } from '../../api/inspectionFacts'
import type { CheckResult } from '../../api/resources'

type Result = Partial<InspectionFact> & { evidence?: CheckResult['evidence'] }
export function resultLabel(row: Result): string {
  if (row.status === 'FAIL') return '发现异常'
  if (row.status === 'ERROR') return '执行失败'
  if (row.status === 'PASS') return '检查通过'
  if (row.status === 'NOT_APPLICABLE') return '不适用'
  const evidence = row.evidence ?? {}
  const evaluation = evidence.evaluation as Record<string, unknown> | undefined
  const known = JSON.stringify([row.evidence_gaps, row.quality, evidence.reason_code, evidence.error_code, evaluation?.quality, evaluation?.coverage, evaluation?.diagnostics, row.host_diagnostics?.coverage, row.host_diagnostics?.items.map(item => ({ reason: item.reason, reason_note: item.reason_note }))])
  const labels: string[] = []
  if (/IDENTITY_MISMATCH|身份不符|身份不匹配/.test(known+(row.summary??''))) labels.push('身份不匹配')
  if (/PLUGIN_VERSION_MISMATCH|版本不符|版本不匹配/.test(known+(row.summary??''))) labels.push('版本不匹配')
  if (/SNAPSHOT_MISMATCH|快照编号不符/.test(known+(row.summary??''))) labels.push('快照不匹配')
  if (/STALE|数据已过期|快照已超过/.test(known + (row.summary ?? ''))) labels.push('数据过期')
  if (/NO_DATA|SNAPSHOT_MISSING/.test(known)) labels.push('未采集')
  if (/INCOMPLETE|MISSING|UNSUPPORTED|覆盖不完整/.test(known)) labels.push('采集不完整')
  const shortHistory = row.host_diagnostics?.items.some(item => {
    const needed = item.requirements.match(/至少\s*(\d+)\s*(?:个|点)/)
    return item.recorded && item.status === 'NOT_READY' && needed && typeof item.statistics.sample_count === 'number' && item.statistics.sample_count < Number(needed[1])
  })
  if (/INSUFFICIENT.*HISTORY|INSUFFICIENT_CONTIGUOUS_WINDOW|BASELINE_NOT_READY|历史不足|历史样本不足/.test(known) || shortHistory) labels.push('历史不足')
  if (/IDLE/.test(known)) labels.push('有效请求样本不足')
  if (/PENDING|TRIGGER_CONFIRMATION_PENDING/.test(known) || row.quality?.pending_confirmation || (evaluation?.quality as {pending_confirmation?: boolean} | undefined)?.pending_confirmation) labels.push('连续观测待确认')
  return [...new Set(labels)].join('、') || '无法判断'
}
export function reportLabel(rows: Result[]): string {
  const ordered = [...rows].sort((a, b) => (a.status === 'FAIL' ? 0 : a.status === 'ERROR' ? 1 : 2) - (b.status === 'FAIL' ? 0 : b.status === 'ERROR' ? 1 : 2))
  return [...new Set(ordered.map(resultLabel))].join('；') || '尚无检查结果'
}
export function reasonLabel(reason?: string | null, fallback = '当时未记录具体原因'): string {
  const labels: Record<string, string> = { INSUFFICIENT_COMPARABLE_HISTORY: '可比历史样本不足', INSUFFICIENT_CONTIGUOUS_WINDOW: '连续时序点数或跨度不足', NO_DATA: '没有收到有效快照', SNAPSHOT_STALE: '快照已超过有效时限', IDENTITY_MISMATCH: '快照对象或环境身份不符', PLUGIN_VERSION_MISMATCH: '插件版本不匹配', SNAPSHOT_MISMATCH: '冻结结果与快照编号不符', INVALID_HARDWARE_INPUT: '原记录仅标注输入无效，未细分失败项', TRIGGER_CONFIRMATION_PENDING: '尚未达到连续确认点数', INCOMPLETE_BINDING_OR_INFERENCE: '绑定或推理上下文不完整', INVALID_OR_INCOMPARABLE_POINT: '当前点无效或负载不可比' }
  return reason ? labels[reason] || (/^[A-Z_0-9]+$/.test(reason) ? '具体技术原因见展开详情' : reason) : fallback
}
