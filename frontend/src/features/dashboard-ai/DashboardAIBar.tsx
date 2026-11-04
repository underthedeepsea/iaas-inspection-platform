import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSavedDashboard, streamDashboard, type DashboardAnswer } from '../../api/dashboardAI'
import { getDashboardFacts, type InspectionFactReport } from '../../api/inspectionFacts'
import { InspectionFacts } from '../inspection-history/InspectionFacts'
import { getApiError } from '../../api/http'
import { ReadableExplanation } from './ReadableExplanation'

const prompts = ['详细解读本次风险', '哪些是代码分析？', '为什么 TTFT 异常？', '对比上一次']

export function DashboardAIBar({ environmentId, runId, resultMode = false, facts, showFacts = true, boundRun = false, cutoff, disabledReason }: { environmentId: string; runId?: string; resultMode?: boolean; facts?: InspectionFactReport; showFacts?: boolean; boundRun?: boolean; cutoff?: string | null; disabledReason?: string }) {
  const [report, setReport] = useState<InspectionFactReport | null>(facts ?? null)
  const [factsError, setFactsError] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<DashboardAnswer | null>(null)
  const [error, setError] = useState('')
  const [savedState, setSavedState] = useState('')
  const [pending, setPending] = useState(false)
  const generation = useRef(0)
  const activeRequest = useRef<AbortController | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [fragments, setFragments] = useState(0)
  const [stage, setStage] = useState<'generating' | 'validating'>('generating')
  const startedAt = useRef(0)
  useEffect(() => {
    if (!pending) return
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [pending])
  useEffect(() => {
    generation.current += 1
    activeRequest.current?.abort()
    activeRequest.current = null
    setAnswer(null)
    setError('')
    setPending(false)
    setSavedState(runId ? '正在读取已保存解读…' : '')
    const loadGeneration = generation.current
    if (runId) void getSavedDashboard(environmentId, runId).then(value => {
      if (generation.current !== loadGeneration) return
      if (value.status === 'SAVED' && value.answer && value.saved
        && value.answer.inspection_run_id === runId && value.saved.inspection_run_id === runId
        && value.saved.environment_id === environmentId && value.answer.ai_status === 'ACCEPTED') {
        setAnswer({...value.answer, saved: value.saved})
        setSavedState('已保存解读')
      } else setSavedState('暂无已保存解读')
    }).catch(() => { if (generation.current === loadGeneration) setSavedState('暂时无法读取已保存解读；未触发生成。') })
    return () => { generation.current += 1; activeRequest.current?.abort(); activeRequest.current = null }
  }, [environmentId, runId])
  useEffect(() => {
    let active = true
    setReport(facts ?? null)
    setFactsError('')
    if (!facts && showFacts) void getDashboardFacts(environmentId, runId).then(value => { if (active) setReport(value) }).catch(() => { if (active) setFactsError('暂时无法读取资源事实，请查看巡检结果。') })
    return () => { active = false }
  }, [environmentId, runId, facts, showFacts])
  const blocked = disabledReason || (boundRun && (!runId || !facts || facts.inspection_run_id !== runId) ? '本轮冻结报告尚不可用，不能开始解读。' : '')
  const stop = () => {
    generation.current += 1
    activeRequest.current?.abort()
    activeRequest.current = null
    setPending(false)
    setError('已停止解读。CODE 巡检事实已保留，可以重新提问。')
  }
  const submit = async (requested = question) => {
    if (!requested.trim() || activeRequest.current || blocked) return
    const controller = new AbortController()
    activeRequest.current = controller
    const requestGeneration = ++generation.current
    startedAt.current = Date.now()
    setElapsed(0)
    setFragments(0)
    setStage('generating')
    setAnswer(null)
    setPending(true)
    setError('')
    try {
      const response = await streamDashboard(environmentId, requested.trim(), runId, controller.signal, event => {
        if (generation.current !== requestGeneration || controller.signal.aborted) return
        if (event.type === 'facts') { if (runId && event.data.inspection_run_id !== runId) throw new Error('解读事实与所选Run不符，已丢弃。'); setReport(event.data) }
        if (event.type === 'status') setStage(event.data.stage)
        if (event.type === 'progress') setFragments(event.data.fragments)
      })
      if (generation.current === requestGeneration && !controller.signal.aborted) { if (runId && response.inspection_run_id !== runId) throw new Error('解读结果与所选Run不符，已丢弃。'); setAnswer(response) }
    } catch (failure) {
      if (generation.current === requestGeneration) setError(getApiError(failure)?.message ?? (failure instanceof Error ? failure.message : 'AI 解读暂不可用，请稍后重试。CODE 巡检事实已保留。'))
    } finally {
      if (generation.current === requestGeneration) {
        activeRequest.current = null
        setPending(false)
      }
    }
  }
  return <>{showFacts && report ? <InspectionFacts report={report} environmentId={environmentId} /> : null}{showFacts && factsError ? <p className="muted">{factsError}</p> : null}<section className={`dashboard-ai${resultMode ? ' result-ai' : ''}`} id="ai-explanation" aria-label="AI 巡检助手">
    <div className="ai-composer-heading"><span className="ai-monogram" aria-hidden="true">AI</span><div><h3>{resultMode ? 'AI 解读本次结果' : '从一个问题，读懂巡检'}</h3><p>基于代码检查与风险证据，按需解释异常。</p></div><span className="analysis-source-ai source-badge">AI · 只读解释</span></div>
    {boundRun ? <div className="bound-ai-context"><p>仅本轮冻结事实 · RUN {runId}</p><p>事实截止：{cutoff ?? '当时未记录截止时间'}；事实由代码记录，AI仅选择可能影响与核查建议。</p><p>当前输出协议仅支持受约束解读，不支持任意自由问答或上次运行对比。</p></div> : null}{blocked ? <p role="status">{blocked}</p> : null}<form onSubmit={event => { event.preventDefault(); void submit() }}>
      <button className="button button-primary ai-detail-action" disabled={pending || !!blocked} onClick={() => { setQuestion('详细解读本次风险'); void submit('详细解读本次风险') }} type="button">{pending ? '正在详细解读…' : '详细解读本次风险 ↗'}</button><div className="ai-composer-input"><textarea aria-label="向 AI 巡检助手提问" disabled={pending || !!blocked || boundRun} maxLength={2000} onChange={e => setQuestion(e.target.value)} onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void submit()}}} placeholder="问我：本次巡检发现了什么？哪些是代码发现的？为什么 TTFT 异常？" rows={2} value={question} /><button aria-label="发送问题" className="ai-send-button" disabled={!question.trim() || pending || !!blocked || boundRun} type="submit">{pending ? '解读中…' : '发送 ↗'}</button></div>
      <div className="ai-composer-footer"><div className="ai-quick-prompts">{(boundRun ? prompts.slice(0, 2) : prompts).map(prompt => <button disabled={pending || !!blocked} key={prompt} onClick={() => { setQuestion(prompt); void submit(prompt) }} type="button">{prompt}</button>)}</div><span className="ai-context">{runId ? <>本次巡检 <span className="mono">{runId.slice(0, 8)}</span></> : '上下文：当前环境最近完成的巡检'}</span></div>
    </form>
    {savedState ? <p className="muted">{savedState}</p> : null}
    {answer?.saved ? <div className="bound-ai-context"><p>已保存解读 · 生成于 {answer.saved.generated_at}</p><p>事实截止：{answer.fact_cutoff ?? '未记录'} · {answer.source.model} · prompt rev{answer.prompt?.revision ?? '未记录'}</p><p>归档于 {answer.saved.created_at} · 消息 {answer.saved.message_id}</p></div> : null}
    {pending ? <div className="ai-stream-progress" role="status" aria-live="polite"><div><strong>{stage === 'validating' ? '正在校验完整解读' : '正在生成并校验解读'}</strong><p>已用 {elapsed} 秒 · {fragments ? '模型已开始输出，正在整理解读' : '等待模型开始输出'}。校验完成后展示 AI 建议。</p>{fragments ? <small>已收到 {fragments} 个模型片段</small> : null}{report ? <p>CODE 的 {report.check_count} 条检查事实已保留。</p> : null}</div><button className="button" onClick={stop} type="button">停止解读</button></div> : null}
    {error ? <p className="ai-error" role="alert">{error}</p> : null}
    {answer ? <div aria-live="polite" className="dashboard-ai-answer"><div className="ai-answer-heading"><span className={`${answer.grounded_report ? 'analysis-source-code' : 'analysis-source-ai'} source-badge`}>{answer.grounded_report ? 'CODE' : 'AI'}</span><strong>{answer.grounded_report ? '逐资源事实与核查建议' : '结果解读'}</strong><small>{answer.source.provider === 'fake' ? '模拟 AI · ' : ''}{answer.source.model}</small><Link to={`/inspection-runs/${answer.inspection_run_id}?environment=${environmentId}`}>RUN {answer.inspection_run_id.slice(0, 8)} ↗</Link></div><ReadableExplanation answer={answer} report={report} environmentId={environmentId} />{answer.truncated ? <p className="muted">本次 AI 输入包含 {answer.selected_count ?? '部分'} / {answer.check_count ?? '全部'} 条检查{answer.omitted_count != null ? `，省略 ${answer.omitted_count} 条检查` : ''}；部分指标可能精简，完整 CODE 事实请查看“资源与异常指标”与巡检结果页。</p> : null}{!answer.grounded_report ? <div className="ai-references"><span>依据</span>{answer.references.map(ref => <Link className="ai-reference" key={`${ref.type}-${ref.id}`} to={ref.type === 'RISK' ? `/risks/${ref.id}?environment=${environmentId}` : ref.type === 'CODE_PLUGIN' ? `/rules#${ref.id}` : `/inspection-runs/${answer.inspection_run_id}?environment=${environmentId}#check-${ref.id}`}><span className="analysis-source-code source-badge">CODE</span><span>{ref.label}</span></Link>)}</div> : null}</div> : null}
    <div className="source-legend"><span><span className="analysis-source-code source-badge">CODE</span> 确定性规则判定</span><span>{resultMode ? 'AI 不参与上面的 PASS / FAIL 判定。' : 'AI 按需解释，不修改检查结果。'}</span></div>
  </section></>
}
