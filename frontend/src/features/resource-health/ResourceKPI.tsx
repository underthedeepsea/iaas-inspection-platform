import { Card, Statistic } from 'antd'

export function ResourceKPI({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string | number
  detail?: string
  tone?: 'critical' | 'warn'
}) {
  return <Card className={`metric-card${tone ? ` metric-card-${tone}` : ''}`} bordered={false} styles={{ body: { padding: 0 } }}><Statistic title={label} value={value} /><small>{detail}</small></Card>
}
