import type { InspectionFactReport } from '../../../api/inspectionFacts'

// SYNTHETIC public v1 report. Every identifier, timestamp and measurement is fabricated.
// No real Run, frozen input, source artifact or private report is embedded here.
const start = '2001-02-03T04:05:00+00:00'
const end = '2001-02-03T04:06:00+00:00'
const measurements = [
  { metric: 'host/cpu_busy_ratio', current: 0.3125, unit: 'ratio' },
  { metric: 'host/memory_available_bytes', current: 1073741824, unit: 'bytes' },
  { metric: 'host/memory_total_bytes', current: 4294967296, unit: 'bytes' },
].map(value => ({ ...value, layer: 'OBSERVATION', value_semantics: 'OBSERVATION', contributes_to_status: false, quality: 'VALID', collected_at: '2001-02-03T12:05:45+08:00', source: 'synthetic-macos-observation-only', config_id: 'synthetic-config-a', sample_id: 'synthetic-sample-a', asset_id: 'synthetic-host-a', snapshot_id: 'synthetic-snapshot-a', window_start: start, window_end: end, frozen_at: '2001-02-03T04:06:30+00:00', input_as_of: '2001-02-03T04:06:30+00:00' }))
export const syntheticHostDiagnosticReport = {
  source: 'CODE', inspection_run_id: 'synthetic-run-a', check_count: 1,
  status_counts: { FAIL: 0, ERROR: 0, UNKNOWN: 1, PASS: 0, NOT_APPLICABLE: 0 },
  checks: [{ id: 'synthetic-check-a', check: 'hardware.host_health', check_name: '合成宿主机健康巡检', asset_id: 'synthetic-host-a', asset_name: 'synthetic-host-a', status: 'UNKNOWN', summary: '合成记录：硬件数据不足或异常待确认', source: 'CODE', checked_at: '2001-02-03T04:06:45+00:00', window_start: start, window_end: end, snapshot_id: 'synthetic-snapshot-a', quality: { state: 'INCOMPLETE', pending_confirmation: false }, evidence_gaps: ['INCOMPLETE'], measurements, risks: [],
    host_diagnostics: {
      rule_reference: '已批准gpu-host-health v1.0.0规则说明（代码展示说明，非本Run新增冻结参数）', recorded_plugin_version: '1.0.0', evaluation_status: 'UNKNOWN', window_start: start, window_end: end,
      execution_note: '巡检执行状态与HOST综合结论分开；执行完成不代表各诊断已就绪或整体健康。', observation_note: 'CPU及内存容量仅为观测；逐点VALID与容量初始化NORMAL均不生成健康PASS。',
      items: [
        { metric: 'host/cpu_busy_ratio', name: 'CPU条件漂移', recorded: true, status: 'NOT_READY', statistics: { sample_count: 0 }, reason: 'INSUFFICIENT_COMPARABLE_HISTORY', reason_note: '可比历史不足；实际样本数见原记录。', requirements: '14天内至少8个历史点；近期样本留出基线。', advice: '核对合成绑定并积累可比历史。', binding_context: { recorded: true, complete: false, engine_count: 0, note: '合成绑定不完整；不补造负载上下文。' } },
        { metric: 'host/decline', name: '主机内存持续下降', recorded: true, status: 'NOT_READY', statistics: { sample_count: 1 }, reason: null, reason_note: '未记录独立原因，不补造原因。', requirements: '至少6个点，跨度至少300秒；仅报告持续下降。', advice: '保留合成时序；不推断根因。' },
      ],
      coverage: [ { component: 'disk', status: 'MISSING', impact: '缺少磁盘覆盖，不能据此确认I/O健康。' }, { component: 'host', status: 'READY', impact: 'VALID仅表示采集有效。' }, { component: 'filesystem', status: 'MISSING', impact: '缺少文件系统覆盖，不能据此确认存储健康。' } ],
    },
  }], omitted_count: 0, risk_state_note: '风险状态与等级为当前处置状态；检查事实为本次巡检的历史记录。',
} as unknown as InspectionFactReport
