import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { CodePluginsPage } from './CodePluginsPage'

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
  expect(within(drawer).queryByRole('button',{name:/编辑|发布|Dry Run|Shadow/})).not.toBeInTheDocument()
})
