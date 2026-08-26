import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { displayDataMode, getProductInfo, type ProductInfo } from '../../api/product'

export type SectionPageKey =
  | 'risks'
  | 'history'
  | 'pending'
  | 'capabilities'
  | 'experiences'
  | 'evolution'
  | 'ai-runtime'
  | 'settings'

const pageMeta: Record<SectionPageKey, { eyebrow: string; title: string; lede: string }> = {
  risks: {
    eyebrow: 'RISK CENTER',
    title: '风险中心',
    lede: '按影响和生命周期管理风险，处置后仍需自动复验。',
  },
  history: {
    eyebrow: 'HISTORY',
    title: '历史趋势',
    lede: '按日查看巡检快照与风险变化。',
  },
  pending: {
    eyebrow: 'ACTION QUEUE',
    title: '待处置',
    lede: '处置完成后请等待下一轮自动复验。',
  },
  capabilities: {
    eyebrow: 'CAPABILITY REGISTRY',
    title: '巡检能力',
    lede: '每个项目都说明代码能确认什么，以及 LLM 还负责什么。',
  },
  experiences: {
    eyebrow: 'EXPERIENCE TO CODE',
    title: '规则与经验',
    lede: '人工反馈不会直接改线上规则，会先经过确认、影子运行和激活。',
  },
  evolution: {
    eyebrow: 'LEARNING LOOP',
    title: '能力演进',
    lede: '把稳定、可验证的经验逐步交给代码，把不确定性留给 AI。',
  },
  'ai-runtime': {
    eyebrow: 'MODEL GATEWAY',
    title: 'AI 运行情况',
    lede: 'AI 只在代码无法确认的 Claim 上介入，所有 Tool Call 都是只读的。',
  },
  settings: {
    eyebrow: 'SYSTEM',
    title: '系统设置',
    lede: '模型、环境和数据源由服务端配置。',
  },
}

export function SectionOverviewPage({ page }: { page: SectionPageKey }) {
  const meta = pageMeta[page]
  return (
    <section aria-labelledby={`${page}-title`} className="view">
      <div className="page-heading">
        <div>
          <span className="eyebrow">{meta.eyebrow}</span>
          <h2 id={`${page}-title`}>{meta.title}</h2>
          <p className="lede">{meta.lede}</p>
        </div>
        {page === 'risks' || page === 'capabilities' ? <button className="button button-secondary" type="button">刷新数据</button> : null}
      </div>
      {page === 'risks' ? <RiskCenter /> : null}
      {page === 'history' ? <HistoryOverview /> : null}
      {page === 'pending' ? <PendingOverview /> : null}
      {page === 'capabilities' ? <CapabilitiesOverview /> : null}
      {page === 'experiences' ? <ExperiencesOverview /> : null}
      {page === 'evolution' ? <EvolutionOverview /> : null}
      {page === 'ai-runtime' ? <AiRuntimeOverview /> : null}
      {page === 'settings' ? <SettingsOverview /> : null}
    </section>
  )
}

function RiskCenter() {
  return (
    <>
      <div aria-label="风险筛选" className="filter-bar">
        {['全部', 'P1', 'P2', 'P3', '待处置', '待复验'].map((label, index) => <button className={`filter-chip${index === 0 ? ' is-active' : ''}`} key={label} type="button">{label}</button>)}
      </div>
      <section className="panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>风险</th><th>领域</th><th>级别</th><th>状态</th><th>出现次数</th><th>AI 介入</th><th /></tr></thead>
            <tbody><tr><td className="empty-cell" colSpan={7}>暂无风险数据</td></tr></tbody>
          </table>
        </div>
      </section>
    </>
  )
}

function HistoryOverview() {
  return <section className="panel"><div className="empty-state"><strong>历史快照</strong><p>选择一个日期范围后，这里会展示风险、完整性和代码化趋势。</p><Link className="button button-secondary" to="/">回到今日巡检</Link></div></section>
}

function PendingOverview() {
  return <section className="panel"><div className="empty-state"><strong>待处置风险</strong><p>风险列表会按优先级聚合需要人工处理的项目。</p><Link className="button button-secondary" to="/risks">打开风险中心</Link></div></section>
}

