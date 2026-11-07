import { render, screen, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import dataJson from '../../../../docs/implementation/2026-10-30-performance-portraits100/author/CONTROLLED-DATA.json'
import type { PerformanceProfileData, ProfileMetric } from '../../api/performanceProfile'
import { apiClient } from '../../api/http'
import { useUiStore } from '../../stores/uiStore'
import { PerformancePortraitsPage, PortraitBrowser } from './PerformancePortraitsPage'
import { MetricPortrait } from './MetricPortrait'
import { portraits, portraitUrl, difference } from './portraitModel'
const data=dataJson as unknown as PerformanceProfileData
function Location(){return <output data-testid="location">{useLocation().pathname+useLocation().search}</output>}
function view(path='/performance-profiles?environment=env'){
 useUiStore.setState({environmentId:'env'})
 vi.spyOn(apiClient,'get').mockResolvedValue({data})
 return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[path]}><Routes><Route path="/performance-profiles" element={<PerformancePortraitsPage/>}/><Route path="/performance-profiles/:kind/:id" element={<PerformancePortraitsPage/>}/></Routes><Location/></MemoryRouter></QueryClientProvider>)
}
afterEach(()=>vi.restoreAllMocks())
it('keeps every registered missing and observed resource; URL filters and real links retain return context',async()=>{
 view('/performance-profiles?environment=env&type=node&stage=all&q=node-a')
 const link=await screen.findByRole('link',{name:'查看节点 node-a'})
 expect(link).toHaveAttribute('href','/performance-profiles/node/node-a?environment=env&type=node&stage=all&q=node-a')
 expect(link.tagName).toBe('A');link.focus();expect(link).toHaveFocus()
 fireEvent.click(link)
 expect(await screen.findByRole('heading',{name:'身份与上下文'})).toBeInTheDocument()
 expect(screen.getByRole('link',{name:'← 返回资源列表'})).toHaveAttribute('href','/performance-profiles?environment=env&type=node&stage=all&q=node-a')
 expect(apiClient.get).toHaveBeenLastCalledWith('/hardware-health/performance-profiles',{params:{environment_id:'env',resource_type:'CLUSTER',view:'portraits',kind:'node',id:'node-a'}})
 fireEvent.click(screen.getByRole('link',{name:'← 返回资源列表'}))
 await screen.findByRole('searchbox',{name:'搜索资源'})
 fireEvent.change(screen.getByRole('searchbox',{name:'搜索资源'}),{target:{value:''}})
 fireEvent.change(screen.getByRole('combobox',{name:'数据阶段'}),{target:{value:'missing'}})
 expect(await screen.findByRole('link',{name:'查看节点 missing-node'})).toBeInTheDocument()
 expect(screen.queryByRole('link',{name:'查看节点 node-a'})).not.toBeInTheDocument()
 expect(screen.getByTestId('location')).toHaveTextContent('stage=missing')
})
it('LLM identities with slashes and equal legacy ids resolve to correct frozen source',async()=>{
 const llms=portraits(data).filter(r=>r.kind==='llm'&&r.id.includes('source-B'))
 expect(data.llm[0].id).toBe(data.llm[1].id)
 const target=llms[0];view(portraitUrl(target,'environment=env&type=llm'))
 await screen.findByRole('heading',{name:'身份与上下文'})
 expect(screen.getByText('source-B')).toBeInTheDocument()
 const ttft=screen.getByRole('article',{name:'TTFT窗口p95'})
 expect(within(ttft).getAllByText('200 ms').length).toBeGreaterThan(0)
 expect(screen.getByRole('link',{name:'← 返回资源列表'})).toHaveAttribute('href','/performance-profiles?environment=env&type=llm')
})
it('detail shows weighted unique totals, readonly deployment and related node links',()=>{
 render(<MemoryRouter initialEntries={['/performance-profiles/cluster/cluster?environment=env']}><Routes><Route path="/performance-profiles/:kind/:id" element={<PortraitBrowser data={data} environmentId="env"/>}/></Routes></MemoryRouter>)
 expect(screen.getByRole('button',{name:'保存部署方式'})).toBeDisabled()
 expect(screen.getByText(/总计 2 个唯一节点/)).toBeInTheDocument()
 expect(screen.getByRole('link',{name:'节点 · node-a →'})).toHaveAttribute('href','/performance-profiles/node/node-a?environment=env')
})
it('keeps a Kubernetes cluster scope when loading its existing portrait',async()=>{
 view('/performance-profiles/cluster/cluster?environment=env&resource_type=K8S_CLUSTER&cluster_id=cluster')
 await screen.findByRole('heading',{name:'身份与上下文'})
 expect(apiClient.get).toHaveBeenLastCalledWith('/hardware-health/performance-profiles',{params:{environment_id:'env',resource_type:'K8S_CLUSTER',view:'portraits',cluster_id:'cluster',kind:'cluster',id:'cluster'}})
 expect(screen.getByRole('link',{name:'节点 · node-a →'})).toHaveAttribute('href','/performance-profiles/node/node-a?environment=env&resource_type=K8S_CLUSTER&cluster_id=cluster')
})
it('chart/card use exact values, point times, units; missing does not make a line; keyboard and touch select real history',()=>{
 const metric=data.nodes[0].metrics[0]
 render(<MetricPortrait metric={metric}/>)
 expect(screen.getAllByText('40%').length).toBeGreaterThan(0)
 expect(screen.getAllByText(/采集 2026-10-29T04:00:00\+00:00/).length).toBeGreaterThan(0)
 const chart=screen.getByRole('group',{name:'CPU忙碌比例真实离散观测'})
 expect(chart.querySelector('path,polyline')).toBeNull()
 expect(metric.series!.some(p=>p.value==null)).toBe(true)
 const points=within(chart).getAllByRole('button');fireEvent.focus(points[0])
 expect(screen.getByRole('status')).toHaveTextContent('历史观测')
 expect(screen.getByRole('status')).toHaveTextContent('37%')
 fireEvent.keyDown(points[points.length-1],{key:'Enter'})
 expect(screen.getByRole('status')).toHaveTextContent('当前有效观测 · 40%')
 fireEvent.click(points[0]);expect(screen.getByRole('status')).toHaveTextContent('37%')
 expect(screen.getByText(/本窗口存在缺测点/)).toBeInTheDocument()
})
it('stale and no-history stay honest, zero baseline never yields infinity and ratio deltas are percentage points',()=>{
 const metric={...data.nodes[0].metrics[0],current:null,latest_observed:.4,history:{...data.nodes[0].metrics[0].history,n:0,median:0,min:null,max:null},difference:null} as ProfileMetric
 render(<MetricPortrait metric={metric}/>)
 expect(screen.getByText(/最近历史观测/)).toBeInTheDocument()
 expect(screen.getByText(/不作为当前值/)).toBeInTheDocument()
 expect(difference({...metric,current:.4,difference:.1,history:{...metric.history,median:.3}})).toContain('10 个百分点')
 expect(difference({...metric,current:.4,difference:.4})).toContain('零基线')
 expect(document.body.textContent).not.toContain('Infinity')
})
