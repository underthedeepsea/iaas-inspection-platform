import { expect, test } from '@playwright/test'

test.setTimeout(180_000)

test('logs in and follows a real inspection through history, AI, SSE, evidence, and follow-up', async ({ page }) => {
  const username = process.env.E2E_USERNAME ?? 'e2e'
  const password = process.env.E2E_PASSWORD ?? 'e2e-password'

  await page.goto('/login?next=/')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: '租户区智能巡检' })).toBeVisible()

  const environmentsResponse = await page.request.get('/api/v1/environments')
  expect(environmentsResponse.ok()).toBeTruthy()
  const environments = await environmentsResponse.json() as { items: Array<{ id: string; slug: string }> }
  const e2eEnvironment = environments.items.find((item) => item.slug === 'e2e')
  expect(e2eEnvironment).toBeTruthy()
  await page.goto(`/?environment=${e2eEnvironment?.id}`)
  await expect(page.getByRole('heading', { name: '租户区智能巡检' })).toBeVisible()

  await page.getByRole('button', { name: /立即巡检/ }).first().click()
  await page.getByRole('button', { name: /LLM/ }).click()
  await page.getByRole('button', { name: '开始巡检' }).click()
  await expect(page.getByText('巡检任务已创建')).toBeVisible()
  await expect(page.getByText('巡检已完成')).toBeVisible({ timeout: 120_000 })
  await page.getByRole('button', { name: '关闭' }).click()

  await page.getByRole('link', { name: '资源巡检', exact: true }).click()
  await expect(page.getByRole('heading', { name: '资源巡检', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: /LLM/ }).first().click()
  await page.getByRole('tab', { name: '巡检历史' }).click()
  const runDate = page.locator('button.button-link').first()
  await expect(runDate).toBeVisible()
  await runDate.click()

  await expect(page.getByRole('heading', { name: /巡检详情/ })).toBeVisible()
  await page.getByRole('button', { name: /开始 AI 分析|重新分析/ }).click()
  await expect(page.getByText('上下文已准备')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('证据工具运行中')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('证据工具已完成')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('证据已创建')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/分析已完成|分析失败/)).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText(/e2e\.llm\.scheduler\.pressure:1/)).toBeVisible()

  const question = page.getByRole('textbox', { name: '询问 AI' })
  await question.fill('请说明本轮风险的主要证据。')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText(/上下文已准备|正在恢复 AI 分析状态/)).toBeVisible({ timeout: 30_000 })
  await expect(question).toHaveValue('', { timeout: 30_000 })

  await page.reload()
  await expect(page.getByRole('heading', { name: /巡检详情/ })).toBeVisible()
  await expect(page.getByText(/e2e\.llm\.scheduler\.pressure:1/)).toBeVisible({ timeout: 30_000 })
})