function CapabilitiesOverview() {
  return (
    <>
      <div className="capability-summary">
        <div className="summary-pill"><span>已激活能力</span><strong>—</strong></div>
        <div className="summary-pill"><span>代码化覆盖率</span><strong>—</strong></div>
        <div className="summary-pill"><span>待验证经验</span><strong>—</strong></div>
      </div>
      <section className="panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>巡检项目</th><th>执行模式</th><th>代码状态</th><th>覆盖率</th><th>LLM 职责</th><th /></tr></thead>
            <tbody><tr><td className="empty-cell" colSpan={6}>暂无巡检能力数据</td></tr></tbody>
          </table>
        </div>
      </section>
    </>
  )
}

function ExperiencesOverview() {
  return <section className="panel"><div className="table-wrap"><table className="data-table"><thead><tr><th>经验</th><th>状态</th><th>目标 Claim</th><th>来源</th><th>创建时间</th></tr></thead><tbody><tr><td className="empty-cell" colSpan={5}>暂无规则与经验</td></tr></tbody></table></div></section>
}

function EvolutionOverview() {
  return (
    <>
      <div className="metric-grid metric-grid-three">
        <article className="metric-card"><span>Code Coverage Rate</span><strong>—</strong><small>巡检断言由代码覆盖</small></article>
        <article className="metric-card"><span>Deterministic Deflection Rate</span><strong>—</strong><small>无需进入 AI 的案例</small></article>
        <article className="metric-card"><span>AI Displacement Rate</span><strong>—</strong><small>被代码化能力替代的 AI 调查</small></article>
      </div>
      <div className="content-grid">
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">PIPELINE</span><h3>从反馈到代码</h3></div></div><div className="evolution-steps"><div><b>01</b><span>人工确认根因</span><small>形成可复用 Experience</small></div><div><b>02</b><span>SHADOW</span><small>影子运行并观察精度</small></div><div><b>03</b><span>CODE_ACTIVE</span><small>稳定后替代同类 AI 调查</small></div></div></section>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">STATUS</span><h3>当前队列</h3></div></div><div className="empty-state compact"><p>暂无演进任务</p></div></section>
      </div>
    </>
  )
}

function AiRuntimeOverview() {
  const [productInfo, setProductInfo] = useState<ProductInfo | null>(null)

  useEffect(() => {
    let active = true
    void getProductInfo().then((value) => {
      if (active) setProductInfo(value)
    }).catch(() => {
      // Keep the boundary visible if runtime metadata is unavailable.
    })
    return () => { active = false }
  }, [])

  return (
    <>
      <div className="runtime-grid">
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">PROVIDER</span><h3>当前运行时</h3></div></div><dl className="definition-list"><div><dt>Provider</dt><dd>{productInfo?.llm_provider ?? '读取中…'}</dd></div><div><dt>安全模式</dt><dd>{productInfo?.security_mode ?? 'READ_ONLY_TOOLS'}</dd></div><div><dt>数据源</dt><dd>{displayDataMode(productInfo?.data_mode)}</dd></div></dl></section>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">BOUNDARIES</span><h3>调查预算</h3></div></div><div className="budget-list"><div><span>最大调查轮次</span><strong>3</strong></div><div><span>最大 Tool Call</span><strong>5</strong></div><div><span>写操作</span><strong>禁止</strong></div></div></section>
      </div>
      <section className="panel runtime-note"><div className="section-heading"><div><span className="eyebrow">OBSERVABILITY</span><h3>运行说明</h3></div></div><p className="body-copy">可在风险详情中询问 AI。对话消息、调查事件和工具摘要会持久化；详细输入输出保持折叠，页面默认只展示人能决策的摘要。</p><p className="body-copy runtime-boundary">所有 Tool Call 都是只读的。</p></section>
    </>
  )
}

function SettingsOverview() {
  return <section className="panel"><div className="empty-state"><strong>系统配置</strong><p>模型、数据库和 Airflow 的运行状态会在产品说明与 AI 运行页面展示。</p><Link className="button button-secondary" to="/about">阅读产品说明</Link></div></section>
}
