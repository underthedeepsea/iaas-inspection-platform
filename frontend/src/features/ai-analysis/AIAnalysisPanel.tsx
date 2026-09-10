import { useEffect, useState } from 'react'
import { createResourceInvestigation, getInvestigation, type Investigation, type InvestigationContextType } from '../../api/investigations'
import { AIAnalysisSummary } from './AIAnalysisSummary'

export function AIAnalysisPanel({ contextType, environmentId, inspectionRunId, initialInvestigationId, resourceCode }: {
  contextType: InvestigationContextType
  environmentId: string
  inspectionRunId?: string
  initialInvestigationId?: string
  resourceCode: string
}) {
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setInvestigation(null)
    if (initialInvestigationId) void getInvestigation(initialInvestigationId).then(value => { if (active) setInvestigation(value) }).catch(() => { if (active) setError('AI 分析暂不可用') })
    return () => { active = false }
  }, [initialInvestigationId, environmentId, inspectionRunId, resourceCode])
  const start = async () => {
    setStarting(true)
    setError('')
    try {
      setInvestigation(await createResourceInvestigation(resourceCode, { contextType, environmentId, inspectionRunId }))
    } catch { setError('AI 分析暂不可用') }
    finally { setStarting(false) }
  }
  return <section aria-label="AI 分析面板" className="ai-analysis-panel">
    <header className="section-heading ai-analysis-header">
      <div><h2>AI 分析</h2><p>按需解释本轮检查与上一轮证据。规则决定状态，AI 解释状态。</p></div>
      <button className="button button-primary" disabled={starting} onClick={() => void start()} type="button">{starting ? '分析中…' : investigation ? '重新分析' : '开始 AI 分析'}</button>
    </header>
    {error ? <p role="alert">{error}</p> : null}
    {investigation ? <AIAnalysisSummary events={[]} investigation={investigation} /> : <p>点击开始分析后查看解释。AI 不改变巡检结果。</p>}
  </section>
}
