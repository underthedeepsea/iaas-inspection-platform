import { useEffect, useRef } from 'react'
import { use, init } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

use([LineChart, GridComponent, TooltipComponent, SVGRenderer])

export interface HealthTrendPoint {
  run_date?: string | null
  snapshot_date?: string | null
  health_score?: number | null
  risk_total?: number | null
  risk_count?: number | null
  p1_count?: number | null
  p2_count?: number | null
}

export function HealthTrendChart({
  trend,
  metric = 'health',
}: {
  trend: HealthTrendPoint[]
  metric?: 'health' | 'risk'
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const visibleTrend = metric === 'health' ? trend.filter((item) => item.health_score != null) : trend

  useEffect(() => {
    if (!containerRef.current || visibleTrend.length === 0) return
    const chart = init(containerRef.current, undefined, { renderer: 'svg' })
    const values = visibleTrend.map((item) => metric === 'risk' ? (item.risk_total ?? item.risk_count ?? 0) : item.health_score as number)
    chart.setOption({
      animation: false,
      grid: { top: 12, right: 12, bottom: 24, left: 42 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: unknown) => `${metric === 'risk' ? '风险总数' : '健康度'}：${value}`,
      },
      xAxis: {
        type: 'category',
        data: visibleTrend.map((item) => item.run_date ?? item.snapshot_date ?? '—'),
        axisLabel: { color: '#6f7d87' },
        axisLine: { lineStyle: { color: '#e4e9eb' } },
      },
      yAxis: {
        type: 'value',
        min: metric === 'health' ? 0 : undefined,
        max: metric === 'health' ? 100 : undefined,
        splitLine: { lineStyle: { color: '#edf0f1' } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 7,
          itemStyle: { color: '#F97316' },
          lineStyle: { color: '#F97316', width: 2 },
          areaStyle: { color: 'rgba(255, 247, 237, .75)' },
          data: values,
        },
      ],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [metric, visibleTrend])

  if (visibleTrend.length === 0) return <div className="trend-chart"><span className="empty-cell">暂无趋势数据</span></div>
  return <div aria-label={metric === 'risk' ? '风险趋势图' : '健康趋势图'} className="trend-chart"><div ref={containerRef} style={{ height: '100%', width: '100%' }} /></div>
}
