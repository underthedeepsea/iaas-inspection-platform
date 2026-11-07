import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
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

it('shows only the selected cluster membership even when projected nodes share an asset id', async () => {
  const nodes = [{id:'shared',scope_cluster_id:'a',name:'worker-a',asset_type:'HOST',roles:['WORKER'],metrics:[],shared_load:false}, {id:'shared',scope_cluster_id:'b',name:'api-b',asset_type:'HOST',roles:['API_SERVER'],metrics:[],shared_load:false}]
  const clusters = [{id:'a',name:'Cluster A',asset_type:'CLUSTER',platform:'kubernetes',roles:['UNKNOWN'],control_plane_deployment:'UNKNOWN',total:{...group,node_ids:['shared']},groups:[],shared_nodes:[]}, {id:'b',name:'Cluster B',asset_type:'CLUSTER',platform:'kubernetes',roles:['UNKNOWN'],control_plane_deployment:'UNKNOWN',total:{...group,node_ids:['shared']},groups:[],shared_nodes:[]}]
  vi.spyOn(apiClient,'get').mockResolvedValue({data:{nodes,clusters,llm:[],deployment_edit:{writable:false}}} as never)
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><PerformanceProfile environmentId="env" resourceCode="K8S_CLUSTER" /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('worker-a · 类型：HOST · 角色：WORKER')).toBeInTheDocument()
  expect(screen.queryByText('api-b · 类型：HOST · 角色：API_SERVER')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox',{name:'现有集群'}),{target:{value:'b'}})
  expect(screen.getByText('api-b · 类型：HOST · 角色：API_SERVER')).toBeInTheDocument()
  expect(screen.queryByText('worker-a · 类型：HOST · 角色：WORKER')).not.toBeInTheDocument()
})

it('shows only the selected cluster service and its real asset identity for equal engine names', async () => {
  const clusters = [{id:'cluster-a',name:'Cluster A',control_plane_deployment:'UNKNOWN',total:{...group,node_ids:[]},groups:[],shared_nodes:[]}, {id:'cluster-b',name:'Cluster B',control_plane_deployment:'UNKNOWN',total:{...group,node_ids:[]},groups:[],shared_nodes:[]}, {id:'cluster-c',name:'Cluster C',control_plane_deployment:'UNKNOWN',total:{...group,node_ids:[]},groups:[],shared_nodes:[]}]
  const service = (id:string, cluster:string, value:number) => ({id:`portrait-${id}`,asset_id:id,asset_name:id,scope_cluster_ids:[cluster],name:'engine/encoded · vllm · org/model',context:{source:'same'},missing_context:[],freshness:'CURRENT_WINDOW_STATISTIC',metrics:[{...metric,key:'ttft.p95_ms',label:'TTFT窗口p95',unit:'ms',current:value,latest_observed:value}]})
  vi.spyOn(apiClient,'get').mockResolvedValue({data:{nodes:[],clusters,llm:[service('service-a','cluster-a',10),service('service-b','cluster-b',90)],deployment_edit:{writable:false}}} as never)
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><PerformanceProfile environmentId="env" resourceCode="K8S_CLUSTER" /></MemoryRouter></QueryClientProvider>)
  await screen.findByRole('combobox',{name:'现有集群'})
  fireEvent.click(screen.getByRole('button',{name:'LLM服务'}))
  let card=screen.getByRole('article')
  expect(within(card).getByText('资产：service-a · 标识：service-a · 所属集群：Cluster A（当前资产关系）')).toBeInTheDocument()
  expect(within(card).getByText('10 ms')).toBeInTheDocument()
  expect(screen.queryByText('90 ms')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox',{name:'现有集群'}),{target:{value:'cluster-b'}})
  card=screen.getByRole('article')
  expect(within(card).getByText('资产：service-b · 标识：service-b · 所属集群：Cluster B（当前资产关系）')).toBeInTheDocument()
  expect(within(card).getByText('90 ms')).toBeInTheDocument()
  expect(screen.queryByText('10 ms')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox',{name:'现有集群'}),{target:{value:'cluster-c'}})
  expect(screen.queryByRole('article')).not.toBeInTheDocument()
  expect(screen.getByText('当前集群没有可确认归属的 LLM 服务快照。')).toBeInTheDocument()
})

it('keeps the unscoped LLM runtime layer available without cluster membership metadata', async () => {
  const service={id:'llm',name:'engine',context:{source:'same'},missing_context:[],freshness:'FRESH',metrics:[]}
  vi.spyOn(apiClient,'get').mockResolvedValue({data:{nodes:[],clusters:[],llm:[service],deployment_edit:{writable:false}}} as never)
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><PerformanceProfile environmentId="env" resourceCode="LLM_RUNTIME" /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('article')).toHaveTextContent('engine')
})

