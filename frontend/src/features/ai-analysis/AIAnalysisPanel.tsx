import { useEffect, useState } from 'react'

import {
  createResourceInvestigation,
  getInvestigation,
  type Investigation,
  type InvestigationContextType,
} from '../../api/investigations'

import { AIAnalysisSummary } from './AIAnalysisSummary'
import { AIConversation } from './AIConversation'
import { EvidencePanel } from './EvidencePanel'
import { InvestigationTimeline } from './InvestigationTimeline'
import { useInvestigationStream } from './useInvestigationStream'

export function AIAnalysisPanel({
  contextType,
  environmentId,
  inspectionRunId,
  initialInvestigationId,
  resourceCode,
}: {
  contextType: InvestigationContextType
  environmentId: string
  inspectionRunId?: string
  initialInvestigationId?: string
  resourceCode: string
}) {
  const storageKey = `iaas-investigation:${contextType}:${resourceCode}:${inspectionRunId ?? 'trend'}`
  const [investigationId, setInvestigationId] = useState(() => {
    if (initialInvestigationId) return initialInvestigationId
    if (typeof window === 'undefined') return undefined
    try {
      return window.localStorage.getItem(storageKey) ?? undefined
    } catch {
      return undefined
    }
  })
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const { events, recovering } = useInvestigationStream(investigationId)

  useEffect(() => {
    if (!investigationId) return
    let active = true
    void getInvestigation(investigationId)
      .then((value) => {
        if (!active) return
        setInvestigation(value)
        if (value.conversation_id) setConversationId(value.conversation_id)
      })
      .catch(() => { if (active) setError('AI 调查状态加载失败') })
    return () => { active = false }
  }, [investigationId])

  const start = async () => {
    setStarting(true)
    setError('')
    try {
      const created = await createResourceInvestigation(resourceCode, {
        contextType,
        environmentId,
        inspectionRunId,
      })
      const createdId = created.investigation_id || created.id
      setInvestigationId(createdId)
      if (created.conversation_id) setConversationId(created.conversation_id)
      try {
        window.localStorage.setItem(storageKey, createdId)
      } catch {
        // Persistence is best-effort in restricted browser contexts.
      }
    } catch {
      setError('AI 分析启动失败，请稍后重试')
    } finally {
      setStarting(false)
    }
  }

  const startFollowUp = (nextInvestigationId: string) => {
    setInvestigationId(nextInvestigationId)
    try {
      window.localStorage.setItem(storageKey, nextInvestigationId)
    } catch {
      // Persistence is best-effort in restricted browser contexts.
    }
  }

  const hasFailure = events.some((event) => event.event_type === 'tool.failed')
  return (
    <section aria-label="AI 分析面板" className="ai-analysis-panel">
      <header className="section-heading ai-analysis-header">
        <div><span className="eyebrow">ASSISTED INVESTIGATION</span><h2>AI 分析</h2><p>{contextType === 'RESOURCE_RUN' ? '本轮资源巡检分析' : '资源类型趋势分析'}</p></div>
        <button className="button button-primary" disabled={starting} onClick={() => void start()} type="button">{starting ? '启动中…' : investigationId ? '重新分析' : '开始 AI 分析'}</button>
      </header>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {recovering ? <p className="progress-recovering" role="status">正在恢复 AI 分析状态…</p> : null}
      {hasFailure ? <p className="form-error" role="alert">部分证据工具失败，结论基于可用证据</p> : null}
      {investigationId ? (
        <>
          <InvestigationTimeline events={events} />
          <div className="ai-analysis-body">
            <AIAnalysisSummary events={events} investigation={investigation} />
            <EvidencePanel events={events} />
            <AIConversation conversationId={conversationId} onTurnStarted={startFollowUp} />
          </div>
        </>
      ) : <div className="empty-state compact"><p>开始分析后，这里会显示证据关联和研判过程。</p></div>}
    </section>
  )
}
