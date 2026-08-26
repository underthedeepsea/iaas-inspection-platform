import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useState } from 'react'

import {
  getRisk,
  getRiskEvidence,
  getRiskTimeline,
  markRiskHandled,
  reverifyRisk,
  riskKeys,
  startRiskInvestigation,
  type RiskEvidence,
  type RiskTimelineEvent,
} from '../../api/risks'

const statusLabels: Record<string, string> = {
  NEW: '首次发现',
  PERSISTING: '风险持续',
  WORSENED: '风险加重',
  INVESTIGATING: '调查中',
  LOCATED: '已定位',
  PENDING_ACTION: '待处置',
  PENDING_REVERIFY: '待复验',
  RECOVERED: '已恢复',
  IGNORED: '已忽略',
  FALSE_POSITIVE: '误报',
}

function statusLabel(status?: string | null) {
  return status ? (statusLabels[status] ?? status) : '—'
}

function formatDate(value?: string | null) {
  return value ? value.slice(0, 10) : '—'
}

function formatPercent(value?: number | null) {
  return value == null ? '—' : `${Math.round(value)}%`
}

export function RiskDetailPage() {
  const { riskId = '' } = useParams()
  const [actionLoading, setActionLoading] = useState(false)
  const [actionMessage, setActionMessage] = useState('')
  const [actionError, setActionError] = useState('')
  const [feedbackMessage, setFeedbackMessage] = useState('')
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)

  const detailQuery = useQuery({
    queryKey: riskKeys.detail(riskId),
    queryFn: () => getRisk(riskId),
    enabled: Boolean(riskId),
  })
  const timelineQuery = useQuery({
    queryKey: riskKeys.timeline(riskId),
    queryFn: () => getRiskTimeline(riskId),
    enabled: Boolean(riskId),
  })
  const evidenceQuery = useQuery({
    queryKey: riskKeys.evidence(riskId),
    queryFn: () => getRiskEvidence(riskId),
    enabled: Boolean(riskId),
  })

  if (!riskId) return <section className="view"><div className="empty-state"><strong>风险详情</strong><p>缺少风险标识。</p></div></section>
  if (detailQuery.isLoading) return <section className="view"><div className="empty-state"><strong>正在加载风险详情</strong><p>正在读取风险判断、证据和生命周期。</p></div></section>
  if (detailQuery.isError || !detailQuery.data) return <section className="view" role="alert"><div className="empty-state"><strong>风险详情加载失败</strong><p>暂时无法读取该风险。</p><button className="button button-secondary" onClick={() => void detailQuery.refetch()} type="button">重试</button></div></section>

  const risk = detailQuery.data
  const timeline = timelineQuery.data?.events ?? []
  const evidence = evidenceQuery.data?.items ?? []
  const severity = risk.severity.toLowerCase()
  const status = statusLabel(risk.status)

  const refreshRisk = async () => {
    await Promise.all([detailQuery.refetch(), timelineQuery.refetch(), evidenceQuery.refetch()])
  }

  const runAction = async (action: () => Promise<unknown>, successMessage: string, errorMessage: string) => {
    setActionLoading(true)
    setActionMessage('')
    setActionError('')
    try {
      await action()
      await refreshRisk()
      setActionMessage(successMessage)
    } catch {
      setActionError(errorMessage)
    } finally {
      setActionLoading(false)
    }
  }

  const askAi = async () => {
    const trimmedQuestion = question.trim()
    if (!trimmedQuestion) {
      setActionError('请先输入想让 AI 核查的问题。')
      return
    }
    setAsking(true)
    setActionMessage('')
    setActionError('')
    try {
      await startRiskInvestigation(riskId, trimmedQuestion)
      setQuestion('')
      await detailQuery.refetch()
      setActionMessage('AI 调查已启动，可在风险时间线中继续查看。')
    } catch {
      setActionError('AI 调查启动失败，请稍后重试。')
    } finally {
      setAsking(false)
    }
  }

  return (
    <section aria-labelledby="risk-detail-title" className="view">
      <div className="back-row"><Link className="text-link" to="/risks">← 返回风险中心</Link><span className="muted">风险 ID：{riskId}</span></div>
      <div className="page-heading">
        <div><span className="eyebrow">RISK DETAIL · {risk.domain}</span><h2 id="risk-detail-title">{risk.title || '未命名风险'}</h2><p className="lede">聚合当前判断、可追溯证据和风险生命周期，支持处置后复验。</p></div>
        <div className="heading-actions"><span className={`severity-badge severity-${severity}`}>{risk.severity}</span><span className={`status-badge${risk.severity === 'P1' ? ' status-critical' : ''}`}>{status}</span></div>
      </div>

      <div className="metric-grid metric-grid-three">
        <article className="metric-card"><span>出现次数</span><strong>{risk.occurrence_count}</strong><small>持续 {risk.duration_days ?? '—'} 天</small></article>
        <article className="metric-card"><span>首次发现</span><strong>{formatDate(risk.first_seen_at)}</strong><small>最近发现 {formatDate(risk.last_seen_at)}</small></article>
        <article className={risk.ai_involved ? 'metric-card metric-card-warn' : 'metric-card'}><span>AI 介入</span><strong>{risk.ai_involved ? '是' : '否'}</strong><small>{risk.recent_investigation?.status ?? '代码判断'}</small></article>
      </div>

      <section className="panel risk-decision-panel">
        <div className="section-heading"><div><span className="eyebrow">L1 · DECISION</span><h3>当前判断</h3></div><span className="legend">{risk.risk_key || '—'}</span></div>
        <p className="decision-copy">{risk.current_conclusion || '当前暂无补充结论，请结合下方证据进行判断。'}</p>
        <div className="risk-impact"><span>影响范围</span><strong>{risk.impact_summary || '暂无影响摘要'}</strong></div>
        <p className="recommendation"><strong>建议动作：</strong>{risk.recommendation || '先确认影响范围，再记录处理结果并发起复验。'}</p>
        <div className="feedback-actions"><span className="muted">这个判断对你有帮助吗？</span><button className="button button-quiet" onClick={() => setFeedbackMessage('已记录：判断有帮助。')} type="button">有帮助</button><button className="button button-quiet" onClick={() => setFeedbackMessage('已记录：结论需要复核。')} type="button">结论不准确</button><button className="button button-quiet" onClick={() => setFeedbackMessage('已打开补充反馈入口。')} type="button">补充反馈</button></div>
        {feedbackMessage ? <p className="form-success" role="status">{feedbackMessage}</p> : null}
        <div className="detail-actions"><button className="button button-primary" disabled={actionLoading} onClick={() => void runAction(() => markRiskHandled(riskId, '已在风险中心记录处理，等待复验'), '已记录处理，风险进入待复验。', '记录处理失败，请检查风险当前状态。')} type="button">{actionLoading ? '处理中…' : '记录已处理'}</button><button className="button button-secondary" disabled={actionLoading} onClick={() => void runAction(() => reverifyRisk(riskId), '复验请求已提交。', '复验提交失败，请确认该风险已处于待复验状态。')} type="button">立即复验</button></div>
        {actionMessage ? <p className="form-success" role="status">{actionMessage}</p> : null}
        {actionError ? <p className="form-error" role="alert">{actionError}</p> : null}
      </section>

      <div className="content-grid content-grid-wide">
        <section className="panel panel-large">
          <div className="section-heading"><div><span className="eyebrow">L2 · EVIDENCE</span><h3>关键证据</h3></div><span className="legend">{evidence.length} 项</span></div>
          {evidenceQuery.isError ? <p className="form-error" role="alert">证据加载失败，请重试。</p> : null}
          {evidence.length ? <div className="evidence-list">{evidence.map((item) => <EvidenceItem item={item} key={item.id || item.evidence_id} />)}</div> : <div className="empty-state compact"><p>{evidenceQuery.isLoading ? '正在加载证据…' : '暂无结构化证据。'}</p></div>}
          <details className="disclosure"><summary>查看证据字段</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>
        </section>
        <section className="panel">
          <div className="section-heading"><div><span className="eyebrow">L3 · CODEIZATION</span><h3>代码化状态</h3></div></div>
          <dl className="definition-list"><div><dt>执行模式</dt><dd>{risk.codeization?.execution_mode || '—'}</dd></div><div><dt>代码状态</dt><dd>{risk.codeization?.code_status || '—'}</dd></div><div><dt>代码覆盖率</dt><dd>{formatPercent(risk.codeization?.code_coverage_percent)}</dd></div><div><dt>当前调查</dt><dd>{risk.recent_investigation?.status || '未启动'}</dd></div></dl>
        </section>
      </div>

      <section className="panel risk-lifecycle-panel">
        <div className="section-heading"><div><span className="eyebrow">L4 · LIFECYCLE</span><h3>风险生命周期</h3></div><span className="legend">按时间顺序</span></div>
        {timelineQuery.isError ? <p className="form-error" role="alert">生命周期加载失败，请重试。</p> : null}
        {timeline.length ? <ol aria-label="风险生命周期时间线" className="timeline">{timeline.map((event, index) => <TimelineItem event={event} key={event.id || `${event.at}-${index}`} />)}</ol> : <div className="empty-state compact"><p>{timelineQuery.isLoading ? '正在加载生命周期…' : '暂无生命周期记录。'}</p></div>}
      </section>

      <section className="panel risk-ai-panel">
        <div className="section-heading"><div><span className="eyebrow">AI ASSISTANT</span><h3>询问 AI</h3><p className="panel-lede">只读调查会基于当前风险、历史和证据给出补充判断。</p></div></div>
        <div className="risk-question-form"><label htmlFor="risk-question">问题</label><textarea id="risk-question" onChange={(event) => setQuestion(event.target.value)} placeholder="例如：这个风险最可能由哪个资源变化引起？" rows={3} value={question} /><div className="form-footer"><span className="muted">AI 调查不会执行写操作。</span><button className="button button-primary" disabled={asking} onClick={() => void askAi()} type="button">{asking ? '启动中…' : '询问 AI'}</button></div></div>
      </section>
    </section>
  )
}

function EvidenceItem({ item }: { item: RiskEvidence }) {
  return <article className="evidence-item"><header><strong>{item.evidence_key || item.evidence_type || '证据项'}</strong>{item.confidence == null ? null : <span className="mode-badge">置信度 {formatPercent(item.confidence * 100)}</span>}</header><p>{item.summary || '暂无证据摘要。'}</p><small>{item.source || '—'}</small></article>
}

function TimelineItem({ event }: { event: RiskTimelineEvent }) {
  return <li><strong>{event.label || statusLabel(event.to_status)}</strong><small>{formatDate(event.at)} · {event.source || 'SYSTEM'}</small>{event.reason ? <span>{event.reason}</span> : null}</li>
}
