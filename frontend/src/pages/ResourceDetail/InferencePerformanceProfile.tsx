import { useQuery } from '@tanstack/react-query'

import { getApiError } from '../../api/http'
import { getInferenceProfile, type InferenceProfile } from '../../api/inferencePerformance'

function display(value: number | undefined, suffix = '') {
  return value == null ? '—' : `${Number(value.toFixed(2))}${suffix}`
}

function percentage(value: number | undefined) {
  return value == null ? '—' : `${Number((value * 100).toFixed(1))}%`
}

function profileIsUsable(profile: InferenceProfile | undefined): profile is InferenceProfile {
  return Boolean(profile?.engine && profile.current_metrics && profile.reasons)
}

export function InferencePerformanceProfile({ environmentId }: { environmentId: string }) {
  const query = useQuery({
    queryKey: ['inference-performance', environmentId, 'latest'],
    queryFn: () => getInferenceProfile(environmentId),
  })
  const profile = profileIsUsable(query.data) ? query.data : undefined
  const isNotFound = query.isError && getApiError(query.error)?.code === 'ENGINE_PERFORMANCE_NOT_FOUND'

  return (
    <section aria-labelledby="inference-performance-title" className="panel panel-large">
      <div className="section-heading">
        <div><span className="eyebrow">INFERENCE PERFORMANCE</span><h3 id="inference-performance-title">推理性能画像</h3></div>
        {profile ? <span className={`status-badge${profile.status === 'CRITICAL' ? ' status-critical' : ''}`}>{profile.status}</span> : null}
      </div>
      {query.isLoading ? <div className="empty-state compact"><p>正在读取推理性能数据</p></div> : isNotFound ? (
        <div className="empty-state compact"><strong>暂无性能数据</strong><p>等待外部监控程序推送首条推理性能快照。</p></div>
      ) : query.isError ? (
        <div className="empty-state compact"><strong>性能数据暂不可用</strong><p>暂时无法读取推理性能画像，请稍后重试。</p></div>
      ) : !profile ? (
        <div className="empty-state compact"><strong>暂无性能数据</strong><p>等待外部监控程序推送首条推理性能快照。</p></div>
      ) : (
        <>
          <div className="metric-grid metric-grid-three">
            <article className="metric-card"><span>TTFT P95</span><strong>{display(profile.current_metrics.ttft.p95_ms, ' ms')}</strong><small>首 token 延迟</small></article>
            <article className="metric-card"><span>TPOT P95</span><strong>{display(profile.current_metrics.tpot.p95_ms, ' ms/token')}</strong><small>每 token 延迟</small></article>
            <article className="metric-card"><span>E2E P95</span><strong>{display(profile.current_metrics.e2e.p95_ms, ' ms')}</strong><small>端到端延迟</small></article>
          </div>
          <div className="content-grid">
            <section className="panel"><dl className="definition-list">
              <div><dt>Engine ID</dt><dd>{profile.engine.engine_id}</dd></div>
              <div><dt>Model</dt><dd>{profile.engine.model_name}</dd></div>
              <div><dt>Engine Type</dt><dd>{profile.engine.engine_type}</dd></div>
              <div><dt>QPS / Generation TPS</dt><dd>{display(profile.current_metrics.traffic.qps)} / {display(profile.current_metrics.throughput.generation_tps)}</dd></div>
              <div><dt>Prompt TPS</dt><dd>{display(profile.current_metrics.throughput.prompt_tps)}</dd></div>
              <div><dt>KV Hit / Running / Waiting</dt><dd>{percentage(profile.current_metrics.cache.kv_cache_hit_rate)} / {display(profile.current_metrics.requests.running)} / {display(profile.current_metrics.requests.waiting)}</dd></div>
            </dl></section>
            <section className="panel"><dl className="definition-list">
              <div><dt>Fixed</dt><dd>{profile.fixed.status ?? '—'}</dd></div>
              <div><dt>Dynamic 14d</dt><dd>{profile.dynamic.status === 'NOT_READY' ? '历史基线建立中' : profile.dynamic.status ?? '—'}</dd></div>
              <div><dt>Trend</dt><dd>{profile.trend.status ?? '—'}</dd></div>
              <div><dt>Policy</dt><dd>{profile.policy_source.level ?? '—'}</dd></div>
            </dl></section>
          </div>
          <div className="section-heading"><div><span className="eyebrow">DETERMINISTIC REASONS</span><h3>异常原因</h3></div></div>
          {profile.reasons.length ? <div className="evidence-list">{profile.reasons.map((reason) => <article className="evidence-item" key={reason.code}>
            <header><strong>{reason.code}</strong><span className={`status-badge${reason.status === 'CRITICAL' ? ' status-critical' : ''}`}>{reason.status}</span></header>
            <p>{reason.metric} 当前值 {display(reason.current)}{reason.threshold != null ? `，固定阈值 ${display(reason.threshold)}` : `，14 天基线 ${display(reason.baseline_median)}，动态边界 ${display(reason.boundary)}`}</p>
          </article>)}</div> : <p className="empty-cell">当前没有固定阈值或动态基线异常。</p>}
        </>
      )}
    </section>
  )
}
