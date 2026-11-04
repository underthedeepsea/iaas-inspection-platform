import { describe, expect, it } from 'vitest'
import { createFixtures, newCluster, newMetric } from './fixtures'
import { current, metricRows, rollbackDraft, saveDraft, validate, type Cluster } from './model'
describe('synthetic mapping boundaries', () => {
 it('allows a custom legal UID on creation', () => {
  const initial = createFixtures()
  const content = {...newCluster('demo-custom-cluster'), uid: 'demo-custom-stable-uid'}
  const created = saveDraft(initial, content, 0)
  expect(current(created, content.id)?.content).toMatchObject({uid: 'demo-custom-stable-uid'})
  expect(initial[content.id]).toBeUndefined()
 })
 it('rejects changing an existing UID to another legal UID without changing state', () => {
  const state = createFixtures()
  const original = current(state, 'demo-cluster-a')!.content as Cluster
  const changed = {...original, uid: 'demo-another-legal-uid'}
  const before = JSON.stringify(state)
  expect(validate(changed, state)).toContain('稳定 UID 创建后不可更改')
  expect(() => saveDraft(state, changed, 1)).toThrow('稳定 UID 创建后不可更改')
  expect(JSON.stringify(state)).toBe(before)
 })
 it('preserves the same UID when editing ordinary cluster fields', () => {
  const state = createFixtures()
  const original = current(state, 'demo-cluster-a')!.content as Cluster
  const saved = saveDraft(state, {...original, displayName: 'demo-updated-name', enabled: false}, 1)
  expect(current(saved, original.id)).toMatchObject({version: 2, content: {uid: original.uid, displayName: 'demo-updated-name', enabled: false}})
  expect(state[original.id]).toHaveLength(1)
 })
 it('rejects rollback from a historical different UID without changing any revision', () => {
  const initial = createFixtures()
  const id = 'demo-cluster-a'
  const original = current(initial, id)!
  const cluster = original.content as Cluster
  const state = {...initial, [id]: [
   {...original, content: {...cluster, uid: 'demo-historical-other-uid'}},
   {...original, version: 2, content: {...cluster}},
  ]}
  const before = JSON.stringify(state)
  expect(() => rollbackDraft(state, id, 1)).toThrow('不能从不同 UID 的历史内容回退')
  expect(JSON.stringify(state)).toBe(before)
  expect(initial[id]).toHaveLength(1)
 })
 it('creates and edits immutable cluster draft versions', () => {
  const initial = createFixtures(); const c = newCluster('demo-new'); const created = saveDraft(initial, c, 0)
  const edited = saveDraft(created, {...c, displayName: 'demo-renamed', enabled: false}, 1)
  expect(current(edited, c.id)?.version).toBe(2); expect(edited[c.id][0].content).toEqual(c); expect(initial[c.id]).toBeUndefined()
 })
 it('rejects monitor ID and UID collisions within source/environment', () => {
  const state = createFixtures(); const row = current(state, 'demo-cluster-a')!.content as Cluster
  expect(() => saveDraft(state, {...row, monitorId: 'demo-monitor-b'}, 1)).toThrow('冲突')
  expect(() => saveDraft(state, {...newCluster('demo-c'), uid: row.uid}, 0)).toThrow('冲突')
  expect(() => saveDraft(state, {...newCluster('demo-c'), env: 'demo-other', uid: row.uid, monitorId: row.monitorId}, 0)).not.toThrow()
 })
 it('never falls back across scopes and stores the same metric code independently', () => {
  const initial = createFixtures(); expect(metricRows(initial, 'demo-cluster-empty')).toEqual([]); expect(metricRows(initial, 'missing')).toEqual([])
  const state = saveDraft(initial, newMetric('demo-b-valid', 'demo-cluster-empty'), 0)
  expect(metricRows(state, 'demo-cluster-a').find(r => r.content.code === 'demo.cpu')?.content.id).toBe('demo-metric-cpu')
  expect(metricRows(state, 'demo-cluster-empty').find(r => r.content.id === 'demo-b-valid')?.content.clusterId).toBe('demo-cluster-empty')
 })
 it('rejects STRING numeric input and unverified histogram support', () => {
  const state = createFixtures(); const m = newMetric('demo-test', 'demo-cluster-empty')
  expect(() => saveDraft(state, {...m, sourceType: 'STRING'}, 0)).toThrow('STRING')
  expect(validate({...m, sourceType: 'HISTOGRAM', aggregation: 'p95'}, state).join()).toContain('语义未核实')
 })
 it.each([0, -1, NaN, Infinity])('rejects nonpositive or nonfinite time values %s', value => {
  const state = createFixtures(); const m = newMetric('demo-test', 'demo-cluster-empty')
  expect(() => saveDraft(state, {...m, step: value}, 0)).toThrow('正数秒')
  expect(() => saveDraft(state, {...m, window: value}, 0)).toThrow('正数秒')
 })
 it('keeps structural validity distinct from unsupported/unconfigured and NOT_RUN', () => {
  const state = saveDraft(createFixtures(), newMetric('demo-valid', 'demo-cluster-empty'), 0)
  expect(current(state, 'demo-valid')).toMatchObject({config: 'VALID', data: 'NOT_RUN'})
  expect(current(state, 'demo-metric-queue')?.content).toMatchObject({support: 'UNCONFIGURED', sourceMetric: ''})
  expect(current(state, 'demo-metric-latency')?.content).toMatchObject({support: 'UNSUPPORTED'})
 })
 it('rollback copies old content into a new unchecked draft without altering history', () => {
  const first = createFixtures(); const c = current(first, 'demo-cluster-a')!.content as Cluster
  const second = saveDraft(first, {...c, displayName: 'demo-new-name'}, 1); const frozen = JSON.stringify(second[c.id])
  const rolled = rollbackDraft(second, c.id, 1)
  expect(JSON.stringify(rolled[c.id].slice(0, 2))).toBe(frozen); expect(current(rolled, c.id)).toMatchObject({version: 3, content: c, config: 'NOT_CHECKED', data: 'NOT_RUN'})
 })
 it('rejects stale saves, real identities, malformed labels and missing scope', () => {
  const state = createFixtures(); expect(() => saveDraft(state, newCluster('demo-cluster-a'), 0)).toThrow('版本冲突')
  expect(validate({...newCluster('demo-test'), monitorId: 'real-monitor'}, state).join()).toContain('demo-')
  expect(validate({...newMetric('demo-test', 'missing'), labels: 'cluster=real'}, state).length).toBeGreaterThan(1)
 })
})
