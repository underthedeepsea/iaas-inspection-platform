import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { askDashboard, type DashboardAnswer } from '../../api/dashboardAI'
import { getApiError } from '../../api/http'

const prompts = ['本次巡检发现了什么？', '哪些是代码分析？', '为什么 TTFT 异常？', '对比上一次']

export function DashboardAIBar({ environmentId, runId, resultMode = false }: { environmentId: string; runId?: string; resultMode?: boolean }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<DashboardAnswer | null>(null)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const generation = useRef(0)
  useEffect(() => {
    generation.current += 1
    setAnswer(null)
    setError('')
    setPending(false)
    return () => { generation.current += 1 }
  }, [environmentId, runId])
  const submit = async () => {
    if (!question.trim() || pending) return
    const requestGeneration = generation.current
    setPending(true)
    setError('')
    try {
      const response = await askDashboard(environmentId, question.trim(), runId)
      if (generation.current === requestGeneration) setAnswer(response)
    } catch (failure) {
      if (generation.current === requestGeneration) setError(getApiError(failure)?.message ?? 'AI 解读暂不可用，请稍后重试。巡检结果已保留。')
    } finally {
      if (generation.current === requestGeneration) setPending(false)
    }
  }
  return <section className={`dashboard-ai${resultMode ? ' result-ai' : ''}`} id="ai-explanation" aria-label="AI 巡检助手">
    <div className="ai-composer-heading"><span className="ai-monogram" aria-hidden="true">AI</span><div><h3>{resultMode ? 'AI 解读本次结果' : '从一个问题，读懂巡检'}</h3><p>基于代码检查与风险证据，按需解释异常。</p></div><span className="analysis-source-ai source-badge">AI · 只读解释</span></div>
    <form onSubmit={event => { event.preventDefault(); void submit() }}>
      <div className="ai-composer-input"><textarea aria-label="向 AI 巡检助手提问" disabled={pending} maxLength={2000} onChange={e => setQuestion(e.target.value)} onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void submit()}}} placeholder="问我：本次巡检发现了什么？哪些是代码发现的？为什么 TTFT 异常？" rows={2} value={question} /><button aria-label="发送问题" className="ai-send-button" disabled={!question.trim() || pending} type="submit">{pending ? '解读中…' : '发送 ↗'}</button></div>
      <div className="ai-composer-footer"><div className="ai-quick-prompts">{prompts.map(prompt => <button disabled={pending} key={prompt} onClick={() => setQuestion(prompt)} type="button">{prompt}</button>)}</div><span className="ai-context">{runId ? <>本次巡检 <span className="mono">{runId.slice(0, 8)}</span></> : '上下文：当前环境最近完成的巡检'}</span></div>
    </form>
    {error ? <p className="ai-error" role="alert">{error}</p> : null}
    {answer ? <div aria-live="polite" className="dashboard-ai-answer"><div className="ai-answer-heading"><span className="analysis-source-ai source-badge">AI</span><strong>结果解读</strong><small>{answer.source.provider === 'fake' ? '模拟 AI · ' : ''}{answer.source.model}</small><Link to={`/inspection-runs/${answer.inspection_run_id}?environment=${environmentId}`}>RUN {answer.inspection_run_id.slice(0, 8)} ↗</Link></div><p>{answer.answer}</p>{answer.truncated ? <p className="muted">本次解释使用最多 50 条检查与 20 条风险，完整结果请查看巡检结果页。</p> : null}<div className="ai-references"><span>依据</span>{answer.references.map(ref => <Link className="ai-reference" key={`${ref.type}-${ref.id}`} to={ref.type === 'RISK' ? `/risks/${ref.id}?environment=${environmentId}` : ref.type === 'CODE_PLUGIN' ? `/rules#${ref.id}` : `/inspection-runs/${answer.inspection_run_id}?environment=${environmentId}#check-${ref.id}`}><span className="analysis-source-code source-badge">CODE</span><span>{ref.label}</span></Link>)}</div></div> : null}
    <div className="source-legend"><span><span className="analysis-source-code source-badge">CODE</span> 确定性规则判定</span><span>{resultMode ? 'AI 不参与上面的 PASS / FAIL 判定。' : 'AI 按需解释，不修改检查结果。'}</span></div>
  </section>
}
