import { describe, expect, it } from 'vitest'
import { formatBytes, formatBytesPerSecond, formatDurationSeconds } from './measurementFormat'

describe('readable capacity and rate measurements', () => {
  it('uses decimal SI scaling and keeps at most two fractional digits', () => {
    expect(formatBytes(88510686035)).toBe('88.51 GB')
    expect(formatBytes(185597562768)).toBe('185.6 GB')
    expect(formatBytes(219902325555.2)).toBe('219.9 GB')
    expect(formatBytes(1000)).toBe('1 kB')
    expect(formatBytes(1024)).toBe('1.02 kB')
    expect(formatBytes(1_000_000)).toBe('1 MB')
    expect(formatBytes(1_000_000_000_000)).toBe('1 TB')
    expect(formatBytes(1_000_000_000_000_000)).toBe('1 PB')
    expect(formatBytes(999.999)).toBe('1 kB')
    expect(formatBytesPerSecond(-9162596.9)).toBe('-9.16 MB/s')
    expect(formatBytesPerSecond(-87960930.22222222)).toBe('-87.96 MB/s')
  })

  it('preserves zero, signs and tiny nonzero measurements without inventing missing values', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytesPerSecond(-0)).toBe('-0 B/s')
    expect(formatBytes(-12.345)).toBe('-12.35 B')
    expect(formatBytes(0.001)).toBe('1e-3 B')
    expect(formatBytesPerSecond(-0.0000012345)).toBe('-1.23e-6 B/s')
    for (const value of [null, undefined]) {
      expect(formatBytes(value)).toBe('未提供')
      expect(formatBytesPerSecond(value)).toBe('未提供')
    }
    for (const value of [NaN, Infinity, -Infinity]) {
      expect(formatBytes(value)).toBe('无效数值')
      expect(formatBytesPerSecond(value)).toBe('无效数值')
    }
  })
})

it('adapts reserve durations while preserving zero and invalid input', () => {
  expect(formatDurationSeconds(0)).toBe('0 秒')
  expect(formatDurationSeconds(45.123)).toBe('45.12 秒')
  expect(formatDurationSeconds(90)).toBe('1.5 分钟')
  expect(formatDurationSeconds(5400)).toBe('1.5 小时')
  expect(formatDurationSeconds(129600)).toBe('1.5 天')
  expect(formatDurationSeconds(0.001)).toBe('1e-3 秒')
  expect(formatDurationSeconds(undefined)).toBe('未提供')
  expect(formatDurationSeconds(null)).toBe('未提供')
  expect(formatDurationSeconds(Infinity)).toBe('无效数值')
})
