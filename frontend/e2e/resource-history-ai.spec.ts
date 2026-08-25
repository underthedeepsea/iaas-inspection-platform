import { expect, test } from '@playwright/test'

const resource = {
  code: 'LLM_RUNTIME', name: '大模型运行时', description: '', icon: '', asset_count: 1,
  inspection_item_count: 1, health_score: 92, risk_count: 1, p1_count: 0, p2_count: 1,
  last_inspection_at: '2026-08-25T08:00:00Z',
}

test('restores resource run AI analysis after refresh', async ({ page }) => {
  const eventStream = [
    'id: 1\nevent: context.ready\ndata: {"sequence":1,"event_type":"context.ready","status":"COMPLETED","payload":{}}\n\n',
    'id: 2\nevent: history.loaded\ndata: {"sequence":2,"event_type":"history.loaded","status":"COMPLETED","payload":{}}\n\n',
    'id: 3\nevent: tool.completed\ndata: {"sequence":3,"event_type":"tool.completed","status":"COMPLETED","payload":{"tool":"summary"}}\n\n',
    'id: 4\nevent: analysis.completed\ndata: {"sequence":4,"event_type":"analysis.completed","status":"COMPLETED","payload":{"summary":"基于成功证据完成分析。"}}\n\n',
  ].join('')

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
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
    if (request.method() === 'POST' && url.pathname.endsWith('/investigations')) {
      await route.fulfill({ status: 201, json: { id: 'investigation-1', investigation_id: 'investigation-1', status: 'RESOLVED' } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/investigations/investigation-1') {
      await route.fulfill({ json: { id: 'investigation-1', investigation_id: 'investigation-1', status: 'RESOLVED', conclusion: '资源运行稳定。', confidence: 0.8 } })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/investigations/investigation-1/events') {
      await route.fulfill({ contentType: 'text/event-stream', body: eventStream })
      return
    }
    await route.continue()
  })

  await page.goto('/resources/llm-runtime')
  await page.getByLabel('巡检环境').selectOption('staging')
  await page.getByRole('tab', { name: '巡检历史' }).click()
  await page.getByRole('button', { name: '2026-08-25' }).click()
  await page.getByRole('button', { name: '开始 AI 分析' }).click()
  await expect(page.getByText('资源运行稳定。')).toBeVisible()

  await page.reload()
  await page.getByLabel('巡检环境').selectOption('staging')
  await expect(page.getByText('资源运行稳定。')).toBeVisible()
  await expect(page.getByText('分析已完成')).toBeVisible()
})

