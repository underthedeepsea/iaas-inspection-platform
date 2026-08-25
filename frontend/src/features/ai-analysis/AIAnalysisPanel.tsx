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
    return window.localStorage.getItem(storageKey) ?? undefined
  })
  const [investigation, setInvestigation] = useState<Investigation | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const { events, recovering } = useInvestigationStream(investigationId)

  useEffect(() => {
    if (!investigationId) return
    let active = true
    void getInvestigation(investigationId)
      .then((value) => { if (active) setInvestigation(value) })
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
      window.localStorage.setItem(storageKey, createdId)
    } catch {
      setError('AI 分析启动失败，请稍后重试')
    } finally {
      setStarting(false)
    }
  }

  const hasFailure = events.some((event) => event.event_type === 'tool.failed')
  return (
    <section aria-label="AI 分析面板">
      <header style={{ alignItems: 'center', display: 'flex', justifyContent: 'space-between', marginBottom: 18 }}>
        <div>
          <h2 style={{ marginBottom: 5 }}>AI 分析</h2>
          <p style={{ color: '#6b7280', fontSize: 13, margin: 0 }}>{contextType === 'RESOURCE_RUN' ? '本轮资源巡检分析' : '资源类型趋势分析'}</p>
        </div>
        <button disabled={starting} onClick={() => void start()} type="button">{starting ? '启动中…' : investigationId ? '重新分析' : '开始 AI 分析'}</button>
      </header>
      {error ? <p role="alert" style={{ color: '#dc2626' }}>{error}</p> : null}
      {recovering ? <p role="status">正在恢复 AI 分析状态…</p> : null}
      {hasFailure ? <p role="alert" style={{ background: '#fef2f2', color: '#b91c1c', padding: 10 }}>部分证据工具失败，结论基于可用证据</p> : null}
      {investigationId ? (
        <>
          <InvestigationTimeline events={events} />
          <div style={{ display: 'grid', gap: 18, marginTop: 20 }}>
            <AIAnalysisSummary events={events} investigation={investigation} />
            <EvidencePanel events={events} />
            <AIConversation />
          </div>
        </>
      ) : <p style={{ color: '#6b7280' }}>开始分析后，这里会显示证据关联和研判过程。</p>}
    </section>
  )
}
