import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { apiClient } from '../../api/http'
import * as dashboard from '../../api/dashboardAI'
import type { DashboardAnswer, DashboardStreamEvent } from '../../api/dashboardAI'
import type { InspectionFactReport } from '../../api/inspectionFacts'
import { DashboardAIBar } from './DashboardAIBar'

const report: InspectionFactReport = {source:'CODE',inspection_run_id:'run-1',check_count:1,status_counts:{FAIL:1},omitted_count:0,risk_state_note:'历史检查 / 当前风险',checks:[{id:'check-1',check:'llm.performance_profile',check_name:'推理性能',asset_id:'asset-1',asset_name:'demo-dynamic / Model-8B',status:'FAIL',summary:'性能异常',quality:{state:'READY'},evidence_gaps:[],measurements:[{layer:'DYNAMIC',metric:'ttft.p95_ms',current:339.7773,boundary:308.75866}],risks:[]}]}
const answer:DashboardAnswer={answer:'不得显示的模型自由文本',confidence:.7,ai_status:'ACCEPTED',inspection_run_id:'run-1',source:{type:'AI',provider:'fake',model:'test'},references:[{type:'CHECK_RESULT',id:'check-1',label:'TTFT P95',source:'CODE'}],grounded_report:{source:'CODE',coverage_text:'CODE完整事实',comparison_text:'前次摘要未知',ai_status:'ACCEPTED',accepted_count:1,checks:[{id:'check-1',asset_name:'报告中的机器',source:'CODE',facts_text:'短期斜率 -9162596.9 bytes/s',ai_note:'',ai:{source:'AI',check_id:'check-1',impact:'内存下降可能影响承载能力；原因未确认',next_check:'核对进程内存与同期负载'}}]}}
const view=(environmentId='env-1',runId:string|undefined='run-1')=><MemoryRouter><DashboardAIBar environmentId={environmentId} runId={runId}/></MemoryRouter>
const click=()=>fireEvent.click(screen.getByRole('button',{name:'详细解读本次风险 ↗'}))
beforeEach(()=>vi.spyOn(apiClient,'get').mockResolvedValue({data:report}))
afterEach(()=>{vi.restoreAllMocks();vi.useRealTimers()})
it('asks exact context only on click and renders grounded report with references',async()=>{
  const stream=vi.spyOn(dashboard,'streamDashboard').mockResolvedValue(answer)
  render(view())
  expect(stream).not.toHaveBeenCalled()
  click()
  expect(await screen.findAllByText('短期斜率 -9162596.9 bytes/s')).toHaveLength(2)
  expect(stream).toHaveBeenCalledExactlyOnceWith('env-1','详细解读本次风险','run-1',expect.any(AbortSignal),expect.any(Function))
  expect(screen.getByText('TTFT P95').closest('a')).toHaveAttribute('href','/inspection-runs/run-1?environment=env-1#check-check-1')
  expect(screen.queryByText('不得显示的模型自由文本')).not.toBeInTheDocument()
  expect(screen.getByText('AI · 潜在影响与核查建议')).toBeInTheDocument()
})
it('shows actual progress before result, retains CODE facts on provider error, and can retry',async()=>{
  let reject!:(error:Error)=>void
  let onEvent!:(event:DashboardStreamEvent)=>void
  const stream=vi.spyOn(dashboard,'streamDashboard').mockImplementation((_e,_q,_r,_s,callback)=>{onEvent=callback;return new Promise((_resolve,rej)=>{reject=rej})})
  render(view())
  fireEvent.change(screen.getByRole('textbox'),{target:{value:'解释结果'}})
  fireEvent.click(screen.getByRole('button',{name:'发送问题'}))
  act(()=>{onEvent({type:'facts',data:report});onEvent({type:'progress',data:{fragments:3,content_bytes:60}})})
  expect(screen.getByRole('status')).toHaveTextContent('已收到 3 个模型片段')
  expect(screen.getByRole('status')).toHaveTextContent('校验完成后展示 AI 建议')
  expect(screen.queryByText('AI · 潜在影响与核查建议')).not.toBeInTheDocument()
  await act(async()=>reject(new Error('AI 暂不可用')))
  expect(screen.getByRole('alert')).toHaveTextContent('AI 暂不可用')
  expect(screen.getByText('308.759 ms')).toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveValue('解释结果')
  stream.mockResolvedValueOnce(answer)
  fireEvent.click(screen.getByRole('button',{name:'发送问题'}))
  expect(await screen.findAllByText('短期斜率 -9162596.9 bytes/s')).toHaveLength(2)
})
it.each(['stop','environment','run','unmount'])('aborts on %s and discards late progress/result',async kind=>{
  let signal!:AbortSignal, callback!:(event:DashboardStreamEvent)=>void, resolve!:(answer:DashboardAnswer)=>void
  vi.spyOn(dashboard,'streamDashboard').mockImplementation((_e,_q,_r,s,event)=>{signal=s;callback=event;return new Promise(r=>{resolve=r})})
  const {rerender,unmount}=render(view())
  click()
  act(()=>callback({type:'facts',data:report}))
  if(kind==='stop') fireEvent.click(screen.getByRole('button',{name:'停止解读'}))
  if(kind==='environment') rerender(view('env-2',undefined))
  if(kind==='run') rerender(view('env-1','run-2'))
  if(kind==='unmount') unmount()
  expect(signal.aborted).toBe(true)
  await act(async()=>{callback({type:'progress',data:{fragments:99,content_bytes:999}});resolve(answer)})
  expect(screen.queryByText('短期斜率 -9162596.9 bytes/s')).not.toBeInTheDocument()
  expect(screen.queryByText(/已收到 99/)).not.toBeInTheDocument()
  if(kind==='stop') {expect(screen.getByRole('button',{name:'发送问题'})).not.toBeDisabled();expect(screen.getByText('308.759 ms')).toBeInTheDocument()}
})
it('prevents duplicate requests synchronously before React commits pending state',()=>{
  const stream=vi.spyOn(dashboard,'streamDashboard').mockReturnValue(new Promise(()=>{}))
  render(view())
  const button=screen.getByRole('button',{name:'详细解读本次风险 ↗'})
  act(()=>{fireEvent.click(button);fireEvent.click(button)})
  expect(stream).toHaveBeenCalledOnce()
})
it('shows validation stage and exact AI inclusion counts after full result',async()=>{
  vi.spyOn(dashboard,'streamDashboard').mockImplementation(async(_e,_q,_r,_s,callback)=>{callback({type:'status',data:{stage:'validating'}});return {...answer,truncated:true,selected_count:8,omitted_count:8,check_count:16}})
  render(view());click()
  expect(await screen.findByText(/8 \/ 16 条检查/)).toHaveTextContent('省略 8 条检查')
})
it('discards independently loaded facts from the old environment',async()=>{
  let resolve!:(value:unknown)=>void
  vi.mocked(apiClient.get).mockReturnValueOnce(new Promise(r=>{resolve=r}) as never)
  const {rerender}=render(view('old'))
  rerender(<MemoryRouter><DashboardAIBar environmentId="new" facts={{...report,checks:[]}}/></MemoryRouter>)
  await act(async()=>resolve({data:report}))
  await waitFor(()=>expect(screen.queryByText('demo-dynamic / Model-8B')).not.toBeInTheDocument())
})
it('displays elapsed wall time while awaiting first provider fragment',async()=>{
  vi.useFakeTimers()
  vi.spyOn(dashboard,'streamDashboard').mockReturnValue(new Promise(()=>{}))
  render(view());click()
  expect(screen.getByRole('status')).toHaveTextContent('已用 0 秒')
  await act(async()=>vi.advanceTimersByTimeAsync(3000))
  expect(screen.getByRole('status')).toHaveTextContent('已用 3 秒')
  expect(screen.getByRole('status')).toHaveTextContent('等待模型开始输出')
  fireEvent.click(screen.getByRole('button',{name:'停止解读'}))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

it('reads persisted answer while AI disabled without generation; reopens read-only',async()=>{
 const saved={message_id:'message',conversation_id:'conversation',environment_id:'env-1',inspection_run_id:'run-1',generated_at:'2026-11-01T01:20:09+08:00',created_at:'2026-11-01T14:00:00+08:00'}
 vi.spyOn(dashboard,'getSavedDashboard').mockResolvedValue({status:'SAVED',answer:{...answer,prompt:{key:'inspection-explanation',revision:2}},saved})
 const stream=vi.spyOn(dashboard,'streamDashboard')
 const {unmount}=render(<MemoryRouter><DashboardAIBar environmentId="env-1" runId="run-1" facts={report} disabledReason="AI关闭"/></MemoryRouter>)
 expect(await screen.findByText(/已保存解读 · 生成于/)).toBeVisible()
 expect(screen.getByText(/prompt rev2/)).toBeVisible();expect(stream).not.toHaveBeenCalled()
 unmount();render(view());expect(await screen.findByText(/已保存解读 · 生成于/)).toBeVisible()
 expect(dashboard.getSavedDashboard).toHaveBeenCalledTimes(2);expect(stream).not.toHaveBeenCalled()
})
it('rejects a persisted answer from a different environment',async()=>{
 vi.spyOn(dashboard,'getSavedDashboard').mockResolvedValue({status:'SAVED',answer,saved:{message_id:'m',conversation_id:'c',environment_id:'other',inspection_run_id:'run-1',generated_at:'t',created_at:'t'}})
 render(view());expect(await screen.findByText('暂无已保存解读')).toBeVisible()
 expect(screen.queryByText(/已保存解读 · 生成于/)).not.toBeInTheDocument()
})
