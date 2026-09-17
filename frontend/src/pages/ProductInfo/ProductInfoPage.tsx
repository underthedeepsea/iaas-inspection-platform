import { useEffect, useState } from 'react'

import { displayDataMode, getProductInfo, type ProductInfo } from '../../api/product'

const sections = [
  ['problem', '这个系统解决什么问题', '内部可用 MVP：针对明确资源执行明确规则，记录可信、可解释、可追踪的巡检事实。首期正式支持 CONTROL_PLANE 与 LLM_RUNTIME。'],
  ['daily', '每日巡检如何工作', 'Airflow 通过内部 HTTP 编排每日批处理。手动巡检使用相同的规则、风险关联、复验和快照流程。'],
  ['division', '为什么不是所有问题都交给 LLM', '规则决定 PASS、FAIL、UNKNOWN、ERROR 或 NOT_APPLICABLE。AI 不决定检查状态，不直接生成风险。'],
  ['code-ai', 'Code / AI 如何分工', '代码插件完成检查后，进入本次巡检结果页查看结论与版本。需要解释时，可在首页或结果页提问，AI 仅使用当前巡检的检查和风险证据。模型不可用不影响巡检结果。'],
  ['coverage', '覆盖率与证据可信度', '覆盖率是已产生 CheckResult 的资产数除以冻结范围中的目标资产数。UNKNOWN 表示证据不足；没有 PASS 或 FAIL 时不显示健康分数。'],
  ['reverify', '为什么“已处理”后还要自动复验', '已处理将风险置为待复验。下一轮同资产同规则明确 PASS 才能恢复，UNKNOWN 不能证明恢复。'],
  ['data', '当前数据源与运行时', '数据来源：模拟巡检数据。当前为模拟巡检阈值：TTFT P95 180ms，最少 3 个样本；队列最后连续 3 点超过 10 才失败。并未完成真实生产基础设施接入。'],
  ['future', '后续阶段', '真实 Prometheus、Kubernetes、CMDB 接入以及其他资源类型留待下一阶段。动态插件、经验生成、Shadow、自进化和复杂多轮 Agent 已延期。'],
] as const

const glossary = [
  ['Finding', '一次巡检执行观察到的具体异常。'],
  ['Risk', '跨运行稳定关联后的风险对象，有自己的生命周期。'],
  ['Evidence', '支持 Finding、Risk 或调查结论的结构化证据。'],
  ['Code Plugin', '具有稳定 ID、版本与适用资源类型的确定性检查规则。'],
  ['CheckResult', '代码插件对单个资源对象产生的判定与证据，AI 不会改写。'],
  ['Inspection Run', '一次巡检的冻结范围、执行过程与检查结果。'],
] as const

export function ProductInfoPage() {
  const [productInfo, setProductInfo] = useState<ProductInfo | null>(null)

  useEffect(() => {
    let active = true
    void getProductInfo().then((value) => {
      if (active) setProductInfo(value)
    }).catch(() => {
      // Product copy remains usable when the optional metadata endpoint is unavailable.
    })
    return () => { active = false }
  }, [])

  return (
    <section aria-labelledby="product-info-title" className="view product-info-page">
      <div className="product-info-content">
        <section className="about-hero">
          <span className="eyebrow">PRODUCT NOTE · CONTROL PLANE v0.2</span>
          <h1 id="product-info-title">让巡检结果<br /><em>可信、可追踪、可解释。</em></h1>
          <p>这是给基础设施团队使用的 IaaS 智能巡检控制面：先用确定性的代码快速发现问题，再按需让 AI 解释现有证据。</p>
          <div className="about-meta"><span>数据源：{displayDataMode(productInfo?.data_mode)}</span><span>Provider：{productInfo?.llm_provider ?? '读取中…'}</span><span>安全模式：{productInfo?.security_mode ?? 'READ_ONLY_TOOLS'}</span></div>
        </section>
        <div className="about-layout">
          <nav aria-label="产品说明目录" className="about-index">
            {sections.map(([id, title], index) => <a href={`#${id}`} key={id}>{String(index + 1).padStart(2, '0')} · {title}</a>)}
            <a href="#security">09 · 安全边界：只读解释</a>
            <a href="#terms">10 · 术语解释</a>
          </nav>
          <div className="about-sections">
            {sections.map(([id, title, body], index) => <section className="about-section" id={id} key={id}><span className="section-number">{String(index + 1).padStart(2, '0')}</span><h2>{title}</h2><p>{body}</p></section>)}
            <section className="about-section about-section-security" id="security"><span className="section-number">09</span><h2>安全边界：只读解释</h2><p>首期 AI 单轮解释已有证据，不执行工具调用和运维写操作。证据不足时标记 UNRESOLVED，模型调用超时上限为 30 秒。</p></section>
            <section className="about-section" id="terms"><span className="section-number">10</span><h2>术语解释</h2><dl className="glossary">{glossary.map(([term, meaning]) => <div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>)}</dl></section>
          </div>
        </div>
      </div>
    </section>
  )
}
