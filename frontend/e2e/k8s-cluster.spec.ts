import { expect, test } from '@playwright/test'

test('opens a Kubernetes resource and follows its existing cluster portrait', async ({ page }) => {
  const base = { description: '', icon: '', inspection_item_count: 0, health_score: null, risk_count: 0, p1_count: 0, p2_count: 0, last_inspection_at: null, data_state: 'NOT_CONNECTED' }
  const k8s = { ...base, code: 'K8S_CLUSTER', name: 'Kubernetes 集群', asset_count: 2 }
  const kvm = { ...base, code: 'KVM_CLUSTER', name: 'KVM 集群', asset_count: 1 }
  const metric = { key: 'host.cpu_busy_ratio', label: 'CPU忙碌比例', unit: 'ratio', current: .6, latest_observed: .6, observed_at: '2026-11-06T00:00:00Z', state: 'CURRENT', history: { n: 0, start: null, end: null, median: null, min: null, max: null, state: 'INSUFFICIENT_HISTORY' }, difference: null, missing_context: [], high_observation: null, low_observation: null }
  const group = { node_ids: ['node-1'], node_count: 1, metrics: [metric], window_aligned: true, note: '' }
  const cluster = { id: 'cluster-1', portrait_id: 'cluster-1', name: '生产集群', asset_type: 'CLUSTER', platform: 'kubernetes', roles: ['PRIMARY'], control_plane_deployment: 'UNKNOWN', total: group, groups: [], shared_nodes: [], relationships: [{ kind: 'node', id: 'node-1', name: 'worker-1' }] }
  const node = { id: 'node-1', scope_cluster_id: 'cluster-1', portrait_id: 'node-1', name: 'worker-1', asset_type: 'HOST', roles: ['WORKER'], stable_identity: 'node-1', shared_load: false, cpu_cores: 4, memory_semantics: 'LINUX_MEMAVAILABLE', metrics: [metric], context: {}, missing_context: [], freshness: 'FRESH', frozen_diagnostics: {}, diagnostic_note: '', relationships: [{ kind: 'cluster', id: 'cluster-1', name: '生产集群' }] }
  const cluster2 = { ...cluster, id: 'cluster-2', portrait_id: 'cluster-2', name: '备用集群', total: { ...group, node_ids: ['node-2'] }, relationships: [{ kind: 'node', id: 'node-2', name: 'worker-2' }] }
  const node2 = { ...node, id: 'node-2', scope_cluster_id: 'cluster-2', portrait_id: 'node-2', name: 'worker-2', stable_identity: 'node-2', relationships: [{ kind: 'cluster', id: 'cluster-2', name: '备用集群' }] }
  const service = (id:string, clusterId:string, value:number) => ({ id:`portrait-${id}`, asset_id:id, asset_name:id, scope_cluster_ids:[clusterId], name:'engine/encoded · vllm · org/model', context:{source:'same'}, missing_context:[], freshness:'CURRENT_WINDOW_STATISTIC', metrics:[{...metric,key:'ttft.p95_ms',label:'TTFT窗口p95',unit:'ms',current:value,latest_observed:value}] })
  const services = [service('service-a','cluster-1',10), service('service-b','cluster-2',90)]
  const profileRequests: string[] = []
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v1/environments') return route.fulfill({ json: { items: [{ id: 'env-1', slug: 'test', name: '测试环境', environment_type: 'TEST', timezone: 'Asia/Shanghai', assets_count: 2, mock_dataset_count: 0, inspection_run_count: 0, has_mock_data: false }] } })
    if (url.pathname === '/api/v1/resource-types') return route.fulfill({ json: { items: [k8s, kvm] } })
    if (url.pathname === '/api/v1/resource-types/K8S_CLUSTER/overview') return route.fulfill({ json: { resource_type: k8s, latest: null, check_results: [], health_trend: [] } })
    if (url.pathname === '/api/v1/hardware-health/performance-profiles') {
      profileRequests.push(`${url.searchParams.get('resource_type')}:${url.searchParams.get('view') ?? ''}`)
      const detail = url.searchParams.get('cluster_id') === 'cluster-1'
      return route.fulfill({ json: { resource_type: url.searchParams.get('resource_type'), generated_at: '2026-11-06T00:00:00Z', history_days: 14, clusters: detail ? [cluster] : [cluster, cluster2], nodes: detail ? [node] : [node, node2], llm: detail ? [services[0]] : services, truncated: false, deployment_edit: { writable: false, note: '' } } })
    }
    return route.abort()
  })

  await page.goto('/resources?environment=env-1')
  await expect(page.getByRole('link', { name: /Kubernetes 集群/ })).toBeVisible()
  await expect(page.getByText('KVM 集群')).toHaveCount(0)
  await page.getByRole('link', { name: /Kubernetes 集群/ }).click()
  await expect(page.getByText('暂无可用巡检插件，可查看资源画像。')).toBeVisible()
  await expect(page.getByText('资源类型：CLUSTER · 平台：kubernetes · 集群角色：PRIMARY')).toBeVisible()
  await expect(page.getByText('worker-1 · 类型：HOST · 角色：WORKER')).toBeVisible()
  await page.getByText('集群总计实际观测（原始成员口径）').click()
  await expect(page.getByText('60.0%').first()).toBeVisible()
  await page.getByRole('button', { name: 'LLM服务', exact: true }).click()
  await expect(page.getByText('资产：service-a · 标识：service-a · 所属集群：生产集群（当前资产关系）')).toBeVisible()
  await expect(page.getByRole('cell', { name: /^10 ms(?: |$)/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: /^90 ms(?: |$)/ })).toHaveCount(0)
  await page.getByRole('combobox', { name: '现有集群' }).selectOption('cluster-2')
  await expect(page.getByText('资产：service-b · 标识：service-b · 所属集群：备用集群（当前资产关系）')).toBeVisible()
  await expect(page.getByRole('cell', { name: /^90 ms(?: |$)/ })).toBeVisible()
  await expect(page.getByRole('cell', { name: /^10 ms(?: |$)/ })).toHaveCount(0)
  await page.getByRole('button', { name: '集群', exact: true }).click()
  await page.getByRole('combobox', { name: '现有集群' }).selectOption('cluster-1')
  expect(profileRequests).toContain('K8S_CLUSTER:')
  await page.getByRole('link', { name: '查看集群完整画像 →' }).click()
  await expect(page).toHaveURL(/\/performance-profiles\/cluster\/cluster-1\?environment=env-1&resource_type=K8S_CLUSTER&cluster_id=cluster-1/)
  await expect(page.getByRole('heading', { name: '身份与上下文' })).toBeVisible()
  await expect(page.getByText('kubernetes', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '节点 · worker-1 →' })).toBeVisible()
  expect(profileRequests).toContain('K8S_CLUSTER:portraits')
})
