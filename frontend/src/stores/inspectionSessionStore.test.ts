import { afterEach, expect, it } from 'vitest'
import { useInspectionSessionStore } from './inspectionSessionStore'

afterEach(() => useInspectionSessionStore.setState({ active: null, lastCompleted: null }))
it('restores run identity from session storage and retains completed context after dismissal', async () => {
  const run = {environmentId:'env-1',runId:'run-1',resourceTypes:['LLM_RUNTIME'],status:'RUNNING' as const,startedAt:'2026-09-12T00:00:00Z'}
  useInspectionSessionStore.getState().start(run)
  const stored = sessionStorage.getItem('iaas-inspection-session')
  useInspectionSessionStore.setState({active:null})
  sessionStorage.setItem('iaas-inspection-session', stored!)
  await useInspectionSessionStore.persist.rehydrate()
  expect(useInspectionSessionStore.getState().active?.runId).toBe('run-1')
  useInspectionSessionStore.getState().finish('run-1', 'PARTIAL')
  useInspectionSessionStore.getState().dismiss('run-1')
  expect(useInspectionSessionStore.getState().active).toBeNull()
  expect(useInspectionSessionStore.getState().lastCompleted).toMatchObject({runId:'run-1',environmentId:'env-1',status:'PARTIAL'})
})
it('does not dismiss a running task or accept stale completion from a different run', () => {
  useInspectionSessionStore.getState().start({environmentId:'env',runId:'current',resourceTypes:[],status:'RUNNING',startedAt:''})
  useInspectionSessionStore.getState().finish('old', 'SUCCEEDED')
  useInspectionSessionStore.getState().dismiss('current')
  expect(useInspectionSessionStore.getState().active?.status).toBe('RUNNING')
  expect(useInspectionSessionStore.getState().lastCompleted).toBeNull()
})
