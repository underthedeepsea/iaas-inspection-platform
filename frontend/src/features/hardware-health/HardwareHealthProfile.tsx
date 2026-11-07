import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../api/http'

type Point = { value: number | null | { event_id: string; code: number }[]; quality: string; collected_at: string }
type Diagnostic = { status: string; sample_count?: number; current?: number; baseline_median?: number; seconds_to_reserve?: number; [key: string]: unknown }
const capacity = /\/(memory_used_bytes|memory_total_bytes|memory_available_bytes|available_bytes|size_bytes)$/
function recorded(value: unknown) { return value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value) }
type Profile = { snapshot_id: string; asset_id: string; asset_name: string; host_id: string; status: string; freshness: string; window_start: string; window_end: string; metrics: Record<string, { identity: Record<string, string>; values: Record<string, Point> }>; evaluation: { diagnostics: Record<string, Diagnostic>; issues: { key: string; code: string; severity: string }[]; limitations: string[]; correlations: { code: string }[] } }

export function HardwareHealthProfile({ environmentId, resourceCode }: { environmentId: string; resourceCode: string }) {
  const query = useQuery({ queryKey: ['hardware-health', environmentId, resourceCode], queryFn: async () => (await apiClient.get<{ profiles: Profile[] }>('/hardware-health/profiles', { params: { environment_id: environmentId, resource_type: resourceCode } })).data })
  return <section className="panel panel-large" aria-labelledby="hardware-health-title">
    <div className="section-heading"><div><span className="eyebrow">HARDWARE HEALTH</span><h3 id="hardware-health-title">GPU / 宿主机诊断</h3></div></div>
    <p>每台设备保留独立证据。基线不足、缺测和不支持分别显示；显存预分配本身不判异常。</p>
    {query.isLoading ? <p role="status">正在读取硬件快照</p> : query.isError ? <p role="alert">硬件快照暂不可用</p> : !query.data?.profiles.length ? <p role="status">暂无硬件数据，等待外部系统推送快照。</p> : query.data.profiles.map(profile => <article key={profile.asset_id}>
      <h4>{profile.asset_name} · {profile.status} {profile.freshness === 'STALE' ? '（数据过期，当前状态未知）' : ''}</h4>
      <p className="data-source-note">宿主机 {profile.host_id} · {profile.window_start} 至 {profile.window_end}</p>
      {profile.evaluation.issues.length > 0 ? <ul>{profile.evaluation.issues.map((issue, index) => <li key={`${issue.key}-${index}`}>{issue.severity} · {issue.key} · {issue.code}</li>)}</ul> : <p>当前无已确认异常；高级诊断覆盖见下表。</p>}
      <details><summary>指标、采集质量与组件身份</summary>{Object.entries(profile.metrics).map(([component, body]) => <div key={component}><h5>{component} · {Object.values(body.identity).join(' / ')}</h5><table><thead><tr><th>指标</th><th>观测值</th><th>质量</th><th>采集时间</th></tr></thead><tbody>{Object.entries(body.values).map(([metric, point]) => <tr key={metric}><td>{metric}</td><td>{point.value == null ? '—' : Array.isArray(point.value) ? point.value.map(event => `Xid ${event.code} (${event.event_id})`).join('、') || '无新增事件' : String(point.value)}</td><td>{point.quality}</td><td>{point.collected_at}</td></tr>)}</tbody></table></div>)}</details>
      <section aria-label="逐项硬件诊断"><h5>条件基线、持续退化与容量趋势</h5><p>{resourceCode === 'HOST' ? 'HOST v2 CPU漂移需14天30个可比历史点、最多12个近期点，各分支连续3点；旧版本按原冻结规则。' : 'GPU 条件基线至少8个历史点，最近最多6点；以原冻结结果为准。'} NOT_READY 表示无法评估，PENDING 表示等待连续观测确认；容量初始化NORMAL仅为观测。</p>
      {Object.entries(profile.evaluation.diagnostics).map(([key, diagnostic]) => <article key={key}><h5>{key} · {(capacity.test(key) && diagnostic.status === 'NORMAL') ? 'OBSERVATION · 容量观测，不生成健康结论' : diagnostic.status}</h5>
        <p>原因：{recorded(diagnostic.reason ?? '原记录未提供独立原因')} · 下一步：{recorded(diagnostic.action ?? ((capacity.test(key) && diagnostic.status === 'NORMAL') ? '结合实际诊断查看，不将容量初始化状态当作健康。' : diagnostic.status === 'NOT_READY' ? '核对本项原始质量、历史点数和匹配上下文，按原规则补齐有效观测。' : diagnostic.status === 'PENDING' ? '保留后续有效连续观测，等待原规则确认。' : '对照原规则及窗口核查本项。'))}</p>
        <dl className="definition-list">{Object.entries(diagnostic).map(([field, value]) => <div key={field}><dt>{field === 'status' && (capacity.test(key) && diagnostic.status === 'NORMAL') ? '原始初始化状态（非健康）' : field}</dt><dd>{recorded(value)}</dd></div>)}</dl>
        {!('unit' in diagnostic) ? <p>单位：{key.includes('bytes') || key.endsWith('/decline') ? 'bytes（斜率为bytes/秒）' : key.includes('ratio') ? 'ratio' : '原记录未标注'}</p> : null}
      </article>)}</section>
      {profile.evaluation.correlations.length ? <p>疑似关联：{profile.evaluation.correlations.map(item => item.code).join('；')}</p> : null}
      <p className="muted">{profile.evaluation.limitations.join(' ')}</p>
    </article>)}
  </section>
}
