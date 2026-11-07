import { expect, it } from 'vitest'
import { formatReportMeasurement, formatReportRatio, reportMeasurementValues, reportMetricLabel } from './reportMeasurementPresentation'

it('formats capacity, rates and reserve duration with public formatters', () => {
  const item = { layer: 'HARDWARE', key: 'filesystem:data/available_bytes', current: 185597562768, reserve_bytes: 219902325555.2, short_slope_bytes_per_second: -87960930.22361112, seconds_to_reserve: 0 }
  expect(reportMetricLabel(item)).toBe('文件系统 data 可用空间')
  expect(reportMeasurementValues(item)).toEqual([
    { label: '历史测量值', value: '185.6 GB' }, { label: '短期斜率', value: '-87.96 MB/s' },
    { label: '保留水位', value: '219.9 GB' }, { label: '到保留水位（不是写满时间）', value: '0 秒' },
  ])
})
it('chooses one latency unit for current, threshold, baseline and both trend halves', () => {
  const item = { layer: 'DYNAMIC', metric: 'ttft.p95_ms', current: 1401.0373, threshold: 900, boundary: 309.10586, baseline_median: 220.7899, first_half_median: 221.59375, second_half_median: 1342.1504 }
  expect(formatReportMeasurement(item, item.current)).toBe('1.4 秒')
  expect(formatReportMeasurement(item, item.threshold)).toBe('0.9 秒')
  expect(formatReportMeasurement(item, item.boundary)).toBe('0.31 秒')
  expect(formatReportMeasurement(item, item.first_half_median)).toBe('0.22 秒')
  const subsecond = { ...item, current: 339.7773, second_half_median: 342.1504 }
  expect(formatReportMeasurement(subsecond, subsecond.current)).toBe('339.78 ms')
  expect(formatReportMeasurement(subsecond, subsecond.threshold)).toBe('900 ms')
  expect(formatReportMeasurement({ layer: 'DYNAMIC', metric: 'e2e.p99_ms', current: 90000, boundary: 500 }, 500)).toBe('500 ms')
})
it('shows ratios as percentages with at most two decimal places and preserves tiny nonzero values', () => {
  expect(formatReportRatio(.5406473781172649)).toBe('54.06%')
  expect(formatReportRatio(-.23676253957101123)).toBe('-23.68%')
  expect(formatReportRatio(.2)).toBe('20%')
  expect(formatReportMeasurement({ layer: 'FIXED', metric: 'tpot.p95_ms', current: .001 }, .001)).toBe('1.00e-3 ms')
  expect(formatReportMeasurement({ layer: 'FIXED' }, undefined)).toBe('未提供')
  expect(formatReportMeasurement({ layer: 'FIXED' }, Infinity)).toBe('无效数值')
})
it('keeps EVENT measurement semantics distinct from window measurements', () => {
  expect(reportMeasurementValues({ layer: 'HARDWARE', key: 'gpu/ecc_dbe_delta', current: 1, value_semantics: 'EVENT' })).toEqual([{ label: '事件时数值', value: '1' }])
  expect(reportMeasurementValues({ layer: 'HARDWARE', value: 2 })).toEqual([{ label: '历史测量值', value: '2' }])
})

it('retains signed tiny nonzero ratios and keeps true zero at 0%', () => {
  expect(formatReportRatio(.000001)).toBe('1e-4%')
  expect(formatReportRatio(-.000001)).toBe('-1e-4%')
  expect(formatReportRatio(Number.MIN_VALUE)).not.toBe('0%')
  expect(formatReportRatio(-Number.MIN_VALUE)).not.toBe('-0%')
  expect(formatReportRatio(0)).toBe('0%')
  expect(formatReportRatio(-0)).toBe('0%')
  expect(reportMeasurementValues({ layer: 'TREND', change_ratio: .000001, change_boundary: -.000001 })).toEqual([
    { label: '变化', value: '1e-4%' }, { label: '趋势变化边界', value: '-1e-4%' },
  ])
})
it('keeps the tiny-percentage rounding boundary and ordinary ratio outputs stable', () => {
  expect(formatReportRatio(.000049)).toBe('4.9e-3%')
  expect(formatReportRatio(-.000049)).toBe('-4.9e-3%')
  expect(formatReportRatio(.00005)).toBe('0.01%')
  expect(formatReportRatio(-.00005)).toBe('-0.01%')
  expect(formatReportRatio(.000051)).toBe('0.01%')
  expect(formatReportRatio(-.000051)).toBe('-0.01%')
  expect(formatReportRatio(.5406473781172649)).toBe('54.06%')
  expect(formatReportRatio(1.3946116390157315)).toBe('139.46%')
  expect(formatReportRatio(Infinity)).toBe('无效数值')
  expect(formatReportRatio(NaN)).toBe('无效数值')
})