const editableGroup = { node_ids: [], node_count: 0, metrics: [], window_aligned: false, note: '' }
const editableClusters = [
  { id: 'cluster-a', name: 'Cluster A', control_plane_deployment: 'UNKNOWN', total: editableGroup, groups: [], shared_nodes: [] },
  { id: 'cluster-b', name: 'Cluster B', control_plane_deployment: 'DEDICATED', total: editableGroup, groups: [], shared_nodes: [] },
]
const editableData = { clusters: editableClusters, nodes: [], llm: [], deployment_edit: { writable: true } }

function editableProfile(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(<QueryClientProvider client={client}><MemoryRouter><PerformanceProfile environmentId="env" resourceCode="K8S_CLUSTER" /></MemoryRouter></QueryClientProvider>)
}

it('does not carry an unsaved deployment through the LLM cluster selector', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: editableData } as never)
  const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} } as never)
  editableProfile()
  fireEvent.change(await screen.findByRole('combobox', { name: '控制面部署方式' }), { target: { value: 'MIXED' } })
  fireEvent.click(screen.getByRole('button', { name: 'LLM服务' }))
  fireEvent.change(screen.getByRole('combobox', { name: '现有集群' }), { target: { value: 'cluster-b' } })
  fireEvent.click(screen.getByRole('button', { name: '集群' }))
  expect(screen.getByRole('combobox', { name: '现有集群' })).toHaveValue('cluster-b')
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('DEDICATED')
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  expect(patch).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('combobox', { name: '控制面部署方式' }), { target: { value: 'MIXED' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(patch).toHaveBeenCalledWith('/hardware-health/clusters/cluster-b/deployment', { control_plane_deployment: 'MIXED' }, { params: { environment_id: 'env' } }))
})

it('retains same-cluster edits across layers but clears them on the cluster selector', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: editableData } as never)
  const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} } as never)
  editableProfile()
  fireEvent.change(await screen.findByRole('combobox', { name: '控制面部署方式' }), { target: { value: 'MIXED' } })
  fireEvent.click(screen.getByRole('button', { name: 'LLM服务' }))
  fireEvent.click(screen.getByRole('button', { name: '集群' }))
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('MIXED')
  expect(screen.getByRole('button', { name: '保存' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(patch).toHaveBeenCalledWith('/hardware-health/clusters/cluster-a/deployment', { control_plane_deployment: 'MIXED' }, { params: { environment_id: 'env' } }))
  expect(await screen.findByText('部署方式已保存')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: '现有集群' }), { target: { value: 'cluster-b' } })
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('DEDICATED')
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  expect(screen.queryByText('部署方式已保存')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: '现有集群' }), { target: { value: 'cluster-a' } })
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('UNKNOWN')
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
})

it.each(['success', 'failure'] as const)('does not show a pending cluster A save %s on cluster B', async (outcome) => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: editableData } as never)
  let finish!: (value: unknown) => void
  let fail!: (reason: unknown) => void
  const pending = new Promise((resolve, reject) => { finish = resolve; fail = reject })
  const patch = vi.spyOn(apiClient, 'patch').mockReturnValueOnce(pending as never)
  editableProfile()
  fireEvent.change(await screen.findByRole('combobox', { name: '控制面部署方式' }), { target: { value: 'MIXED' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  expect(patch).toHaveBeenCalledWith('/hardware-health/clusters/cluster-a/deployment', { control_plane_deployment: 'MIXED' }, { params: { environment_id: 'env' } })
  fireEvent.click(screen.getByRole('button', { name: 'LLM服务' }))
  fireEvent.change(screen.getByRole('combobox', { name: '现有集群' }), { target: { value: 'cluster-b' } })
  fireEvent.click(screen.getByRole('button', { name: '集群' }))
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('DEDICATED')
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  await act(async () => { if (outcome === 'success') finish({ data: {} }); else fail({ response: { data: { error: { message: 'A 保存失败' } } } }) })
  await waitFor(() => expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toBeEnabled())
  expect(screen.queryByText('部署方式已保存')).not.toBeInTheDocument()
  expect(screen.queryByText('A 保存失败')).not.toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('DEDICATED')
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
})

it('does not apply a draft to the fallback cluster after a data refresh removes the original', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: editableData } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  editableProfile(client)
  fireEvent.change(await screen.findByRole('combobox', { name: '控制面部署方式' }), { target: { value: 'MIXED' } })
  act(() => client.setQueryData(['performance-profile', 'env', 'K8S_CLUSTER'], { ...editableData, clusters: [editableClusters[1]] }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: '现有集群' })).toHaveValue('cluster-b'))
  expect(screen.getByRole('combobox', { name: '控制面部署方式' })).toHaveValue('DEDICATED')
  expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
})
