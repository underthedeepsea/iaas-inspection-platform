import { expect, test } from '@playwright/test'

test('shows an unavailable model as a retryable AI failure', async ({ page }) => {
  const eventStream = [
    'id: 1\nevent: context.ready\ndata: {"sequence":1,"event_type":"context.ready","status":"COMPLETED","payload":{}}\n\n',
    'id: 2\nevent: analysis.started\ndata: {"sequence":2,"event_type":"analysis.started","status":"STARTED","payload":{}}\n\n',
    'id: 3\nevent: analysis.failed\ndata: {"sequence":3,"event_type":"analysis.failed","status":"FAILED","payload":{"summary":"LLM unavailable","error_code":"LLM_UNAVAILABLE"}}\n\n',
  ].join('')

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/auth/me') {
      await route.fulfill({ json: { user_id: 'failure-user', username: 'e2e', roles: ['operator', 'viewer'] } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/environments') {
      await route.fulfill({ json: { items: [{ id: 'env-1', slug: 'staging', name: '测试环境', environment_type: 'TEST', timezone: 'Asia/Shanghai', assets_count: 1, mock_dataset_count: 1, inspection_run_count: 1, has_mock_data: true }], page: 1, page_size: 1, total: 1 } })
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/overview')) {
      await route.fulfill({ json: { resource_type: { code: 'LLM_RUNTIME', name: '大模型运行时', description: '', icon: '', asset_count: 1, inspection_item_count: 1, health_score: 92, risk_count: 1, p1_count: 0, p2_count: 1, last_inspection_at: '2026-08-25T08:00:00Z' }, latest: null, health_trend: [] } })
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/inspection-history')) {
      await route.fulfill({ json: { items: [{ id: 'summary-1', inspection_run_id: 'run-1', resource_type: 'LLM_RUNTIME', run_date: '2026-08-25', status: 'SUCCEEDED', assets_total: 1, assets_covered: 1, coverage_rate: 1, inspection_item_count: 1, success_item_count: 1, failed_item_count: 0, finding_count: 1, risk_count: 1, p1_count: 0, p2_count: 1, p3_count: 0, p4_count: 0, ai_dependent_cases: 1, ai_investigation_count: 0, health_score: 92, started_at: null, finished_at: null, summary: {} }], page: 1, page_size: 20, total: 1 } })
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/inspection-history/run-1')) {
      await route.fulfill({ json: { resource_type: 'LLM_RUNTIME', run: { id: 'run-1', status: 'SUCCEEDED', run_date: '2026-08-25', started_at: null, finished_at: null }, coverage: { assets_total: 1, assets_covered: 1, rate: 1 }, inspection_item_status_counts: { SUCCEEDED: 1 }, inspection_item_count: 1, finding_count: 1, risk_count: 1, severity_counts: { P1: 0, P2: 1 }, ai_dependent_cases: 1, ai_investigation_count: 0, major_risks: [], summary: {} } })
      return
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/investigations')) {
      await route.fulfill({ status: 201, json: { id: 'failure-investigation', investigation_id: 'failure-investigation', status: 'CREATED', conversation_id: 'failure-conversation' } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/investigations/failure-investigation') {
      await route.fulfill({ json: { id: 'failure-investigation', investigation_id: 'failure-investigation', status: 'FAILED', conclusion: 'LLM unavailable', confidence: 0, conversation_id: 'failure-conversation' } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/investigations/failure-investigation/events') {
      await route.fulfill({ contentType: 'text/event-stream', body: eventStream })
      return
    }
    await route.continue()
  })

  await page.goto('/resources/llm-runtime')
  await page.getByLabel('巡检环境').click()
  await page.locator('.ant-select-dropdown .ant-select-item-option').filter({ hasText: '测试环境' }).click()
  await page.getByRole('tab', { name: '巡检历史' }).click()
  await page.getByRole('button', { name: '2026-08-25' }).click()
  await page.getByRole('button', { name: '开始 AI 分析' }).click()

  await expect(page.getByText('上下文已准备')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('分析失败')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('LLM unavailable')).toBeVisible()
  await expect(page.getByRole('button', { name: '重新分析' })).toBeVisible()
})
