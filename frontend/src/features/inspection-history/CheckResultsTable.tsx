import type { CheckResult } from '../../api/resources'

function FactValue({ value }: { value: unknown }) {
  if (value == null) return <span>—</span>
  if (typeof value !== 'object') return <span>{typeof value === 'boolean' ? value ? '是' : '否' : String(value)}</span>
  if (Array.isArray(value)) return <span>{value.map(v => typeof v === 'object' ? '对象' : String(v)).join('、') || '—'}</span>
  return <dl className="check-facts">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key}</dt><dd><FactValue value={item} /></dd></div>)}</dl>
}

export function CheckResultsTable({ results = [] }: { results?: CheckResult[] }) {
  const priority = { FAIL: 0, ERROR: 1, UNKNOWN: 2, PASS: 3, NOT_APPLICABLE: 4 }
  const rows = [...results].sort((a, b) => priority[a.status] - priority[b.status])
  return <section className="panel check-results-panel" aria-label="本轮检查">
    <div className="section-heading"><div><h3>代码插件检查结果</h3><p className="panel-lede">每条判定对应一个资源对象，证据与版本随巡检保留。</p></div><span className="legend">{results.length} 条检查</span></div>
    {results.length ? <div className="table-wrap"><table className="data-table check-results-table"><thead><tr><th>来源</th><th>检查</th><th>资产</th><th>结果</th><th>观测值</th><th>期望值</th><th>证据与时间</th></tr></thead><tbody>
      {rows.map(result => <tr id={`check-${result.id}`} key={result.id}>
        <td><span className="analysis-source-code source-badge">CODE</span><strong className="plugin-source-name">{result.source?.plugin_name ?? '历史代码检查'}</strong><small className="mono">{result.source?.plugin_version ? `v${result.source.plugin_version}` : '版本未记录'}</small></td>
        <td><strong>{result.inspection_item_name}</strong><small className="check-rule-code mono">{result.inspection_item_code}</small></td><td>{result.asset_name}</td>
        <td><strong className={`check-status check-status-${result.status.toLowerCase()}`}>{result.status}</strong>{result.status === 'UNKNOWN' ? <small className="check-note">证据不足</small> : null}</td>
        <td><FactValue value={result.observed_value} /></td><td><FactValue value={result.expected_value} /></td>
        <td><details className="check-evidence"><summary>展开证据</summary><p>{result.summary}</p><p>Asset：{result.asset_id}</p><time>{result.checked_at}</time><pre>{JSON.stringify(result.evidence,null,2)}</pre></details></td>
      </tr>)}
    </tbody></table></div> : <div className="empty-state compact"><strong>本轮尚无逐对象检查结果</strong><p>尚不能据此认定资源健康。</p></div>}
    <p className="data-source-note">数据来源：模拟巡检数据</p>
  </section>
}
