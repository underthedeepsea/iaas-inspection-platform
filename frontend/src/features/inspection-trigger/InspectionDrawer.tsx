import { useEffect, useState } from 'react'

import type { ResourceType } from '../../api/resources'
import { triggerInspection, type TriggerInspectionResponse } from '../../api/inspections'

import { InspectionProgress } from './InspectionProgress'
import { InspectionScopePreview } from './InspectionScopePreview'
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
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, open])

  if (!open) return null

  const toggle = (code: string) => {
    setValidationError('')
    setSelectedCodes((current) => current.includes(code) ? current.filter((item) => item !== code) : [...current, code])
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
    <>
      <div className="drawer-backdrop" data-testid="inspection-drawer-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }} />
      <aside aria-labelledby="inspection-drawer-title" aria-modal="true" className="ai-drawer inspection-drawer" role="dialog">
        <header className="drawer-header">
          <div><span className="eyebrow">MANUAL INSPECTION</span><h2 id="inspection-drawer-title">立即巡检</h2></div>
          <button aria-label="关闭巡检抽屉" className="icon-button" onClick={onClose} type="button">×</button>
        </header>

        <div className="drawer-scroll">
          <label className="drawer-field">
            <span>巡检环境</span>
            <select aria-label="本次巡检环境" disabled value={environmentId}>
              <option value={environmentId}>当前环境 · {environmentId}</option>
            </select>
          </label>

          {run ? (
            <>
              <section className="inspection-created panel">
                <span className="eyebrow">RUN CREATED</span>
                <strong>巡检任务已创建</strong>
                <p>任务 {run.inspection_run_id || run.id} 正在准备执行，Drawer 会持续保留执行状态。</p>
              </section>
              <InspectionProgress runId={run.inspection_run_id || run.id} />
            </>
          ) : (
            <>
              <section className="drawer-section">
                <div className="section-heading"><div><span className="eyebrow">RESOURCE SCOPE</span><h3>选择巡检资源</h3></div><span className="legend">可多选</span></div>
                {resourceTypes.length ? <ResourceTypeSelector onToggle={toggle} resources={resourceTypes} selectedCodes={selectedCodes} /> : <div className="empty-state compact"><strong>暂无可巡检资源</strong><p>当前环境没有已启用的资源类型。</p></div>}
              </section>
              <InspectionScopePreview resources={resourceTypes} selectedCodes={selectedCodes} />
              {validationError ? <p className="form-error" role="alert">{validationError}</p> : null}
              {requestError ? <p className="form-error" role="alert">{requestError}</p> : null}
            </>
          )}
        </div>

        <footer className="drawer-footer">
          {run ? <button className="button button-secondary" onClick={onClose} type="button">关闭</button> : <><button className="button button-secondary" onClick={onClose} type="button">取消</button><button className="button button-primary" disabled={submitting || resourceTypes.length === 0} onClick={() => void submit()} type="button">{submitting ? '创建中…' : '开始巡检'}</button></>}
        </footer>
      </aside>
    </>
  )
}
