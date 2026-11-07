import type { FrozenMappingInputQuality, FrozenMappingInputs } from '../../api/inspectionRunResult'

function recorded(value: string | number | null | undefined) {
  return value == null || value === '' ? '未记录' : String(value)
}

function Field({ label, value }: { label: string; value?: string | number | null }) {
  return <div><dt>{label}</dt><dd>{recorded(value)}</dd></div>
}

export function FrozenMappingProvenance({ inputs, quality }: {
  inputs?: FrozenMappingInputs | null
  quality?: FrozenMappingInputQuality | null
}) {
  if (inputs == null && quality == null) return null
  const coverage = quality?.coverage
  const coverageLabel = coverage != null && Number.isFinite(coverage)
    ? `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(coverage * 100)}%`
    : '未记录'
  return <section className="panel check-results-panel" aria-label="本次巡检冻结映射来源">
    <div className="section-heading"><div><h3>本次巡检冻结映射来源</h3><p className="panel-lede">以下来源与输入随本次 Run 保留；关联风险展示当前处置状态。</p></div><span className="analysis-source-code source-badge">CODE</span></div>
    <dl className="check-facts">
      <Field label="数据源" value={inputs?.source_ref} />
      <Field label="采集批次" value={inputs?.batch_id} />
      <Field label="映射 revision ID" value={inputs?.revision_id} />
      <Field label="映射内容 hash" value={inputs?.content_hash} />
      <Field label="环境 ID" value={inputs?.environment_id} />
      <Field label="集群 UID" value={inputs?.cluster_uid} />
      <Field label="监控集群 ID" value={inputs?.monitor_cluster_id} />
      <Field label="历史窗口开始" value={inputs?.window_start} />
      <Field label="历史窗口结束" value={inputs?.window_end} />
      <Field label="生效记录 ID" value={inputs?.activation_id} />
      <Field label="校验记录 ID" value={inputs?.validation_id} />
      <Field label="原始输入 hash" value={inputs?.raw_hash} />
      <Field label="字段覆盖状态" value={quality?.status} />
      <Field label="字段覆盖率" value={coverageLabel} />
      <Field label="有效字段数" value={quality?.valid_fields} />
      <Field label="必需字段数" value={quality?.required_fields} />
      <Field label="缺失字段数" value={quality?.missing_count} />
      <Field label="当时基线状态" value={quality?.baseline_status ?? inputs?.baseline_status} />
      <Field label="覆盖计算依据" value={quality?.basis} />
    </dl>
    <details className="fact-more"><summary>冻结快照引用{inputs?.snapshot_ids ? `（${inputs.snapshot_ids.length}）` : ''}</summary>
      {inputs?.snapshot_ids?.length ? <ul>{inputs.snapshot_ids.map((id, index) => <li className="mono" key={`${id}-${index}`}>{id}</li>)}</ul> : <p>未记录</p>}
    </details>
    {inputs?.asset_ids?.length ? <details className="fact-more"><summary>冻结资产引用（{inputs.asset_ids.length}）</summary><ul>{inputs.asset_ids.map((id, index) => <li className="mono" key={`${id}-${index}`}>{id}</li>)}</ul></details> : null}
    {inputs?.versions && Object.keys(inputs.versions).length ? <details className="fact-more"><summary>当时输入契约与策略版本</summary><dl className="check-facts">{Object.entries(inputs.versions).map(([key, value]) => <Field key={key} label={key} value={value} />)}</dl></details> : null}
    {quality?.missing?.length ? <details className="fact-more"><summary>缺失字段明细</summary><ul>{quality.missing.map((item, index) => <li key={index}>{item.asset_id} · {item.component ? `${item.component} · ` : ''}{item.field}{item.quality ? ` · ${item.quality}` : ''}</li>)}</ul></details> : null}
    {quality?.missing_truncated ? <p className="muted">缺失字段明细已截断，缺失总数见上方记录。</p> : null}
    {quality?.binding_errors?.length ? <div><h4>输入绑定问题</h4><ul>{quality.binding_errors.map((error, index) => <li key={index}>{error}</li>)}</ul></div> : null}
    {inputs?.limitations?.length ? <div><h4>本次输入限制</h4><ul>{inputs.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul></div> : null}
    <p className="data-source-note">字段覆盖与基线状态仅描述当时输入，不表示资源健康；未记录的历史字段保持缺省。</p>
  </section>
}
