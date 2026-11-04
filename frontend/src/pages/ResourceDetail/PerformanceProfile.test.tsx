import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/http'
import { ControlPlaneRisk, PerformanceProfile, ProfileMetrics } from './PerformanceProfile'

const metric = {key:'cpu',label:'CPU忙碌比例',unit:'ratio',current:null,latest_observed:.8,observed_at:'2026-10-20',state:'HISTORICAL_OR_UNAVAILABLE',history:{n:1,start:null,end:null,median:null,min:null,max:null,state:'INSUFFICIENT_HISTORY'},difference:null,missing_context:['historical_roles'],high_observation:null,low_observation:null}
const group = {node_ids:['node'],node_count:1,metrics:[metric],window_aligned:true,note:'IO百分比/请求p95不汇总'}
function show(data: object, resourceCode='HOST') {
  vi.spyOn(apiClient,'get').mockResolvedValue({data} as never)
  return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><PerformanceProfile environmentId="env" resourceCode={resourceCode} /></QueryClientProvider>)
}
afterEach(() => vi.restoreAllMocks())
it('retains stale values and missing historical context without deriving health', async () => {
  show({nodes:[{id:'node',name:'host',metrics:[metric],context:{source:'mac'},missing_context:['historical_roles'],freshness:'STALE',roles:['API_SERVER','ETCD'],shared_load:true,frozen_diagnostics:{},diagnostic_note:'VALID不表示健康正常'}],llm:[],clusters:[],deployment_edit:{writable:false}})
  expect(await screen.findByText('历史/过期观测')).toBeInTheDocument()
  expect(screen.getByText(/历史\/过期或语义未核实：80.0%/)).toBeInTheDocument()
  expect(screen.getByText('历史不足，范围未知')).toBeInTheDocument()
  expect(screen.getByText(/未记录比较条件：历史角色/)).toBeInTheDocument()
  expect(screen.getByText(/共享负载/)).toBeInTheDocument()
})
it('shows no cluster explicitly and permits changing layers', async () => {
  show({nodes:[],llm:[],clusters:[],deployment_edit:{writable:false}},'CONTROL_PLANE')
  expect(await screen.findByText('当前环境没有集群资产，部署方式未配置。')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'LLM服务'}))
  expect(screen.getByText('尚无LLM服务快照；其他层级仍可查看。')).toBeInTheDocument()
})
it('disables saving in read-only environments and shows exclusive group names', async () => {
  const patch=vi.spyOn(apiClient,'patch')
  show({nodes:[],llm:[],clusters:[{id:'cluster',name:'cluster',control_plane_deployment:'UNKNOWN',total:group,groups:[{role:'API_SERVER_ONLY',...group},{role:'ETCD_ONLY',...group}],shared_nodes:['node']}],deployment_edit:{writable:false}},'CONTROL_PLANE')
  expect(await screen.findByRole('button',{name:'保存'})).toBeDisabled()
  expect(screen.getByText('当前环境只读或权限未知，无法保存部署方式。')).toBeInTheDocument()
  expect(screen.getByText(/三组唯一主机/)).toBeInTheDocument()
  expect(screen.getByRole('button',{name:/纯APIServer/})).toBeInTheDocument()
  expect(patch).not.toHaveBeenCalled()
})
it('reports the actual server refusal instead of a successful save', async () => {
  vi.spyOn(apiClient,'patch').mockRejectedValue({response:{data:{error:{message:'数据库拒绝保存，部署方式未保存'}}}})
  show({nodes:[],llm:[],clusters:[{id:'cluster',name:'cluster',control_plane_deployment:'UNKNOWN',total:group,groups:[],shared_nodes:[]}],deployment_edit:{writable:true}},'CONTROL_PLANE')
  const select=await screen.findByRole('combobox',{name:'控制面部署方式'})
  fireEvent.change(select,{target:{value:'MIXED'}});fireEvent.click(screen.getByRole('button',{name:'保存'}))
  expect(await screen.findByText('数据库拒绝保存，部署方式未保存')).toBeInTheDocument()
  expect(screen.queryByText('部署方式已保存')).not.toBeInTheDocument()
})

it('labels real window statistics and point times separately', () => {
  const windowMetric={...metric,current:10,latest_observed:10,value_kind:'WINDOW_STATISTIC' as const,window_start:'2026-10-29T00:00:00Z',window_end:'2026-10-29T00:01:00Z',observed_at:'2026-10-29T00:01:00Z'}
  render(<ProfileMetrics metrics={[windowMetric]} />)
  expect(screen.getByText(/当前窗口统计 · WINDOW_STATISTIC · 统计窗口：2026-10-29T00:00:00Z 至 2026-10-29T00:01:00Z/)).toBeInTheDocument()
  expect(screen.queryByText(/指标采集时间/)).not.toBeInTheDocument()
})

it('keeps group selection stable on repeated clicks and normal members accessible', () => {
  const risk={level:'NORMAL' as const,complete:true,incomplete:false,triggers:[],items:[],missing:[],sample_time:'2026-11-02'}
  const nodes=[{id:'api',name:'api host',stable_identity:'api',risk,roles:['API_SERVER'],metrics:[],context:{},missing_context:[],freshness:'FRESH',shared_load:false,cpu_cores:4,memory_semantics:'LINUX_MEMAVAILABLE',frozen_diagnostics:{},diagnostic_note:''},{id:'mix',name:'mixed host',stable_identity:'mix',risk:{...risk,level:'UNKNOWN' as const,incomplete:true,complete:false,missing:['missing confirmation']},roles:['API_SERVER','ETCD'],metrics:[],context:{},missing_context:[],freshness:'FRESH',shared_load:true,cpu_cores:4,memory_semantics:'LINUX_MEMAVAILABLE',frozen_diagnostics:{},diagnostic_note:''}]
  const cluster={id:'c',name:'c',control_plane_deployment:'UNKNOWN',total:group,groups:[{...group,role:'API_SERVER_ONLY',node_ids:['api']},{...group,role:'ETCD_ONLY',node_ids:[],node_count:0},{...group,role:'MIXED',node_ids:['mix']}],shared_nodes:['mix']}
  render(<ControlPlaneRisk cluster={cluster} nodes={nodes}/> )
  expect(screen.queryByRole('cell',{name:/api host/})).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox',{name:'查看正常成员'}))
  expect(screen.getByRole('cell',{name:/api host/})).toBeInTheDocument()
  const mixed=screen.getByRole('button',{name:/混合部署/})
  fireEvent.click(mixed);fireEvent.click(mixed)
  expect(mixed).toHaveAttribute('aria-pressed','true')
  expect(screen.getByRole('cell',{name:/mixed host/})).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:/纯APIServer/}))
  fireEvent.click(screen.getByRole('checkbox',{name:'查看正常成员'}))
  expect(screen.getByRole('cell',{name:/api host/})).toBeInTheDocument()
  expect(screen.queryByRole('cell',{name:/mixed host/})).not.toBeInTheDocument()
})
