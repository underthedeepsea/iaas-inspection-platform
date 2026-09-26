import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../api/http'

type Point = { value: number | null | { event_id: string; code: number }[]; quality: string; collected_at: string }
type Diagnostic = { status: string; sample_count?: number; current?: number; baseline_median?: number; seconds_to_reserve?: number }
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
      <details><summary>条件基线、持续退化与容量趋势</summary><p>8 个历史点仅为最低计算门槛。NOT_READY 不表示诊断健康；预测为到保留空间的趋势估计。</p><table><thead><tr><th>诊断维度</th><th>状态</th><th>历史点数</th><th>基线中位数</th><th>到保留空间</th></tr></thead><tbody>{Object.entries(profile.evaluation.diagnostics).map(([key, diagnostic]) => <tr key={key}><td>{key}</td><td>{diagnostic.status}</td><td>{diagnostic.sample_count ?? '—'}</td><td>{diagnostic.baseline_median ?? '—'}</td><td>{diagnostic.seconds_to_reserve == null ? '—' : `${(diagnostic.seconds_to_reserve / 3600).toFixed(1)} 小时`}</td></tr>)}</tbody></table></details>
      {profile.evaluation.correlations.length ? <p>疑似关联：{profile.evaluation.correlations.map(item => item.code).join('；')}</p> : null}
      <p className="muted">{profile.evaluation.limitations.join(' ')}</p>
    </article>)}
  </section>
}
