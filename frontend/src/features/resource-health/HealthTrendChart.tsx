import { useEffect, useRef } from 'react'
import { use, init } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

import type { ResourceSummary } from '../../api/resources'

use([LineChart, GridComponent, TooltipComponent, SVGRenderer])

export function HealthTrendChart({ trend }: { trend: ResourceSummary[] }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || trend.length === 0) return
    const chart = init(containerRef.current, undefined, { renderer: 'svg' })
    chart.setOption({
      animation: false,
      grid: { top: 12, right: 12, bottom: 24, left: 42 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: unknown) => `${value} 分`,
      },
      xAxis: {
        type: 'category',
        data: trend.map((item) => item.run_date),
        axisLabel: { color: '#6b7280' },
        axisLine: { lineStyle: { color: '#e5e7eb' } },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        splitLine: { lineStyle: { color: '#f1f5f9' } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 7,
          itemStyle: { color: '#f97316' },
          lineStyle: { color: '#f97316', width: 2 },
          data: trend.map((item) => item.health_score),
        },
      ],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [trend])

  if (trend.length === 0) return <div>暂无趋势数据</div>
  return <div aria-label="健康趋势图" ref={containerRef} style={{ height: 220, width: '100%' }} />
}
