import type { CheckResult } from '../../api/resources'

export function CheckResultsTable({ results = [] }: { results?: CheckResult[] }) {
  return <section className="panel" aria-label="本轮检查">
    <h3>本轮检查</h3><p>数据来源：模拟巡检数据</p>
    {results.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>检查</th><th>资产</th><th>结果</th><th>观测值</th><th>期望值</th><th>证据与时间</th></tr></thead><tbody>
      {results.map(result => <tr key={result.id}>
        <td>{result.inspection_item_name}<small style={{display:'block'}}>{result.inspection_item_code}</small></td><td>{result.asset_name}</td>
        <td><strong>{result.status}</strong>{result.status === 'UNKNOWN' ? <small> · 证据不足</small> : null}</td>
        <td>{JSON.stringify(result.observed_value)}</td><td>{JSON.stringify(result.expected_value)}</td>
        <td><details><summary>展开证据</summary><p>{result.summary}</p><p>Asset：{result.asset_id}</p><time>{result.checked_at}</time><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(result.evidence,null,2)}</pre></details></td>
      </tr>)}
    </tbody></table></div> : <p>本轮尚无逐对象检查结果，不能据此认定资源健康。</p>}
  </section>
}
