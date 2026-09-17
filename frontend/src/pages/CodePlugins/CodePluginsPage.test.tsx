import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { apiClient } from '../../api/http'
import { CodePluginsPage } from './CodePluginsPage'

afterEach(() => vi.restoreAllMocks())

it('searches the read-only rule catalog and opens rule details', async () => {
  vi.spyOn(apiClient, 'get').mockResolvedValue({data:{items:[
    {rule_code:'topology.control_plane_anti_affinity',name:'控制面反亲和',rule_version:'1.0.0',plugin_id:'control-plane-anti-affinity',plugin_version:'1.0.0',operation_key:'evaluate',resource_types:['CONTROL_PLANE'],parameters:{min_replicas:2},status:'ACTIVE',deterministic:true,description:'按副本组检查。'},
    {rule_code:'llm.queue_backlog',name:'LLM 最近 N 点连续超限',rule_version:'1.0.0',plugin_id:'llm-queue-backlog',plugin_version:'1.0.0',operation_key:'evaluate',resource_types:['LLM_RUNTIME'],parameters:{consecutive_points:3},status:'ACTIVE',deterministic:true,description:'检查最近 N 点。'},
  ]}} as never)
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><CodePluginsPage /></QueryClientProvider>)

  expect(await screen.findByRole('heading',{name:'规则库'})).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox',{name:'搜索规则'}), {target:{value:'queue'}})
  expect(screen.queryByText('控制面反亲和')).not.toBeInTheDocument()
  expect(screen.getByText('LLM 最近 N 点连续超限')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button',{name:/查看规则详情/}))
  const drawer = await screen.findByRole('dialog')
  expect(within(drawer).getByText('llm.queue_backlog')).toBeInTheDocument()
  expect(within(drawer).getByText(/consecutive_points/)).toBeInTheDocument()
  expect(within(drawer).queryByRole('button',{name:/编辑|发布|Dry Run|Shadow/})).not.toBeInTheDocument()
})
