import { useQuery } from '@tanstack/react-query'
import { Select } from 'antd'
import { useState } from 'react'

import { getApiError } from '../../api/http'
import { getInferenceEngines, getInferenceProfile, type InferenceEngine, type InferenceProfile } from '../../api/inferencePerformance'

function display(value: number | undefined, suffix = '') {
  return value == null ? '—' : `${Number(value.toFixed(2))}${suffix}`
}

function percentage(value: number | undefined) {
  return value == null ? '—' : `${Number((value * 100).toFixed(1))}%`
}

function identity(engine: InferenceEngine) {
  return JSON.stringify([engine.engine_id, engine.engine_type, engine.model_name])
}

function profileIsUsable(profile: InferenceProfile | undefined): profile is InferenceProfile {
  return Boolean(profile?.engine && profile.current_metrics && profile.reasons)
}

function statusText(profile: InferenceProfile) {
  if (profile.status === 'WARNING' || profile.status === 'CRITICAL') return profile.status
  if (profile.freshness?.state === 'STALE') return '数据已过期 · 当前状态未知'
  if (profile.quality?.state === 'IDLE') return '空闲无请求 · 不能判断恢复'
  if (profile.quality?.pending_confirmation) return '异常待连续确认'
  if (profile.status === 'UNKNOWN') return '当前状态未知'
  return profile.status
}

