import type { Cluster, MappingState, Metric } from './model'
export const newCluster = (id: string): Cluster => ({kind: 'cluster', id, source: 'demo-monitor', env: 'demo-lab', uid: id, displayName: id, monitorId: id, enabled: true})
export const newMetric = (id: string, clusterId: string): Metric => ({kind: 'metric', id, clusterId, code: 'demo.cpu', sourceMetric: 'demo.cpu_usage', labels: 'demo_cluster=demo-a', sourceType: 'GAUGE', sourceUnit: 'percent', outputUnit: 'percent', conversion: 1, window: 300, step: 60, aggregation: 'mean', support: 'SUPPORTED', enabled: true})
export function createFixtures(): MappingState {
 const rows = [
  {...newCluster('demo-cluster-a'), displayName: 'demo-alpha', monitorId: 'demo-monitor-a'},
  {...newCluster('demo-cluster-b'), displayName: 'demo-beta', monitorId: 'demo-monitor-b'},
  {...newCluster('demo-cluster-empty'), displayName: 'demo-empty'},
  newMetric('demo-metric-cpu', 'demo-cluster-a'),
  {...newMetric('demo-metric-queue', 'demo-cluster-a'), code: 'demo.controller_queue', sourceMetric: '', labels: '', support: 'UNCONFIGURED' as const},
  {...newMetric('demo-metric-latency', 'demo-cluster-a'), code: 'demo.api_latency', sourceMetric: 'demo.api_buckets', sourceType: 'HISTOGRAM' as const, sourceUnit: 'seconds', outputUnit: 'seconds', aggregation: 'p95' as const, support: 'UNSUPPORTED' as const},
  {...newMetric('demo-metric-string', 'demo-cluster-b'), code: 'demo.cpu', sourceType: 'STRING' as const, labels: 'demo_cluster=demo-b'},
 ]
 return Object.fromEntries(rows.map(content => [content.id, [{version: 1, content, config: 'NOT_CHECKED', data: 'NOT_RUN', reason: '合成初始草稿；未生效'}]]))
}
