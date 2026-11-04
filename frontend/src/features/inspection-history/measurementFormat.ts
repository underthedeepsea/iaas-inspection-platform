const byteUnits = ['B', 'kB', 'MB', 'GB', 'TB', 'PB'] as const
const readableNumber = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 2, useGrouping: false})

function compactNumber(value: number) {
  // Tiny nonzero measurements must not look like a measured zero.
  if (value !== 0 && Math.abs(value) < 0.005) {
    const [mantissa, exponent] = value.toExponential(2).split('e')
    return `${Number(mantissa)}e${Number(exponent)}`
  }
  return readableNumber.format(value)
}

function missingValue(value: number | null | undefined) {
  if (value == null) return '未提供'
  if (!Number.isFinite(value)) return '无效数值'
  return null
}

/** Decimal SI units: 1 kB = 1000 bytes. Formatting never changes source measurements. */
export function formatBytes(value: number | null | undefined) {
  const missing = missingValue(value)
  if (missing) return missing
  let scaled = value as number
  let unitIndex = 0
  while (Math.abs(scaled) >= 1000 && unitIndex < byteUnits.length - 1) {
    scaled /= 1000
    unitIndex += 1
  }
  // Promote a rounded unit boundary too, so 999.999 B reads as 1 kB.
  if (Math.abs(scaled) >= 999.995 && unitIndex < byteUnits.length - 1) {
    scaled /= 1000
    unitIndex += 1
  }
  return `${compactNumber(scaled)} ${byteUnits[unitIndex]}`
}

export function formatBytesPerSecond(value: number | null | undefined) {
  const missing = missingValue(value)
  return missing ?? `${formatBytes(value)}/s`
}

export function formatDurationSeconds(value: number | null | undefined) {
  const missing = missingValue(value)
  if (missing) return missing
  const seconds = value as number
  const [divisor, unit] = Math.abs(seconds) >= 86400 ? [86400, '天']
    : Math.abs(seconds) >= 3600 ? [3600, '小时']
    : Math.abs(seconds) >= 60 ? [60, '分钟'] : [1, '秒']
  return `${compactNumber(seconds / divisor)} ${unit}`
}
