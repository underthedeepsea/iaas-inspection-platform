import { expect, test } from '@playwright/test'

const resource = {
  code: 'LLM_RUNTIME', name: '大模型运行时', description: '', icon: '', asset_count: 1,
  inspection_item_count: 1, health_score: 92, risk_count: 1, p1_count: 0, p2_count: 1,
  last_inspection_at: '2026-08-25T08:00:00Z',
}

test('explains a resource run synchronously on demand', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/v1/auth/me') {
      await route.fulfill({ json: { user_id: 'user-1', username: 'e2e', roles: ['operator', 'viewer'] } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/environments') {
      await route.fulfill({ json: { items: [{ id: 'env-1', slug: 'staging', name: '测试环境', environment_type: 'TEST', timezone: 'Asia/Shanghai', assets_count: 1, mock_dataset_count: 1, inspection_run_count: 1, has_mock_data: true }], page: 1, page_size: 1, total: 1 } })
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/overview')) {
      await route.fulfill({ json: { resource_type: resource, latest: null, health_trend: [] } })
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/inspection-history')) {
      await route.fulfill({ json: {
        items: [{ id: 'summary-1', inspection_run_id: 'run-1', resource_type: 'LLM_RUNTIME', run_date: '2026-08-25', status: 'SUCCEEDED', assets_total: 1, assets_covered: 1, coverage_rate: 1, inspection_item_count: 1, success_item_count: 1, failed_item_count: 0, finding_count: 1, risk_count: 1, p1_count: 0, p2_count: 1, p3_count: 0, p4_count: 0, ai_dependent_cases: 0, ai_investigation_count: 0, health_score: 92, started_at: null, finished_at: null, summary: {} }],
        page: 1, page_size: 20, total: 1,
      } })
      return
    }
    if (request.method() === 'GET' && url.pathname.endsWith('/inspection-history/run-1')) {
      await route.fulfill({ json: {
        resource_type: 'LLM_RUNTIME',
        run: { id: 'run-1', status: 'SUCCEEDED', run_date: '2026-08-25', started_at: null, finished_at: null },
        coverage: { assets_total: 1, assets_covered: 1, rate: 1 },
        inspection_item_status_counts: { SUCCEEDED: 1 }, inspection_item_count: 1, finding_count: 1, risk_count: 1,
        severity_counts: { P1: 0, P2: 1 }, ai_dependent_cases: 0, ai_investigation_count: 0,
        major_risks: [], summary: {},
      } })
      return
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/analysis')) {
      await route.fulfill({ status: 201, json: { id: 'investigation-1', investigation_id: 'investigation-1', status: 'RESOLVED', conclusion: '资源运行稳定。' } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/investigations/investigation-1') {
      await route.fulfill({ json: { id: 'investigation-1', investigation_id: 'investigation-1', status: 'RESOLVED', conclusion: '资源运行稳定。', confidence: 0.8 } })
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
  await expect(page.getByText('资源运行稳定。')).toBeVisible()

  await page.reload()
  await page.getByLabel('巡检环境').click()
  await page.locator('.ant-select-dropdown .ant-select-item-option').filter({ hasText: '测试环境' }).click()
  await expect(page.getByRole('button',{name:'开始 AI 分析'})).toBeVisible()
  await expect(page.getByText('资源运行稳定。')).toHaveCount(0)
})
