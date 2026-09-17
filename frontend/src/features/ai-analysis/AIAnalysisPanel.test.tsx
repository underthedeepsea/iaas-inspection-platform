import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/http'
import { AIAnalysisPanel } from './AIAnalysisPanel'

afterEach(() => vi.restoreAllMocks())

it('runs only after a click and renders the synchronous explanation without streaming', async () => {
  const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'i', investigation_id: 'i', status: 'RESOLVED', conclusion: 'TTFT P95 超过阈值', result: {} } })
  render(<AIAnalysisPanel contextType="RESOURCE_RUN" environmentId="env" inspectionRunId="run" resourceCode="LLM_RUNTIME" />)
  expect(post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', {name:'开始 AI 分析'}))
  expect(await screen.findByText('TTFT P95 超过阈值')).toBeInTheDocument()
  expect(post).toHaveBeenCalledWith('/resource-types/LLM_RUNTIME/analysis', expect.objectContaining({inspection_run_id:'run',environment_id:'env'}))
  expect(screen.getByText('RESOLVED')).toBeInTheDocument()
})

it('shows provider failure while leaving the inspection view available', async () => {
  vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('offline'))
  render(<><p>巡检结果 FAIL</p><AIAnalysisPanel contextType="RESOURCE_RUN" environmentId="env" inspectionRunId="run" resourceCode="LLM_RUNTIME" /></>)
  fireEvent.click(screen.getByRole('button', {name:'开始 AI 分析'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('AI 分析暂不可用')
  expect(screen.getByText('巡检结果 FAIL')).toBeInTheDocument()
})
