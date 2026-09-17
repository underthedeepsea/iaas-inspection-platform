import { expect, test, type Page } from '@playwright/test'

test.setTimeout(120_000)

async function inspect(page: Page, code: 'CONTROL_PLANE' | 'LLM_RUNTIME') {
  const authRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/api/v1/auth/')) authRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'租户区智能巡检'})).toBeVisible()
  expect(authRequests).toEqual([])
  const response = await page.request.get('/api/v1/environments')
  const env = (await response.json()).items.find((row: {slug:string}) => row.slug === 'e2e')
  expect(env).toBeTruthy()
  await page.goto(`/?environment=${env.id}`)
  await page.getByRole('button',{name:'立即巡检',exact:true}).click()
  await page.getByRole('button',{name:code === 'CONTROL_PLANE' ? /控制面/ : /LLM/}).click()
  const created = page.waitForResponse(r => r.url().endsWith('/api/v1/inspection-runs/trigger') && r.request().method() === 'POST')
  await page.getByRole('button',{name:'开始巡检'}).click()
  const run = await (await created).json()
  await expect(page.getByText('巡检已完成',{exact:true})).toBeVisible({timeout:90_000})
  const slug = code === 'CONTROL_PLANE' ? 'control-plane' : 'llm-runtime'
  await page.goto(`/resources/${slug}/runs/${run.id}?environment=${env.id}`)
  const checks = page.getByRole('region',{name:'本轮检查'})
  await expect(checks).toBeVisible()
  return {run,env,code,checks}
}

test('control plane: manual inspection → failed checks → stable risks and history',async ({page}) => {
  const {checks,run,env,code} = await inspect(page,'CONTROL_PLANE')
  await expect(checks.getByRole('row').filter({hasText:'FAIL'})).toHaveCount(2)
  const response = await page.request.get(`/api/v1/resource-types/${code}/inspection-history/${run.id}?environment_id=${env.id}`)
  const detail = await response.json()
  expect(detail.risk_count).toBe(2)
  expect(detail.coverage.rate).toBe(1)
  await page.reload()
  await expect(checks.getByText('topology.control_plane_anti_affinity').first()).toBeVisible()
})

test('LLM runtime: TTFT and queue conclusions are visible with actual coverage',async ({page}) => {
  const {checks,run,env,code} = await inspect(page,'LLM_RUNTIME')
  await expect(checks.getByRole('row').filter({hasText:'llm.ttft_slo'}).filter({hasText:'FAIL'})).toHaveCount(1)
  await expect(checks.getByRole('row').filter({hasText:'llm.queue_backlog'}).filter({hasText:'FAIL'})).toHaveCount(1)
  const detail = await (await page.request.get(`/api/v1/resource-types/${code}/inspection-history/${run.id}?environment_id=${env.id}`)).json()
  expect(detail.coverage.rate).toBe(1)
  expect(detail.finding_count).toBe(2)
  expect(detail.summary.conclusive_assets).toBe(1)
})

test('AI explanation references persisted TTFT and queue evidence without changing checks',async ({page}) => {
  const {run,env,code} = await inspect(page,'LLM_RUNTIME')
  const url = `/api/v1/resource-types/${code}/inspection-history/${run.id}?environment_id=${env.id}`
  const before = await (await page.request.get(url)).json()
  await page.getByRole('button',{name:'开始 AI 分析'}).click()
  await expect(page.locator('.decision-copy')).toContainText('llm.ttft_slo',{timeout:40_000})
  await expect(page.locator('.decision-copy')).toContainText('llm.queue_backlog')
  const after = await (await page.request.get(url)).json()
  expect(after.check_results).toEqual(before.check_results)
  expect(after.risk_count).toBe(before.risk_count)
})
