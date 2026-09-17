import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { apiClient } from '../../api/http'
import { DashboardAIBar } from './DashboardAIBar'

afterEach(() => vi.restoreAllMocks())
it('asks about the exact run and shows a labeled AI answer with CODE references', async () => {
  const post = vi.spyOn(apiClient, 'post').mockResolvedValue({data: {answer:'TTFT 超出阈值', confidence:.7, inspection_run_id:'run-1', source:{type:'AI',provider:'fake',model:'test'}, references:[{type:'CHECK_RESULT',id:'check-1',label:'TTFT P95',source:'CODE'}]}})
  render(<MemoryRouter><DashboardAIBar environmentId="env-1" runId="run-1" /></MemoryRouter>)
  expect(post).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('textbox'), {target:{value:'哪些是代码分析？'}})
  fireEvent.click(screen.getByRole('button', {name:'发送问题'}))
  await screen.findByText('TTFT 超出阈值')
  expect(post).toHaveBeenCalledExactlyOnceWith('/dashboard/ask', {environment_id:'env-1',question:'哪些是代码分析？',inspection_run_id:'run-1'})
  expect(screen.getByText('TTFT P95').closest('a')).toHaveAttribute('href', '/inspection-runs/run-1?environment=env-1#check-check-1')
  expect(screen.getAllByText('CODE').length).toBeGreaterThan(0)
})
it('keeps the question available to retry after a provider failure', async () => {
  vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('unavailable'))
  render(<MemoryRouter><DashboardAIBar environmentId="env-1" /></MemoryRouter>)
  fireEvent.change(screen.getByRole('textbox'), {target:{value:'解释结果'}})
  fireEvent.click(screen.getByRole('button', {name:'发送问题'}))
  await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  expect(screen.getByRole('textbox')).toHaveValue('解释结果')
  expect(screen.getByRole('button', {name:'发送问题'})).not.toBeDisabled()
})
it('discards an answer that arrives after switching environments', async () => {
  let resolve: (value: unknown) => void = () => {}
  vi.spyOn(apiClient, 'post').mockReturnValue(new Promise(r => {resolve = r}) as never)
  const {rerender} = render(<MemoryRouter><DashboardAIBar environmentId="env-1" runId="run-1" /></MemoryRouter>)
  fireEvent.change(screen.getByRole('textbox'), {target:{value:'解释结果'}})
  fireEvent.click(screen.getByRole('button',{name:'发送问题'}))
  rerender(<MemoryRouter><DashboardAIBar environmentId="env-2" /></MemoryRouter>)
  resolve({data:{answer:'来自旧环境的解释',confidence:.5,inspection_run_id:'run-1',source:{type:'AI'},references:[]}})
  await waitFor(() => expect(screen.getByRole('button',{name:'发送问题'})).not.toBeDisabled())
  expect(screen.queryByText('来自旧环境的解释')).not.toBeInTheDocument()
})
