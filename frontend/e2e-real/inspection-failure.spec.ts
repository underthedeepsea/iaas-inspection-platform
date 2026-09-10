import { expect, test } from '@playwright/test'

test('AI transport unavailable leaves persisted inspection results visible', async ({page}) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(process.env.E2E_USERNAME ?? 'e2e')
  await page.getByLabel('密码').fill(process.env.E2E_PASSWORD ?? 'e2e-password')
  await page.getByRole('button',{name:'登录'}).click()
  await expect(page.getByRole('heading',{name:'租户区智能巡检'})).toBeVisible()
  const env = (await (await page.request.get('/api/v1/environments')).json()).items.find((r:{slug:string}) => r.slug === 'e2e')
  const created = await page.request.post('/api/v1/inspection-runs/trigger',{data:{environment_id:env.id,scope:{resource_types:['LLM_RUNTIME']},trigger_options:{ai_mode:'DISABLED'}}})
  expect(created.ok()).toBeTruthy()
  const run = await created.json()
  const url = `/api/v1/resource-types/LLM_RUNTIME/inspection-history/${run.id}?environment_id=${env.id}`
  await expect.poll(async()=> (await page.request.get(url)).status(),{timeout:90_000}).toBe(200)
  const before = await (await page.request.get(url)).json()
  await page.goto(`/resources/llm-runtime/runs/${run.id}?environment=${env.id}`)
  await page.route('**/api/v1/resource-types/LLM_RUNTIME/analysis',r=>r.abort('failed'))
  await page.getByRole('button',{name:'开始 AI 分析'}).click()
  await expect(page.getByRole('alert')).toHaveText('AI 分析暂不可用')
  await expect(page.getByRole('region',{name:'本轮检查'}).getByText('FAIL').first()).toBeVisible()
  const after = await (await page.request.get(url)).json()
  expect(after.check_results).toEqual(before.check_results)
  expect(after.risk_count).toBe(before.risk_count)
})
