import { expect, test, type Page } from '@playwright/test'

test.setTimeout(120_000)

// CI setup/build may outlive the 300-second policy; refresh raw input, not results.
// Minute-aligned windows remain contiguous with seed/replayed observations.
async function refreshInferenceInput(page: Page, environmentId: string) {
  const latest = Math.floor(Date.now() / 60_000) * 60_000
  const response = await page.request.post('/api/v1/inference-performance/snapshots/batch', {data: {
    source: 'e2e-browser-fixture', environment_id: environmentId,
    engine: {engine_id: `e2e-browser-${environmentId}`, engine_type: 'vllm', model_name: 'Qwen3.5-4B'},
    evaluate_latest: true,
    samples: [latest - 60_000, latest].map(end => ({
      sample_id: `e2e-browser-${environmentId}-${new Date(end).toISOString()}`,
      window_start: new Date(end - 60_000).toISOString(), window_end: new Date(end).toISOString(),
      ttft: {avg_ms: 100, p90_ms: 200, p95_ms: 1200, p99_ms: 1300, e2e_ratio: 0.2},
      tpot: {avg_ms: 10, p90_ms: 15, p95_ms: 20, p99_ms: 30},
      e2e: {avg_ms: 1000, p90_ms: 1500, p95_ms: 2000, p99_ms: 2500},
      traffic: {qps: 5, qpm: 300}, throughput: {generation_tps: 1000, prompt_tps: 2000},
      cache: {kv_cache_hit_rate: 0.6}, requests: {running: 3, waiting: 40},
    })),
  }})
  expect([200, 201]).toContain(response.status())
}

async function inspect(page: Page, code: 'LLM_RUNTIME') {
  const authRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/api/v1/auth/')) authRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'总览',level:1,exact:true})).toBeVisible()
  expect(authRequests).toEqual([])
  const response = await page.request.get('/api/v1/environments')
  const env = (await response.json()).items.find((row: {slug:string}) => row.slug === 'e2e')
  expect(env).toBeTruthy()
  await refreshInferenceInput(page, env.id)
  await page.goto(`/?environment=${env.id}`)
  await page.getByRole('button',{name:'立即巡检',exact:true}).click()
  await page.getByRole('button',{name:/LLM/}).click()
  const created = page.waitForResponse(r => r.url().endsWith('/api/v1/inspection-runs/trigger') && r.request().method() === 'POST')
  await page.getByRole('button',{name:'开始巡检'}).click()
  const responseCreated = await created
  expect(responseCreated.ok()).toBeTruthy()
  const run = await responseCreated.json()
  await expect(page.getByText('巡检已完成',{exact:true})).toBeVisible({timeout:90_000})
  const slug = 'llm-runtime'
  await page.goto(`/resources/${slug}/runs/${run.id}?environment=${env.id}`)
  const checks = page.getByRole('region',{name:'本轮检查'})
  await expect(checks).toBeVisible()
  return {run,env,code,checks}
}

test('control plane: resource type stays visible without a connected formal plugin',async ({page}) => {
  const authRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/api/v1/auth/')) authRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'总览',level:1,exact:true})).toBeVisible()
  expect(authRequests).toEqual([])
  const env = (await (await page.request.get('/api/v1/environments')).json()).items.find((row:{slug:string}) => row.slug === 'e2e')
  expect(env).toBeTruthy()
  const types = await (await page.request.get(`/api/v1/resource-types?environment_id=${env.id}`)).json()
  expect(types.items.find((row:{code:string}) => row.code === 'CONTROL_PLANE')).toMatchObject({
    code:'CONTROL_PLANE',release_state:'PLANNED',data_state:'NOT_CONNECTED',inspection_item_count:0,health_score:null,
  })
  await page.goto(`/?environment=${env.id}`)
  await page.getByRole('button',{name:'立即巡检',exact:true}).click()
  const control = page.getByRole('dialog').getByRole('button',{name:/控制面/})
  await expect(control).toBeVisible()
  await expect(control).toContainText('未接入正式插件')
  await expect(control).toContainText('0 个巡检项')
  // Node-role visibility needs control-plane assets, outside this inference fixture.
  // Do not resurrect the retired anti-affinity execution or fabricate those roles.
})

test('LLM runtime: aggregate check retains TTFT and queue evidence with actual coverage',async ({page}) => {
  const {checks,run,env,code} = await inspect(page,'LLM_RUNTIME')
  await checks.getByText('规则标识',{exact:true}).click()
  await expect(checks.getByRole('row').filter({hasText:'llm.performance_profile'}).filter({hasText:'发现异常'})).toHaveCount(1)
  await checks.getByText('展开证据',{exact:true}).click()
  await expect(checks.getByText('原始状态：FAIL',{exact:true})).toBeVisible()
  await expect(checks.locator('pre')).toContainText('TTFT_P95_FIXED_HIGH')
  await expect(checks.locator('pre')).toContainText('WAITING_REQUESTS_FIXED_HIGH')
  const detail = await (await page.request.get(`/api/v1/resource-types/${code}/inspection-history/${run.id}?environment_id=${env.id}`)).json()
  expect(detail.coverage.rate).toBe(1)
  expect(detail.run.id).toBe(run.id)
  expect(detail.finding_count).toBe(1)
  expect(detail.risk_count).toBe(1)
  expect(detail.check_results).toEqual([expect.objectContaining({inspection_item_code:'llm.performance_profile',status:'FAIL',source:expect.objectContaining({plugin_id:'inference-performance',plugin_version:'1.0.0'})})])
  const evaluation = detail.check_results[0].evidence.evaluation
  expect(evaluation.reasons).toEqual(expect.arrayContaining([
    expect.objectContaining({code:'TTFT_P95_FIXED_HIGH',metric:'ttft.p95_ms'}),
    expect.objectContaining({code:'WAITING_REQUESTS_FIXED_HIGH',metric:'requests.waiting'}),
  ]))
  expect(detail.summary.conclusive_assets).toBe(1)
  await page.reload()
  const persisted = await (await page.request.get(`/api/v1/resource-types/${code}/inspection-history/${run.id}?environment_id=${env.id}`)).json()
  expect(persisted.run.id).toBe(run.id)
  expect(persisted.check_results).toEqual(detail.check_results)
  expect(persisted.major_risks).toEqual(detail.major_risks)
})

test('AI explanation references persisted TTFT and queue evidence without changing checks',async ({page}) => {
  const {run,env,code} = await inspect(page,'LLM_RUNTIME')
  const url = `/api/v1/resource-types/${code}/inspection-history/${run.id}?environment_id=${env.id}`
  const before = await (await page.request.get(url)).json()
  await page.getByRole('button',{name:'开始 AI 分析'}).click()
  await expect(page.locator('.decision-copy')).toContainText('llm.performance_profile',{timeout:40_000})
  const evidence = before.check_results[0].evidence.evaluation
  expect(evidence.reasons).toEqual(expect.arrayContaining([
    expect.objectContaining({code:'TTFT_P95_FIXED_HIGH'}),
    expect.objectContaining({code:'WAITING_REQUESTS_FIXED_HIGH'}),
  ]))
  const after = await (await page.request.get(url)).json()
  expect(after.check_results).toEqual(before.check_results)
  expect(after.risk_count).toBe(before.risk_count)
  expect(after.major_risks).toEqual(before.major_risks)
})
