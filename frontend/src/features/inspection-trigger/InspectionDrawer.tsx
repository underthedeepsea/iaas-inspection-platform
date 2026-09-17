import { useNavigate } from 'react-router-dom'
import { useInspectionSessionStore } from '../../stores/inspectionSessionStore'
import { InspectionCompletion } from './InspectionCompletion'
import { Button, Drawer, Select } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import type { ResourceType } from '../../api/resources'
import { triggerInspection, type TriggerInspectionResponse } from '../../api/inspections'

import { InspectionProgress } from './InspectionProgress'
import { InspectionScopePreview } from './InspectionScopePreview'
import { ResourceTypeSelector } from './ResourceTypeSelector'

export function InspectionDrawer({
  environmentId,
  environmentName = '当前环境',
  open,
  onClose,
  resourceTypes,
  onTriggered,
}: {
  environmentId: string
  environmentName?: string
  open: boolean
  onClose: () => void
  resourceTypes: ResourceType[]
  onTriggered?: (run: TriggerInspectionResponse) => void
}) {
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [validationError, setValidationError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const active = useInspectionSessionStore(state => state.active)
  const start = useInspectionSessionStore(state => state.start)
  const finish = useInspectionSessionStore(state => state.finish)
  const dismiss = useInspectionSessionStore(state => state.dismiss)
  const run = active?.environmentId === environmentId ? active : null
  const terminal = run && run.status !== 'RUNNING' ? run.status : null
  const close = useCallback(() => { if (run && terminal) dismiss(run.runId); onClose() }, [run, terminal, dismiss, onClose])
  const goTo = (url: string) => { close(); navigate(url) }

  useEffect(() => {
    if (!open) return
    setSelectedCodes([])
    setValidationError('')
    setRequestError('')
  }, [open, environmentId])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [close, open])

  const toggle = (code: string) => {
    setValidationError('')
    setSelectedCodes((current) => current.includes(code) ? current.filter((item) => item !== code) : [...current, code])
  }

  const submit = async () => {
    if (submitting || (active && active.status === 'RUNNING')) return
    if (selectedCodes.length === 0) {
      setValidationError('请至少选择一种巡检资源')
      return
    }
    setSubmitting(true)
    setRequestError('')
    try {
      const created = await triggerInspection({ environmentId, resourceTypes: selectedCodes })
      start({environmentId,runId:created.inspection_run_id || created.id,resourceTypes:[...selectedCodes],status:'RUNNING',startedAt:new Date().toISOString()})
      onTriggered?.(created)
    } catch {
      setRequestError('巡检任务创建失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  const footer = run ? <div className="inspection-footer"><Button autoInsertSpace={false} onClick={close}>关闭</Button>{terminal ? <><Button autoInsertSpace={false} onClick={() => goTo('/rules')}>查看规则库</Button><Button autoInsertSpace={false} className="button-primary" onClick={() => goTo(`/inspection-runs/${run.runId}?environment=${environmentId}`)} type="primary">{terminal === 'FAILED' ? '查看失败详情' : '查看本次巡检结果 →'}</Button></> : null}</div> : <><Button autoInsertSpace={false} className="button button-secondary" onClick={close}>取消</Button><Button autoInsertSpace={false} className="button button-primary" disabled={submitting || resourceTypes.length === 0 || Boolean(active && active.environmentId !== environmentId && active.status === 'RUNNING')} loading={submitting} onClick={() => void submit()} type="primary">{submitting ? '创建中…' : '开始巡检'}</Button></>


  return (
    <Drawer
      aria-labelledby="inspection-drawer-title"
      className="ai-drawer inspection-drawer"
      closeIcon={<span aria-hidden="true">×</span>}
      footer={footer}
      mask={{ closable: true }}
      onClose={close}
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
          <Select aria-label="本次巡检环境" disabled options={[{ value: environmentId, label: environmentName }]} value={environmentId} />
        </label>

          {run ? (
            <>
              {terminal ? <InspectionCompletion environmentId={environmentId} resourceTypes={run.resourceTypes} runId={run.runId} status={terminal} /> : <section className="inspection-created panel">
                <span className="eyebrow">RUN CREATED</span>
                <strong>巡检任务已创建</strong>
                <p>任务 {run.runId} 正在执行，关闭面板后可继续查看。</p>
              </section>}
              <InspectionProgress key={run.runId} onTerminal={({runId,status}) => finish(runId,status)} runId={run.runId} />
            </>
          ) : (
            <>
              <section className="drawer-section">
                <div className="section-heading"><div><span className="eyebrow">RESOURCE SCOPE</span><h3>选择巡检资源</h3></div><span className="legend">可多选</span></div>
                {resourceTypes.length ? <ResourceTypeSelector onToggle={toggle} resources={resourceTypes} selectedCodes={selectedCodes} /> : <div className="empty-state compact"><strong>暂无可巡检资源</strong><p>当前环境没有已启用的资源类型。</p></div>}
              </section>
              {active?.status === 'RUNNING' && active.environmentId !== environmentId ? <p className="form-error" role="status">其他环境的巡检正在执行。<button className="text-link button-quiet" onClick={() => goTo(`/?environment=${active.environmentId}`)}>返回该环境查看</button></p> : null}
              <InspectionScopePreview resources={resourceTypes} selectedCodes={selectedCodes} />
              {validationError ? <p className="form-error" role="alert">{validationError}</p> : null}
              {requestError ? <p className="form-error" role="alert">{requestError}</p> : null}
            </>
          )}
      </div>
    </Drawer>
  )
}
