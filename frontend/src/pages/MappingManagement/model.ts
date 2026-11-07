export type ConfigStatus = 'NOT_CHECKED' | 'VALID' | 'ERROR'
export type Cluster = { kind: 'cluster'; id: string; source: string; env: string; uid: string; displayName: string; monitorId: string; enabled: boolean }
export type Metric = { kind: 'metric'; id: string; clusterId: string; code: string; sourceMetric: string; labels: string; sourceType: 'GAUGE' | 'COUNTER' | 'HISTOGRAM' | 'STRING'; sourceUnit: string; outputUnit: string; conversion: number; window: number; step: number; aggregation: 'mean' | 'rate' | 'p95'; support: 'SUPPORTED' | 'UNSUPPORTED' | 'UNCONFIGURED'; enabled: boolean }
export type Content = Cluster | Metric
export type Revision = { version: number; content: Content; config: ConfigStatus; data: 'NOT_RUN'; reason: string }
export type MappingState = Record<string, Revision[]>
export const current = (state: MappingState, id: string) => state[id]?.[state[id].length - 1]
export const latest = (state: MappingState) => Object.values(state).map(history => history[history.length - 1])
export const clusterRows = (state: MappingState) => latest(state).filter((r): r is Revision & { content: Cluster } => r.content.kind === 'cluster')
export const metricRows = (state: MappingState, clusterId: string) => latest(state).filter((r): r is Revision & { content: Metric } => r.content.kind === 'metric' && r.content.clusterId === clusterId)
const demo = (value: string) => /^demo-[a-z0-9][a-z0-9-]*$/.test(value)
export function validate(content: Content, state: MappingState): string[] {
 const errors: string[] = []
 if (!demo(content.id)) errors.push('草稿身份必须使用 demo- 合成标识')
 if (content.kind === 'cluster') {
  const existing = current(state, content.id)?.content
  if (existing?.kind === 'cluster' && existing.uid !== content.uid) errors.push('稳定 UID 创建后不可更改')
  for (const key of ['source', 'env', 'uid', 'displayName', 'monitorId'] as const) if (!demo(content[key])) errors.push(`${key} 必须使用 demo- 合成标识`)
  if (clusterRows(state).some(({content: row}) => row.id !== content.id && row.source === content.source && row.env === content.env && (row.uid === content.uid || row.monitorId === content.monitorId))) errors.push('同源同环境的稳定 UID 或监控标识冲突')
 } else {
  if (current(state, content.clusterId)?.content.kind !== 'cluster') errors.push('必须选择明确的合成集群作用域')
  if (!/^demo\.[a-z][a-z0-9_.]*$/.test(content.code)) errors.push('标准指标 code 必须使用 demo. 合成占位')
  if (metricRows(state, content.clusterId).some(({content: row}) => row.id !== content.id && row.code === content.code)) errors.push('当前集群内标准指标重复')
  if (content.support !== 'UNCONFIGURED' && !/^demo\.[a-z][a-z0-9_.]*$/.test(content.sourceMetric)) errors.push('源指标必须使用 demo. 合成占位')
  if (content.labels && content.labels.split(',').some(label => !/^demo_[a-z0-9_]+=demo-[a-z0-9-]+$/.test(label.trim()))) errors.push('标签格式必须为 demo_键=demo-值，以逗号分隔')
  if (content.sourceType === 'STRING') errors.push('STRING 不能作为数值健康输入')
  if (content.sourceType === 'HISTOGRAM' && content.support === 'SUPPORTED') errors.push('HISTOGRAM 桶与请求级分位语义未核实，不能声明支持')
  if (content.sourceType === 'COUNTER' && content.aggregation !== 'rate') errors.push('COUNTER 必须使用 rate；重置与数据语义尚未验证')
  if (content.sourceType === 'GAUGE' && content.aggregation !== 'mean') errors.push('GAUGE 合成示例仅支持时间 mean')
  if (content.sourceType === 'HISTOGRAM' && content.aggregation !== 'p95') errors.push('HISTOGRAM 示例仅保留 p95 待验证语义')
  if (![content.window, content.step].every(n => Number.isFinite(n) && n > 0)) errors.push('window 和 step 必须为正数秒')
  if (content.step > content.window) errors.push('step 大于 window 的语义未确认')
  if (![content.sourceUnit, content.outputUnit].every(unit => ['percent', 'count', 'seconds', 'bytes'].includes(unit))) errors.push('必须选择明确的源单位与输出单位')
  if (content.sourceUnit !== content.outputUnit) errors.push('本合成闭环只支持相同单位，跨单位换算待确认')
  if (!Number.isFinite(content.conversion) || content.conversion !== 1) errors.push('本合成闭环换算系数必须为 1')
  if (content.support === 'UNCONFIGURED' && (content.sourceMetric || content.labels)) errors.push('未配置指标的源指标与标签必须留空')
 }
 return errors
}
export function saveDraft(state: MappingState, content: Content, expectedVersion: number): MappingState {
 if ((current(state, content.id)?.version ?? 0) !== expectedVersion) throw new Error('版本冲突，请重新打开草稿')
 const errors = validate(content, state)
 if (errors.length) throw new Error(errors.join('；'))
 return { ...state, [content.id]: [...(state[content.id] ?? []), {version: expectedVersion + 1, content: {...content}, config: 'VALID', data: 'NOT_RUN', reason: '保存合成草稿；未生效'}] }
}
export function rollbackDraft(state: MappingState, id: string, version: number): MappingState {
 const old = state[id]?.find(row => row.version === version)
 if (!old) throw new Error('历史版本不存在')
 const present = current(state, id)!.content
 if (old.content.kind === 'cluster' && present.kind === 'cluster' && old.content.uid !== present.uid) throw new Error('稳定 UID 创建后不可更改；不能从不同 UID 的历史内容回退')
 return {...state, [id]: [...state[id], {version: current(state, id)!.version + 1, content: {...old.content}, config: 'NOT_CHECKED', data: 'NOT_RUN', reason: `从 v${version} 内容生成回退草稿；需重新校验，未生效`}]}
}
export function differences(previous: Content | undefined, next: Content): string[] {
 if (!previous) return ['新建合成草稿']
 return Object.entries(next).filter(([key, value]) => value !== (previous as unknown as Record<string, unknown>)[key]).map(([key, value]) => `${key}: ${String((previous as unknown as Record<string, unknown>)[key])} → ${String(value)}`)
}
