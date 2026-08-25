import { useEffect, useState } from 'react'

import type { ResourceType } from '../../api/resources'
import { triggerInspection, type TriggerInspectionResponse } from '../../api/inspections'

import { InspectionScopePreview } from './InspectionScopePreview'
import { InspectionProgress } from './InspectionProgress'
import { ResourceTypeSelector } from './ResourceTypeSelector'

export function InspectionDrawer({
  environmentId,
  open,
  onClose,
  resourceTypes,
  onTriggered,
}: {
  environmentId: string
  open: boolean
  onClose: () => void
  resourceTypes: ResourceType[]
  onTriggered?: (run: TriggerInspectionResponse) => void
}) {
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [validationError, setValidationError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [run, setRun] = useState<TriggerInspectionResponse | null>(null)

  useEffect(() => {
    if (!open) return
    setSelectedCodes([])
    setValidationError('')
    setRequestError('')
    setRun(null)
  }, [open])

  if (!open) return null

  const toggle = (code: string) => {
    setValidationError('')
    setSelectedCodes((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code],
    )
  }

  const submit = async () => {
    if (selectedCodes.length === 0) {
      setValidationError('请至少选择一种巡检资源')
      return
    }
    setSubmitting(true)
    setRequestError('')
    try {
      const created = await triggerInspection({ environmentId, resourceTypes: selectedCodes })
      setRun(created)
      onTriggered?.(created)
    } catch {
      setRequestError('巡检任务创建失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div aria-label="立即巡检" role="dialog" style={{ background: '#ffffff', borderLeft: '1px solid #e5e7eb', boxShadow: '-8px 0 32px rgb(15 23 42 / 10%)', maxWidth: 560, minHeight: '100vh', padding: 28, position: 'fixed', right: 0, top: 0, width: 'min(100%, 560px)', zIndex: 10 }}>
      <header style={{ alignItems: 'center', display: 'flex', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ margin: 0 }}>立即巡检</h2>
          <p style={{ color: '#6b7280', fontSize: 13 }}>选择本次需要覆盖的资源类型。</p>
        </div>
        <button aria-label="关闭巡检抽屉" onClick={onClose} type="button">×</button>
      </header>
      {run ? (
        <>
          <section aria-label="巡检进度模式" style={{ background: '#fff7ed', borderRadius: 12, marginTop: 20, padding: 16 }}>
            <strong>巡检任务已创建</strong>
            <p style={{ color: '#4b5563', fontSize: 13 }}>任务 {run.inspection_run_id || run.id} 正在准备执行。</p>
          </section>
          <InspectionProgress runId={run.inspection_run_id || run.id} />
        </>
      ) : (
        <>
          <div style={{ marginTop: 20 }}>
            <ResourceTypeSelector onToggle={toggle} resources={resourceTypes} selectedCodes={selectedCodes} />
          </div>
          <div style={{ marginTop: 20 }}>
            <InspectionScopePreview resources={resourceTypes} selectedCodes={selectedCodes} />
          </div>
          {validationError ? <p role="alert" style={{ color: '#dc2626', fontSize: 13 }}>{validationError}</p> : null}
          {requestError ? <p role="alert" style={{ color: '#dc2626', fontSize: 13 }}>{requestError}</p> : null}
          <button disabled={submitting} onClick={() => void submit()} style={{ background: '#f97316', border: 0, borderRadius: 9, color: '#ffffff', cursor: 'pointer', marginTop: 20, padding: '10px 16px' }} type="button">
            {submitting ? '创建中…' : '开始巡检'}
          </button>
        </>
      )}
    </div>
  )
}
