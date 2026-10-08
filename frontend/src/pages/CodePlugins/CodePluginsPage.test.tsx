import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { CodePluginsPage } from './CodePluginsPage'
import catalogFixture from './ruleDetails.test.fixture.json'

afterEach(() => vi.restoreAllMocks())

it('searches the read-only rule catalog and opens rule details', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({data:{items:[
    {rule_code:'llm.performance_profile',name:'推理性能画像',rule_version:'1.0.0',plugin_id:'inference-performance',plugin_version:'1.0.0',operation_key:'evaluate',resource_types:['LLM_RUNTIME'],parameters:{source:'INFERENCE_SNAPSHOT'},status:'ACTIVE',deterministic:true,description:'评估真实推理性能快照。'},
  ]}} as never)
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><CodePluginsPage /></QueryClientProvider>)

  expect(await screen.findByRole('heading',{name:'规则库'})).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox',{name:'搜索规则'}), {target:{value:'performance'}})
  expect(screen.getByText('推理性能画像')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button',{name:/查看规则详情/}))
  const drawer = await screen.findByRole('dialog')
  expect(within(drawer).getByText('llm.performance_profile')).toBeInTheDocument()
  expect(within(drawer).getByText(/INFERENCE_SNAPSHOT/)).toBeInTheDocument()
  expect(within(drawer).getByText(/当前接口未提供具体指标清单/)).toBeInTheDocument()
  expect(within(drawer).getByText(/当前接口未提供具体判定条件和正常边界/)).toBeInTheDocument()
  expect(within(drawer).queryByRole('button',{name:/编辑|发布|Dry Run|Shadow/})).not.toBeInTheDocument()
})

// Captured from _serialize_rule/list_rules and the current backend policy file.
// Fixtures retain all metrics and explanations so the UI test exercises the API contract.
function renderCatalog(ruleCode: string) {
  const rule = catalogFixture.items.find(item => item.rule_code === ruleCode)!
  vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [rule] } } as never)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><CodePluginsPage /></QueryClientProvider>)
}

it('shows inference metrics, judgment boundaries and resolved engine/model policies in the drawer', async () => {
  renderCatalog('llm.performance_profile')
  fireEvent.click(await screen.findByRole('button', { name: /查看规则详情/ }))
  const drawer = within(await screen.findByRole('dialog'))
  expect(drawer.getByText(/外部采集系统计算并推送聚合快照/)).toBeInTheDocument()
  const metrics = drawer.getByRole('table', { name: '指标字段、输入路径及用途' })
  expect(within(metrics).getAllByRole('row')).toHaveLength(21)
  expect(within(metrics).getByText('首 Token 延迟（TTFT） P95')).toBeInTheDocument()
  expect(within(metrics).getByText('sample.ttft.p95_ms')).toBeInTheDocument()
  expect(within(metrics).getByText('sample.cache.kv_cache_hit_rate')).toBeInTheDocument()
  expect(drawer.getByRole('heading', { name: '14 天动态基线与正常边界' })).toBeInTheDocument()
  expect(drawer.getByText(/至少 100 点且覆盖 3 个不同日期才 READY/)).toBeInTheDocument()
  expect(drawer.getByText(/pending_confirmation=true/)).toBeInTheDocument()
  expect(drawer.getByText(/趋势不抬高 overall/)).toBeInTheDocument()

  const defaults = drawer.getByRole('table', { name: 'DEFAULT · 默认策略 · 完整有效固定阈值' })
  expect(within(defaults).getAllByRole('row')).toHaveLength(8)
  const defaultTtft = within(defaults).getByText('ttft.p95_ms').closest('tr')!
  expect(within(defaultTtft).getByText('≥ 800 且 < 1500')).toBeInTheDocument()
  expect(within(defaultTtft).getByText('≥ 1500')).toBeInTheDocument()
  expect(within(defaults.closest('details')!).getByText('相对变化 20%；Z = 3')).toBeInTheDocument()

  const engineSummary = drawer.getByText('ENGINE · sglang', { selector: 'summary' })
  fireEvent.click(engineSummary)
  expect(engineSummary.closest('details')).toHaveAttribute('open')
  expect(within(engineSummary.closest('details')!).getByText('本层未覆盖参数，沿用父级策略的全部值。')).toBeInTheDocument()

  const modelSummary = drawer.getByText('ENGINE_MODEL · vllm / Qwen/Qwen3-32B', { selector: 'summary' })
  fireEvent.click(modelSummary)
  expect(modelSummary.closest('details')).toHaveAttribute('open')
  const modelTable = drawer.getByRole('table', { name: 'ENGINE_MODEL · vllm / Qwen/Qwen3-32B · 完整有效固定阈值' })
  expect(within(modelTable).getByText('≥ 500 且 < 900')).toBeInTheDocument()
  expect(within(modelTable).getByText('≥ 1500 且 < 3000')).toBeInTheDocument()
  expect(within(modelSummary.closest('details')!).getByText('fixed.ttft.p95_ms.warning')).toBeInTheDocument()
  expect(drawer.queryByText(/当前接口未提供/)).not.toBeInTheDocument()
})

it.each([
  ['hardware.gpu_health', 7, 'metrics.gpu.values.ecc_dbe_delta.value', 'ECC / Xid 严重度与处置复验', /DRAM DOUBLE_BIT 增量 > 0/],
  ['hardware.host_health', 10, 'metrics.filesystem:<稳定标识>.values.available_bytes.value', '内存\/文件系统持续下降与保留空间', /10% 是保留空间时间估计基准/],
] as const)('shows %s collection and actual judgment details without inventing a fixed policy', async (ruleCode, count, path, judgmentTitle, boundary) => {
  renderCatalog(ruleCode)
  fireEvent.click(await screen.findByRole('button', { name: /查看规则详情/ }))
  const drawer = within(await screen.findByRole('dialog'))
  const metrics = drawer.getByRole('table', { name: '指标字段、输入路径及用途' })
  expect(within(metrics).getAllByRole('row')).toHaveLength(count + 1)
  expect(within(metrics).getByText(path)).toBeInTheDocument()
  expect(drawer.getByRole('heading', { name: judgmentTitle })).toBeInTheDocument()
  expect(drawer.getByText(boundary)).toBeInTheDocument()
  expect(drawer.getByText(/NOT_READY 诊断本身不会自动将 overall 改为 UNKNOWN/)).toBeInTheDocument()
  expect(drawer.queryByRole('heading', { name: '当前阈值与策略覆盖' })).not.toBeInTheDocument()
})
