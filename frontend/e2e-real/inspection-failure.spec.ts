import { expect, test, type Page } from '@playwright/test'

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


test('AI transport unavailable leaves persisted inspection results visible', async ({page}) => {
  const authRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/api/v1/auth/')) authRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'总览',level:1,exact:true})).toBeVisible()
  expect(authRequests).toEqual([])
  const env = (await (await page.request.get('/api/v1/environments')).json()).items.find((r:{slug:string}) => r.slug === 'e2e')
  expect(env).toBeTruthy()
  await refreshInferenceInput(page, env.id)
  const created = await page.request.post('/api/v1/inspection-runs/trigger',{data:{environment_id:env.id,scope:{resource_types:['LLM_RUNTIME']},trigger_options:{ai_mode:'DISABLED'}}})
  expect(created.ok()).toBeTruthy()
  const run = await created.json()
  const url = `/api/v1/resource-types/LLM_RUNTIME/inspection-history/${run.id}?environment_id=${env.id}`
  await expect.poll(async()=> (await page.request.get(url)).status(),{timeout:90_000}).toBe(200)
  const before = await (await page.request.get(url)).json()
  expect(before.run.id).toBe(run.id)
  expect(before.check_results).toEqual([expect.objectContaining({inspection_item_code:'llm.performance_profile',status:'FAIL'})])
  expect(before.risk_count).toBe(1)
  expect(before.major_risks).toHaveLength(1)
  await page.goto(`/resources/llm-runtime/runs/${run.id}?environment=${env.id}`)
  await page.route('**/api/v1/resource-types/LLM_RUNTIME/analysis',r=>r.abort('failed'))
  await page.getByRole('button',{name:'开始 AI 分析'}).click()
  await expect(page.getByRole('alert')).toHaveText('AI 分析暂不可用')
  const checks = page.getByRole('region',{name:'本轮检查'})
  await expect(checks.getByText('发现异常',{exact:true})).toBeVisible()
  await checks.getByText('展开证据',{exact:true}).click()
  await expect(checks.getByText('原始状态：FAIL',{exact:true})).toBeVisible()
  const after = await (await page.request.get(url)).json()
  expect(after.check_results).toEqual(before.check_results)
  expect(after.risk_count).toBe(before.risk_count)
  expect(after.major_risks).toEqual(before.major_risks)
})
