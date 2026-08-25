export function ResourceKPI({
  label,
  value,
  detail,
}: {
  label: string
  value: string | number
  detail?: string
}) {
  return (
    <div>
      <div style={{ color: '#4b5563', fontSize: 13 }}>{label}</div>
      <div style={{ color: '#111827', fontSize: 26, fontWeight: 700, lineHeight: 1.2 }}>{value}</div>
      {detail ? <div style={{ color: '#6b7280', fontSize: 12 }}>{detail}</div> : null}
    </div>
  )
}

