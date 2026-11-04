import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { render,screen,fireEvent,waitFor,act,within } from '@testing-library/react'
import { afterEach,it,expect,vi } from 'vitest'
import { apiClient } from '../../api/http'
import * as streamApi from '../../api/dashboardAI'
import { RunCounts,RunFactsWorkspace } from './RunOverview'
import { DashboardPage } from '../../pages/Dashboard/DashboardPage'
import { detail } from './runOverview.fixture'

function view(node:React.ReactNode){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>)}
afterEach(()=>vi.restoreAllMocks())
it.each(['快照对象或环境身份不符','快照插件版本不受当前规则支持'])('keeps known UNKNOWN reason visible: %s',summary=>{
 const data=structuredClone(detail);data.fact_report!.checks[0].summary=summary
 view(<RunFactsWorkspace detail={data} environmentId="env"/>);
 expect(screen.getAllByText(summary).some(node=>node.closest('details')==null)).toBe(true)
 expect(screen.queryByText('当时未记录具体原因，无法判断本项健康。')).not.toBeInTheDocument()
})
it('uses same-run counts without mixing asset and check denominators',()=>{
 view(<RunCounts detail={detail}/>);
 expect(screen.getByText('1 / 2')).toBeVisible();expect(screen.getByText('执行对象覆盖')).toBeVisible();expect(screen.getByText('仍无法判断')).toBeVisible()
})
it('binds opened interpretation to this run; close cancels, unavailable capability stays explicit',async()=>{
 vi.spyOn(apiClient,'get').mockResolvedValue({data:{llm_provider:'disabled'}})
 const stream=vi.spyOn(streamApi,'streamDashboard')
 view(<RunFactsWorkspace detail={detail} environmentId="env"/>);fireEvent.click(screen.getByRole('button',{name:'智能解读本轮'}))
 expect(await screen.findByText('当前AI配置已关闭；本页不会开启配置。')).toBeVisible()
 expect(screen.getByRole('textbox')).toBeDisabled();expect(screen.getByText(/不支持任意自由问答/)).toBeVisible()
 expect(screen.getByRole('button',{name:'详细解读本次风险 ↗'})).toBeDisabled();expect(stream).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'关闭解读并返回事实'}));expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
})
it('cancels duplicate pending interpretation on close and never displays late result',async()=>{
 vi.spyOn(apiClient,'get').mockResolvedValue({data:{llm_provider:'ollama'}})
 let signal!:AbortSignal,resolve!:(x:streamApi.DashboardAnswer)=>void
 const stream=vi.spyOn(streamApi,'streamDashboard').mockImplementation((_e,_q,_r,s)=>{signal=s;return new Promise(r=>{resolve=r})})
 view(<RunFactsWorkspace detail={detail} environmentId="env"/>);fireEvent.click(screen.getByRole('button',{name:'智能解读本轮'}))
 await waitFor(()=>expect(screen.getByRole('button',{name:'详细解读本次风险 ↗'})).not.toBeDisabled());const btn=screen.getByRole('button',{name:'详细解读本次风险 ↗'});act(()=>{fireEvent.click(btn);fireEvent.click(btn)})
 expect(stream).toHaveBeenCalledOnce();expect(stream.mock.calls[0][2]).toBe('r1')
 fireEvent.click(screen.getByRole('button',{name:'关闭解读并返回事实'}));expect(signal.aborted).toBe(true)
 await act(async()=>resolve({inspection_run_id:'old',answer:'old answer'} as streamApi.DashboardAnswer));expect(screen.queryByText('old answer')).not.toBeInTheDocument()
})
it('dashboard shows a real selected Run and frozen cutoff rather than live average health',async()=>{
 vi.spyOn(apiClient,'get').mockImplementation(async(url)=>({data:String(url)==='/inspection-runs'?{items:[detail.run]}:String(url).includes('/result')?detail:{items:[]}}))
 view(<DashboardPage environmentId="env" onOpenInspection={()=>{}}/>);
 expect(await screen.findByText(/完成\/事实截止 cutoff/)).toBeVisible()
 expect(screen.getByRole('link',{name:'查看本轮报告 →'})).toHaveAttribute('href','/inspection-runs/r1?environment=env')
 expect(screen.queryByText('资源类型平均健康评分')).not.toBeInTheDocument()
})
