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
  return (
    <article className={`metric-card${tone ? ` metric-card-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  )
}
