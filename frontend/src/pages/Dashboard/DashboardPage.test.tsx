import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach,it,expect,vi } from 'vitest'
import { apiClient } from '../../api/http'
import { DashboardPage } from './DashboardPage'
import { detail } from '../../features/run-overview/runOverview.fixture'
function view(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><DashboardPage environmentId="env" onOpenInspection={()=>{}}/></MemoryRouter></QueryClientProvider>)}
afterEach(()=>vi.restoreAllMocks())
it('loads actual environment Run records before drawing conclusions',()=>{vi.spyOn(apiClient,'get').mockReturnValue(new Promise(()=>{}) as never);view();expect(screen.getByText('正在读取当前环境的巡检记录…')).toBeVisible()})
it('uses selected frozen summary and cutoff; does not mix current resource health averages',async()=>{vi.spyOn(apiClient,'get').mockImplementation(async(url)=>({data:String(url)==='/inspection-runs'?{items:[detail.run]}:String(url).includes('/result')?detail:{items:[{health_score:100,risk_count:999}]}}));view();expect(await screen.findByText('1 / 2')).toBeVisible();expect(screen.getByText('已得出判定')).toBeVisible();expect(screen.queryByText('整体健康度')).not.toBeInTheDocument()})
it('has an honest no-report state and keeps the normal inspection CTA',async()=>{vi.spyOn(apiClient,'get').mockResolvedValue({data:{items:[]}});view();expect(await screen.findByText('当前环境尚无巡检报告')).toBeVisible();expect(screen.getByRole('button',{name:'立即巡检'})).toBeVisible();expect(screen.queryByRole('button',{name:'智能解读本轮'})).not.toBeInTheDocument()})
it('shows actual list failure with trace and retry action',async()=>{vi.spyOn(apiClient,'get').mockRejectedValue({response:{data:{error:{message:'记录服务暂不可用',trace_id:'tr_dashboard'}}}});view();expect(await screen.findByText('记录服务暂不可用')).toBeVisible();expect(screen.getByText('追踪 ID：tr_dashboard')).toBeVisible();expect(screen.getByRole('button',{name:'重试'})).toBeVisible()})
