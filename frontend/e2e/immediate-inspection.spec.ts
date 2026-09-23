import { expect, test } from '@playwright/test'

const resources = {
  items: [
    {
      code: 'CONTROL_PLANE', name: '控制面', description: '', icon: '', release_state: 'PLANNED', asset_count: 24,
      inspection_item_count: 0, health_score: null, risk_count: 0, p1_count: 0, p2_count: 0,
      last_inspection_at: null,
    },
    {
      code: 'LLM_RUNTIME', name: '大模型运行时', description: '', icon: '', release_state: 'READY', asset_count: 24,
      inspection_item_count: 1, health_score: 92, risk_count: 1, p1_count: 0, p2_count: 1,
      last_inspection_at: null,
    },
  ], page: 1, page_size: 2, total: 2,
}

test('completes the immediate inspection workflow', async ({ page }) => {
  const authRequests: string[] = []
  const triggerScopes: unknown[] = []
  page.on('request', request => { if (request.url().includes('/api/v1/auth/')) authRequests.push(request.url()) })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/environments') {
      await route.fulfill({ json: { items: [{ id: 'env-1', slug: 'staging', name: '测试环境', environment_type: 'TEST', timezone: 'Asia/Shanghai', assets_count: 48, mock_dataset_count: 1, inspection_run_count: 0, has_mock_data: true }], page: 1, page_size: 1, total: 1 } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/resource-types') {
      await route.fulfill({ json: resources })
      return
    }
    if (request.method() === 'POST' && url.pathname === '/api/v1/inspection-runs/trigger') {
      triggerScopes.push(request.postDataJSON())
      await route.fulfill({
        status: 201,
        json: {
          id: 'run-1', inspection_run_id: 'run-1', status: 'PENDING', trigger_type: 'MANUAL',
          scope: { resource_types: ['LLM_RUNTIME'], asset_count: 24, inspection_item_count: 1 },
        },
      })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/inspection-runs/run-1/events') {
      await route.fulfill({
        contentType: 'text/event-stream',
        body: [
          'id: 1\nevent: scope.resolved\ndata: {"sequence":1,"event_type":"scope.resolved","status":"PENDING","payload":{"asset_count":24,"inspection_item_count":1}}\n\n',
          'id: 2\nevent: assets.discovered\ndata: {"sequence":2,"event_type":"assets.discovered","status":"PENDING","payload":{"asset_count":24}}\n\n',
          'id: 3\nevent: run.completed\ndata: {"sequence":3,"event_type":"run.completed","status":"SUCCEEDED","payload":{"completed_asset_count":24}}\n\n',
        ].join(''),
      })
      return
    }
    await route.continue()
  })

  await page.goto('/')
  expect(authRequests).toEqual([])
  await page.getByLabel('巡检环境').click()
  await page.locator('.ant-select-dropdown .ant-select-item-option').filter({ hasText: '测试环境' }).click()
  await page.getByRole('button', { name: /立即巡检/ }).click()
  await expect(page.getByRole('button', { name: /控制面/ })).toHaveCount(0)
  await page.getByRole('button', { name: /大模型运行时/ }).click()
  await expect(page.getByText('范围预览：24 个资源对象 / 1 个巡检项')).toBeVisible()
  await page.getByRole('button', { name: '开始巡检' }).click()
  await expect.poll(() => triggerScopes).toEqual([{
    environment_id: 'env-1',
    scope: { resource_types: ['LLM_RUNTIME'] },
    trigger_options: { ai_mode: 'DEFERRED' },
  }])

  await expect(page.getByRole('heading', {name: '本次巡检已完成', exact: true})).toBeVisible()
  await expect(page.getByRole('button', {name: /查看本次巡检结果/})).toBeVisible()
  await expect(page.getByText('24 / 24 个资源对象')).toBeVisible()
})
