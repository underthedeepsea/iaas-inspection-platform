import { expect, test } from '@playwright/test'

const resources = {
  items: [
    {
      code: 'CONTROL_PLANE', name: '控制面', description: '', icon: '', asset_count: 24,
      inspection_item_count: 6, health_score: 96, risk_count: 0, p1_count: 0, p2_count: 0,
      last_inspection_at: null,
    },
    {
      code: 'LLM_RUNTIME', name: '大模型运行时', description: '', icon: '', asset_count: 24,
      inspection_item_count: 6, health_score: 92, risk_count: 1, p1_count: 0, p2_count: 1,
      last_inspection_at: null,
    },
  ], page: 1, page_size: 2, total: 2,
}

test('completes the immediate inspection workflow', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/resource-types') {
      await route.fulfill({ json: resources })
      return
    }
    if (request.method() === 'POST' && url.pathname === '/api/v1/inspection-runs/trigger') {
      await route.fulfill({
        status: 201,
        json: {
          id: 'run-1', inspection_run_id: 'run-1', status: 'PENDING', trigger_type: 'MANUAL',
          scope: { resource_types: ['CONTROL_PLANE', 'LLM_RUNTIME'], asset_count: 48, inspection_item_count: 12 },
        },
      })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/inspection-runs/run-1/events') {
      await route.fulfill({
        contentType: 'text/event-stream',
        body: [
          'id: 1\nevent: scope.resolved\ndata: {"sequence":1,"event_type":"scope.resolved","status":"PENDING","payload":{"asset_count":48,"inspection_item_count":12}}\n\n',
          'id: 2\nevent: assets.discovered\ndata: {"sequence":2,"event_type":"assets.discovered","status":"PENDING","payload":{"asset_count":48}}\n\n',
          'id: 3\nevent: run.completed\ndata: {"sequence":3,"event_type":"run.completed","status":"SUCCEEDED","payload":{"completed_asset_count":48}}\n\n',
        ].join(''),
      })
      return
    }
    await route.continue()
  })

  await page.goto('/')
  await page.getByLabel('巡检环境').selectOption('staging')
  await page.getByRole('button', { name: /立即巡检/ }).click()
  await page.getByRole('button', { name: /控制面/ }).click()
  await page.getByRole('button', { name: /大模型运行时/ }).click()
  await expect(page.getByText('范围预览：48 个资源对象 / 12 个巡检项')).toBeVisible()
  await page.getByRole('button', { name: '开始巡检' }).click()

  await expect(page.getByText('巡检任务已创建')).toBeVisible()
  await expect(page.getByText('巡检已完成')).toBeVisible()
  await expect(page.getByText('48 / 48 个资源对象')).toBeVisible()
})

