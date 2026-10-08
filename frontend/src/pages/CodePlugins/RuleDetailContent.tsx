import type { RuleDefinition, RulePolicyProfile } from '../../api/codePlugins'
import './RuleDetailContent.css'

export function RuleDetailContent({ rule }: { rule: RuleDefinition }) {
  const metrics = rule.supported_metrics ?? []
  const judgments = rule.judgment_rules ?? []
  const profiles = rule.policy_profiles ?? []
  const metricNames = new Map(metrics.map(metric => [metric.field, metric.name]))

  return <div className="rule-detail">
    <dl className="definition-list">
      <div><dt>rule_code</dt><dd className="mono">{rule.rule_code}</dd></div>
      <div><dt>规则版本</dt><dd>v{rule.rule_version}</dd></div>
      <div><dt>plugin</dt><dd className="mono">{rule.plugin_id} · v{rule.plugin_version}</dd></div>
      <div><dt>operation</dt><dd className="mono">{rule.operation_key}</dd></div>
      <div><dt>资源类型</dt><dd>{rule.resource_types.map(resourceLabel).join(' / ')}</dd></div>
      <div><dt>状态</dt><dd>{rule.status}</dd></div>
    </dl>
    <section aria-label="数据输入">
      <h4>数据输入</h4>
      {rule.input_source ? <p>输入源：<code>{rule.input_source}</code></p> : null}
      <p>{rule.input_contract || '当前接口未提供数据输入契约，请结合采集接入文档核实输入来源。'}</p>
    </section>
    <section aria-label="支持采集的指标">
      <h4>支持采集的指标{metrics.length ? `（${metrics.length} 项）` : ''}</h4>
      {metrics.length ? <div className="rule-detail-table-scroll" role="region" aria-label="支持采集的指标表" tabIndex={0}>
        <table className="rule-detail-table rule-detail-metrics">
          <caption>指标字段、输入路径及用途</caption>
          <thead><tr><th scope="col">指标 / 字段</th><th scope="col">单位 / 有效范围</th><th scope="col">判定用途</th></tr></thead>
          <tbody>{metrics.map(metric => <tr key={metric.field}>
            <th scope="row"><span>{metric.name}</span><code>{metric.field}</code><small>输入路径：<code>{metric.input_path}</code></small></th>
            <td>{metric.unit}<small>{metric.range}</small></td><td>{metric.purpose}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p className="rule-detail-unavailable" role="status">当前接口未提供具体指标清单，不能据此确认采集覆盖完整。</p>}
    </section>
    <section aria-label="具体判定规则">
      <h4>具体判定规则</h4>
      {judgments.length ? judgments.map(section => <div className="rule-judgment-section" key={section.title}>
        <h5>{section.title}</h5><ul>{section.items.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </div>) : <p className="rule-detail-unavailable" role="status">当前接口未提供具体判定条件和正常边界；参数为空或规则启用均不能证明资源正常。</p>}
    </section>
    {profiles.length ? <section aria-label="当前阈值与策略覆盖">
      <h4>当前阈值与策略覆盖</h4>
      <p>以下为当前服务配置的完整有效策略，已合并继承值。展开引擎或模型策略可查看实际阈值和调参；历史巡检请以该次冻结策略为准。</p>
      {profiles.map(profile => <PolicyProfile key={profile.label} profile={profile} metricNames={metricNames} />)}
    </section> : null}
    <section aria-label="规则参数"><h4>参数</h4><pre className="evidence-json">{JSON.stringify(rule.parameters, null, 2)}</pre></section>
    <section aria-label="规则说明"><h4>说明</h4><p>{rule.description}</p></section>
  </div>
}

function PolicyProfile({ profile, metricNames }: { profile: RulePolicyProfile; metricNames: Map<string, string> }) {
  const { dynamic, trend, persistence, quality } = profile.policy
  const tuning = [
    ['固定异常连续确认', `${persistence.consecutive_hits} 个窗口`],
    ['动态 WARNING 边界参数', `相对变化 ${percent(dynamic.warning_change_ratio)}；Z = ${dynamic.warning_z}`],
    ['动态 CRITICAL 边界参数', `相对变化 ${percent(dynamic.critical_change_ratio)}；Z = ${dynamic.critical_z}`],
    ['趋势窗口', `${trend.window_minutes} 分钟`],
    ['趋势 WATCH / DEGRADING', `${percent(trend.watch_change_ratio)} / ${percent(trend.degrading_change_ratio)}`],
    ['快照最大年龄', seconds(quality?.max_age_seconds)],
    ['连续窗口最大间隔', seconds(quality?.max_gap_seconds)],
  ]
  const overrides = flattenOverrides(profile.overrides)
  return <details className="rule-policy-profile" open={profile.level === 'DEFAULT'}>
    <summary>{profile.label}</summary>
    <div className="rule-policy-content">
      <p>适用范围：{profile.engine_type || '所有未匹配专属配置的引擎'}{profile.model_name ? ` / ${profile.model_name}` : ' / 未匹配专属模型配置'}。</p>
      <div className="rule-detail-table-scroll" role="region" aria-label={`${profile.label}固定阈值表`} tabIndex={0}>
        <table className="rule-detail-table rule-detail-thresholds">
          <caption>{profile.label} · 完整有效固定阈值</caption>
          <thead><tr><th scope="col">指标</th><th scope="col">单位</th><th scope="col">NORMAL</th><th scope="col">WARNING</th><th scope="col">CRITICAL</th></tr></thead>
          <tbody>{profile.fixed_thresholds.map(row => <tr key={row.field}>
            <th scope="row">{metricNames.get(row.field) || row.field}<code>{row.field}</code></th>
            <td>{row.unit}</td><td>&lt; {row.warning}</td><td>≥ {row.warning} 且 &lt; {row.critical}</td><td>≥ {row.critical}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="rule-policy-confirmation">固定阈值越界仍需满足上方连续确认条件；动态判定、质量与就绪状态请同时核对。</p>
      <dl className="rule-policy-tuning">{tuning.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      {overrides.length ? <div className="rule-policy-overrides"><h5>本层覆盖值</h5><ul>{overrides.map(([field, value]) => <li key={field}><code>{field}</code> = {value}</li>)}</ul></div>
        : <p className="rule-policy-confirmation">{profile.level === 'DEFAULT' ? '默认策略提供基础值，无上层覆盖。' : '本层未覆盖参数，沿用父级策略的全部值。'}</p>}
    </div>
  </details>
}

function flattenOverrides(value: Record<string, unknown>, prefix = ''): [string, string][] {
  return Object.entries(value).flatMap(([key, child]) => {
    const field = prefix ? `${prefix}.${key}` : key
    return child !== null && typeof child === 'object' && !Array.isArray(child)
      ? flattenOverrides(child as Record<string, unknown>, field)
      : [[field, String(child)]] as [string, string][]
  })
}

function percent(value: number) { return `${Number((value * 100).toFixed(4))}%` }
function seconds(value?: number) { return value === undefined ? '服务默认值（见具体判定规则）' : `${value} 秒` }
export function resourceLabel(code: string) {
  return code === 'CONTROL_PLANE' ? '控制面' : code === 'LLM_RUNTIME' ? 'LLM 运行时' : code
}
