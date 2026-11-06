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


test('multi-resource inspection survives reload and ties CODE and AI to the same run', async ({page}, testInfo) => {
  test.setTimeout(120_000)
  await page.setViewportSize({width:1440,height:1000})
  const authRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/api/v1/auth/')) authRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'总览',level:1,exact:true})).toBeVisible()
  expect(authRequests).toEqual([])
  const env = (await (await page.request.get('/api/v1/environments')).json()).items.find((row:{slug:string}) => row.slug === 'e2e')
  expect(env).toBeTruthy()
  await refreshInferenceInput(page, env.id)
  await page.goto(`/?environment=${env.id}`)
  let triggerCount = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/inspection-runs/trigger')) triggerCount += 1 })
  await page.getByRole('button',{name:'立即巡检',exact:true}).click()
  const drawer = page.getByRole('dialog')
  await expect(drawer).toContainText('E2E 环境 · e2e')
  await drawer.getByRole('button',{name:/控制面/}).click()
  await drawer.getByRole('button',{name:/LLM/}).click()
  const created = page.waitForResponse(response => response.url().endsWith('/inspection-runs/trigger') && response.request().method() === 'POST')
  await drawer.getByRole('button',{name:'开始巡检',exact:true}).click()
  const run = await (await created).json()
  await expect(drawer).toContainText(run.id)
  await page.reload()
  await page.getByRole('button',{name:/查看正在进行的巡检|查看巡检完成摘要/}).click()
  await expect(drawer).toContainText(run.id)
  await expect(drawer.getByText('AI 准入评估')).toHaveCount(0)
  await expect(drawer.getByText('执行代码插件')).toBeVisible()
  await expect(drawer.getByRole('button',{name:/查看本次巡检结果/})).toBeVisible({timeout:90_000})
  expect(triggerCount).toBe(1)
  await expect(drawer.getByRole('button',{name:'查看规则库',exact:true})).toBeVisible()
  await drawer.getByRole('button',{name:/查看本次巡检结果/}).click()
  await expect(page).toHaveURL(new RegExp(`/inspection-runs/${run.id}`))
  await expect(page.getByRole('heading',{name:'本次巡检结果',level:2})).toBeVisible()
  const resultUrl = `/api/v1/inspection-runs/${run.id}/result?environment_id=${env.id}`
  const before = await (await page.request.get(resultUrl)).json()
  expect(before.run.id).toBe(run.id)
  expect(before.code_plugins).toEqual([expect.objectContaining({plugin_id:'inference-performance',plugin_version:'1.0.0',rule_code:'llm.performance_profile'})])
  expect(before.summary).toMatchObject({assets_total:1,assets_covered:1,check_count:1,fail_count:1,risk_count:1})
  expect(before.check_results).toEqual([expect.objectContaining({inspection_item_code:'llm.performance_profile',status:'FAIL'})])
  expect(before.risks).toHaveLength(1)
  await page.getByText('全部检查、原规则与冻结证据',{exact:true}).click()
  const table = page.getByRole('region',{name:'本轮检查'})
  await table.getByText('规则来源',{exact:true}).click()
  await expect(table.getByText('CODE',{exact:true})).toHaveCount(before.check_results.length)
  await expect(table.getByText('v1.0.0',{exact:true})).toHaveCount(before.check_results.length)
  await page.getByRole('button',{name:'智能解读本轮',exact:true}).click()
  await expect(page.getByRole('region',{name:'AI 巡检助手'})).toContainText('AI · 只读解释')
  await page.screenshot({path:testInfo.outputPath('inspection-result.png'),fullPage:true})
  await page.reload()
  await expect(page.getByRole('heading',{name:'本次巡检结果',level:2})).toBeVisible()
  const reloaded = await (await page.request.get(resultUrl)).json()
  expect(reloaded.run.id).toBe(run.id)
  expect(reloaded.check_results).toEqual(before.check_results)
  expect(reloaded.risks).toEqual(before.risks)
  await page.getByRole('link',{name:'← 返回总览'}).click()
  await expect(page.getByRole('complementary',{name:'最近完成的巡检'})).toContainText(run.id.slice(0,8))
  await page.getByRole('textbox',{name:'向 AI 巡检助手提问'}).fill('哪些是代码分析？')
  const asked = page.waitForResponse(response => response.url().endsWith('/dashboard/ask/stream') && response.request().method() === 'POST')
  await page.getByRole('button',{name:'发送问题'}).click()
  const streamed = await asked
  expect(streamed.ok()).toBeTruthy()
  const frames = (await streamed.text()).split(/\r?\n\r?\n/).filter(frame => frame.includes('data:')).map(frame => ({
    event: frame.split(/\r?\n/).find(line => line.startsWith('event:'))?.slice(6).trim(),
    data: JSON.parse(frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')),
  }))
  expect(frames.filter(frame => frame.event === 'result')).toHaveLength(1)
  expect(frames.find(frame => frame.event === 'done')?.data.outcome).toBe('success')
  const answer = frames.find(frame => frame.event === 'result')!.data
  expect(answer.ai_status).toBe('ACCEPTED')
  expect(answer.grounded_report.source).toBe('CODE')
  expect(answer.inspection_run_id).toBe(run.id)
  expect(answer.source.type).toBe('AI')
  expect(answer.references).toEqual(expect.arrayContaining([expect.objectContaining({type:'CHECK_RESULT',id:before.check_results[0].id,source:'CODE'})]))
  await expect(page.locator('.dashboard-ai-answer')).toContainText('推理性能')
  await expect(page.locator('.dashboard-ai-answer').getByRole('link',{name:`RUN ${run.id.slice(0,8)} ↗`})).toBeVisible()
  const after = await (await page.request.get(resultUrl)).json()
  expect(after.check_results).toEqual(before.check_results)
  expect(after.risks).toEqual(before.risks)
  await page.screenshot({path:testInfo.outputPath('dashboard.png'),fullPage:true})
  await page.getByRole('link',{name:'规则库',exact:true}).click()
  await expect(page.locator('.plugin-card')).toHaveCount(3)
  await expect(page.getByText('evaluate',{exact:true})).toHaveCount(3)
  await page.reload()
  await expect(page.locator('.plugin-card')).toHaveCount(3)
  await page.screenshot({path:testInfo.outputPath('rules.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  await expect(page.getByRole('heading',{name:'规则库',level:2})).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button',{name:'打开主导航',exact:true}).click()
  await page.getByRole('link',{name:'总览',exact:true}).click()
  await expect(page.getByRole('textbox',{name:'向 AI 巡检助手提问'})).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({path:testInfo.outputPath('dashboard-mobile.png'),fullPage:true})
})
