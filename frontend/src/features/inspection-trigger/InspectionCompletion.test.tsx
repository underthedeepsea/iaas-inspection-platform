import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/http'
import { useInspectionSessionStore } from '../../stores/inspectionSessionStore'
import { InspectionDrawer } from './InspectionDrawer'

afterEach(() => {vi.restoreAllMocks(); useInspectionSessionStore.setState({active:null,lastCompleted:null})})
it.each([
  ['PARTIAL', '本次巡检部分完成', '查看本次巡检结果 →'],
  ['FAILED', '巡检失败', '查看失败详情'],
] as const)('restores %s and links to the exact result', async (status, heading, action) => {
  useInspectionSessionStore.getState().start({runId:'run-1',environmentId:'env-1',resourceTypes:['LLM_RUNTIME'],status,startedAt:''})
  vi.spyOn(apiClient,'get').mockResolvedValue({data:{run:{status,error_message:'执行记录'},code_plugins:[],summary:{pass_count:1,fail_count:2,risk_count:2}}})
  const post = vi.spyOn(apiClient,'post')
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><Routes><Route path="/" element={<InspectionDrawer environmentId="env-1" environmentName="演示环境 · mvp" open onClose={vi.fn()} resourceTypes={[]} />} /><Route path="/inspection-runs/:runId" element={<h2>恢复的巡检结果</h2>} /></Routes></MemoryRouter></QueryClientProvider>)
  expect(screen.getByRole('heading',{name:heading})).toBeInTheDocument()
  expect(screen.getByText('演示环境 · mvp')).toBeInTheDocument()
  expect(await screen.findByText('关联风险')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:action}))
  expect(screen.getByRole('heading',{name:'恢复的巡检结果'})).toBeInTheDocument()
  expect(post).not.toHaveBeenCalled()
})
