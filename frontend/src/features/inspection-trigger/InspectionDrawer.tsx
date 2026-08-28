import { Button, Drawer, Select } from 'antd'
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

  const footer = run ? <Button autoInsertSpace={false} className="button button-secondary" onClick={onClose}>关闭</Button> : <><Button autoInsertSpace={false} className="button button-secondary" onClick={onClose}>取消</Button><Button autoInsertSpace={false} className="button button-primary" disabled={submitting || resourceTypes.length === 0} loading={submitting} onClick={() => void submit()} type="primary">{submitting ? '创建中…' : '开始巡检'}</Button></>

  return (
    <Drawer
      aria-labelledby="inspection-drawer-title"
      className="ai-drawer inspection-drawer"
      closeIcon={<span aria-hidden="true">×</span>}
      destroyOnHidden
      footer={footer}
      mask={{ closable: true }}
      onClose={onClose}
      open={open}
      rootClassName="inspection-drawer-root"
      styles={{ body: { display: 'flex', flexDirection: 'column', minHeight: 0, padding: 0 }, footer: { padding: '16px 24px' } }}
      title={<div className="drawer-title"><span className="eyebrow">MANUAL INSPECTION</span><h2 id="inspection-drawer-title">立即巡检</h2></div>}
      width={600}
    >
      <span data-testid="inspection-drawer-overlay" hidden />
      <div className="drawer-scroll">
        <label className="drawer-field">
          <span>巡检环境</span>
          <Select aria-label="本次巡检环境" disabled options={[{ value: environmentId, label: `当前环境 · ${environmentId}` }]} value={environmentId} />
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
    </Drawer>
  )
}
