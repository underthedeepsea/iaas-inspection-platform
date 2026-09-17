import { useQuery } from '@tanstack/react-query'
import { Drawer, Input, Select } from 'antd'
import { useMemo, useState } from 'react'
import { getRules, type RuleDefinition } from '../../api/codePlugins'

export function CodePluginsPage() {
  const query = useQuery({queryKey:['rules'],queryFn:getRules})
  const [search, setSearch] = useState('')
  const [resourceType, setResourceType] = useState('ALL')
  const [selected, setSelected] = useState<RuleDefinition | null>(null)
  const rules = useMemo(() => (query.data?.items ?? []).filter(rule => {
    const term = search.trim().toLowerCase()
    const matchesSearch = !term || `${rule.rule_code} ${rule.name} ${rule.plugin_id} ${rule.description}`.toLowerCase().includes(term)
    return matchesSearch && (resourceType === 'ALL' || rule.resource_types.includes(resourceType))
  }), [query.data?.items, resourceType, search])
  return <section className="view" aria-labelledby="rules-title"><div className="page-heading"><div><span className="eyebrow">CODE RULE LIBRARY</span><h2 id="rules-title">规则库</h2><p className="lede">只读查看规则、插件、操作、参数和版本；巡检结论由这些 CODE 规则产生。</p></div><span className="plugin-total">{query.data?.items.length ?? '—'} 条确定性规则</span></div>
    <div className="plugin-intro"><span className="analysis-source-code source-badge">CODE</span><p>规则产生 PASS / FAIL / UNKNOWN 等检查结论。AI 仅在巡检完成后按需解释。</p></div>
    <div className="rule-library-filters"><Input aria-label="搜索规则" allowClear onChange={event => setSearch(event.target.value)} placeholder="搜索 rule_code、名称或插件" value={search} /><Select aria-label="按资源类型筛选" onChange={setResourceType} options={[{label:'全部资源',value:'ALL'},{label:'控制面',value:'CONTROL_PLANE'},{label:'LLM 运行时',value:'LLM_RUNTIME'}]} value={resourceType} /></div>
    {query.isLoading ? <div className="empty-state" role="status">正在加载规则库…</div> : query.isError ? <div className="empty-state" role="alert"><strong>规则库加载失败</strong><button className="button button-secondary" onClick={() => void query.refetch()}>重试</button></div> : <div className="plugin-library">{rules.map((rule, index) => <article className="plugin-card" id={rule.plugin_id} key={rule.rule_code}>
      <div className="plugin-card-index mono">{String(index + 1).padStart(2,'0')}</div><div className="plugin-card-main"><div className="plugin-card-heading"><h3>{rule.name}</h3><span className="plugin-version mono">v{rule.rule_version}</span><span className="plugin-active">{rule.status}</span></div><p>{rule.description}</p><div className="plugin-identifiers"><span className="mono">{rule.plugin_id}</span><code>{rule.rule_code}</code></div><button className="text-link" onClick={() => setSelected(rule)} type="button">查看规则详情 →</button></div><dl className="plugin-card-details"><div><dt>适用资源</dt><dd>{rule.resource_types.map(resourceLabel).join(' / ')}</dd></div><div><dt>Operation</dt><dd className="mono">{rule.operation_key}</dd></div><div><dt>插件版本</dt><dd className="mono">v{rule.plugin_version}</dd></div></dl>
    </article>)}{rules.length === 0 ? <div className="empty-state compact">没有匹配的规则。</div> : null}</div>}
    <p className="data-source-note">规则与插件版本会冻结在每次巡检结果中；本页不提供编辑、发布、Shadow 或 Dry Run。</p>
    <Drawer onClose={() => setSelected(null)} open={Boolean(selected)} title={selected?.name ?? '规则详情'}>
      {selected ? <div className="rule-detail"><dl className="definition-list"><div><dt>rule_code</dt><dd className="mono">{selected.rule_code}</dd></div><div><dt>规则版本</dt><dd>v{selected.rule_version}</dd></div><div><dt>plugin</dt><dd className="mono">{selected.plugin_id} · v{selected.plugin_version}</dd></div><div><dt>operation</dt><dd className="mono">{selected.operation_key}</dd></div><div><dt>资源类型</dt><dd>{selected.resource_types.map(resourceLabel).join(' / ')}</dd></div><div><dt>状态</dt><dd>{selected.status}</dd></div></dl><h4>参数</h4><pre className="evidence-json">{JSON.stringify(selected.parameters, null, 2)}</pre><h4>说明</h4><p>{selected.description}</p></div> : null}
    </Drawer>
  </section>
}

function resourceLabel(code: string) {
  return code === 'CONTROL_PLANE' ? '控制面' : code === 'LLM_RUNTIME' ? 'LLM 运行时' : code
}