export function InferencePerformanceProfile({ environmentId, latestRunAt }: { environmentId: string; latestRunAt?: string | null }) {
  const [requestedIdentity, setRequestedIdentity] = useState<string | null>(null)
  const enginesQuery = useQuery({ queryKey: ['inference-engines', environmentId], queryFn: () => getInferenceEngines(environmentId) })
  const engines = enginesQuery.data ?? []
  const selected = engines.find(engine => identity(engine) === requestedIdentity) ?? engines[0]
  const query = useQuery({
    queryKey: ['inference-performance', environmentId, selected?.engine_id, selected?.engine_type, selected?.model_name],
    queryFn: () => getInferenceProfile(environmentId, selected.engine_id, selected.engine_type, selected.model_name),
    enabled: Boolean(selected),
  })
  const profile = profileIsUsable(query.data) ? query.data : undefined
  const isNotFound = query.isError && getApiError(query.error)?.code === 'ENGINE_PERFORMANCE_NOT_FOUND'

  return <section aria-labelledby="inference-performance-title" className="panel panel-large">
    <div className="section-heading"><div><span className="eyebrow">INFERENCE PERFORMANCE</span><h3 id="inference-performance-title">推理性能画像</h3></div>
      {profile ? <span className={`status-badge${profile.status === 'CRITICAL' ? ' status-critical' : ''}`}>{statusText(profile)}</span> : null}</div>
    {engines.length > 0 ? <label className="environment-picker">推理引擎
      <Select aria-label="推理引擎" options={engines.map(engine => ({ value: identity(engine), label: `${engine.engine_id} · ${engine.engine_type} · ${engine.model_name}` }))}
        onChange={setRequestedIdentity} value={selected ? identity(selected) : undefined} />
    </label> : null}
    {enginesQuery.isLoading || query.isLoading ? <div className="empty-state compact"><p>正在读取推理性能数据</p></div> : enginesQuery.isError || query.isError && !isNotFound ? (
      <div className="empty-state compact"><strong>性能数据暂不可用</strong><p>暂时无法读取推理性能画像，请稍后重试。</p></div>
    ) : engines.length === 0 || isNotFound || !profile ? (
      <div className="empty-state compact"><strong>暂无性能数据</strong><p>等待外部监控程序推送首条推理性能快照。</p></div>
    ) : <>
      <p className="data-source-note">测量窗口：{profile.window.start} 至 {profile.window.end} · 数据新鲜度：{profile.freshness?.state === 'STALE' ? '已过期' : '新鲜'} · 最近正式巡检：{latestRunAt ?? '尚无，请运行一次巡检'}</p>
      {profile.plugin?.id ? <p className="data-source-note">CODE 插件：{profile.plugin.id} · v{profile.plugin.version ?? '—'}</p> : <p className="data-source-note">历史性能结果未标注插件版本，不能作为当前正式巡检结论。</p>}
      {profile.quality?.pending_confirmation ? <p role="status">{profile.status === 'WARNING' || profile.status === 'CRITICAL' ? '部分原始指标待确认；已确认异常仍有效。' : '原始指标越界，正在等待连续观测确认；当前不新增风险。'}</p> : null}
      {profile.dynamic.baseline_state === 'NOT_READY' || profile.dynamic.status === 'NOT_READY' ? <p role="status">动态基线尚未就绪，固定阈值判断仍可使用。</p> : null}
      <div className="metric-grid metric-grid-three">
        <article className="metric-card"><span>TTFT P95</span><strong>{display(profile.current_metrics.ttft.p95_ms, ' ms')}</strong><small>首 token 延迟</small></article>
        <article className="metric-card"><span>TPOT P95</span><strong>{display(profile.current_metrics.tpot.p95_ms, ' ms/token')}</strong><small>每 token 延迟</small></article>
        <article className="metric-card"><span>E2E P95</span><strong>{display(profile.current_metrics.e2e.p95_ms, ' ms')}</strong><small>端到端延迟</small></article>
      </div>
      <div className="content-grid"><section className="panel"><dl className="definition-list">
        <div><dt>Engine ID</dt><dd>{profile.engine.engine_id}</dd></div><div><dt>Model</dt><dd>{profile.engine.model_name}</dd></div><div><dt>Engine Type</dt><dd>{profile.engine.engine_type}</dd></div>
        <div><dt>Fixed</dt><dd>{profile.fixed.status ?? '—'}</dd></div><div><dt>Dynamic 14d</dt><dd>{profile.dynamic.status === 'NOT_READY' ? '历史基线建立中' : profile.dynamic.status ?? '—'}</dd></div><div><dt>Trend</dt><dd>{profile.trend.status ?? '—'}</dd></div><div><dt>Policy</dt><dd>{profile.policy_source.level ?? '—'}</dd></div>
      </dl></section></div>
      <details><summary>全部当前指标</summary><dl className="definition-list">
        <div><dt>QPS / QPM</dt><dd>{display(profile.current_metrics.traffic.qps)} / {display(profile.current_metrics.traffic.qpm)}</dd></div>
        <div><dt>Generation / Prompt TPS</dt><dd>{display(profile.current_metrics.throughput.generation_tps)} / {display(profile.current_metrics.throughput.prompt_tps)}</dd></div>
        <div><dt>KV 命中率</dt><dd>{percentage(profile.current_metrics.cache.kv_cache_hit_rate)}</dd></div>
        <div><dt>Running / Waiting</dt><dd>{display(profile.current_metrics.requests.running)} / {display(profile.current_metrics.requests.waiting)}</dd></div>
        {(['ttft', 'tpot', 'e2e'] as const).map(key => <div key={key}><dt>{key.toUpperCase()} AVG / P90 / P95 / P99</dt><dd>{display(profile.current_metrics[key].avg_ms)} / {display(profile.current_metrics[key].p90_ms)} / {display(profile.current_metrics[key].p95_ms)} / {display(profile.current_metrics[key].p99_ms)}</dd></div>)}
      </dl></details>
      <div className="section-heading"><div><span className="eyebrow">DETERMINISTIC REASONS</span><h3>异常原因</h3></div></div>
      {profile.reasons.length ? <div className="evidence-list">{profile.reasons.map(reason => <article className="evidence-item" key={reason.code}>
        <header><strong>{reason.code}</strong><span className={`status-badge${reason.status === 'CRITICAL' ? ' status-critical' : ''}`}>{reason.status}</span></header>
        <p>{reason.metric} 当前值 {display(reason.current)}{reason.threshold != null ? `，固定阈值 ${display(reason.threshold)}` : `，14 天基线 ${display(reason.baseline_median)}，动态边界 ${display(reason.boundary)}`}</p>
      </article>)}</div> : <p className="empty-cell">当前没有已确认的固定阈值或动态基线异常。</p>}
    </>}
  </section>
}
