import { useEffect, useState } from 'react'

import { displayDataMode, getProductInfo, type ProductInfo } from '../../api/product'

export function AiRuntimePage() {
  const [productInfo, setProductInfo] = useState<ProductInfo | null>(null)

  useEffect(() => {
    let active = true
    void getProductInfo().then((value) => {
      if (active) setProductInfo(value)
    }).catch(() => {
      // Keep the documented runtime boundary visible when metadata is unavailable.
    })
    return () => { active = false }
  }, [])

  return (
    <section aria-labelledby="ai-runtime-title" className="view">
      <div className="page-heading">
        <div><span className="eyebrow">MODEL GATEWAY</span><h2 id="ai-runtime-title">AI 运行情况</h2><p className="lede">AI 只解释 CODE 结果，不参与确定性判定。</p></div>
      </div>
      <div className="runtime-grid">
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">PROVIDER</span><h3>当前运行时</h3></div></div><dl className="definition-list"><div><dt>Provider</dt><dd>{productInfo?.llm_provider ?? '读取中…'}</dd></div><div><dt>安全模式</dt><dd>{productInfo?.security_mode ?? 'READ_ONLY_TOOLS'}</dd></div><div><dt>数据源</dt><dd>{displayDataMode(productInfo?.data_mode)}</dd></div></dl></section>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">BOUNDARIES</span><h3>解释边界</h3></div></div><div className="budget-list"><div><span>交互方式</span><strong>单轮</strong></div><div><span>Tool Call</span><strong>0</strong></div><div><span>写操作</span><strong>禁止</strong></div></div></section>
      </div>
      <section className="panel runtime-note"><div className="section-heading"><div><span className="eyebrow">OBSERVABILITY</span><h3>运行说明</h3></div></div><p className="body-copy">首页和本次巡检结果页会把问题绑定到明确的 Run，并引用 CheckResult、Risk 和 Evidence。</p><p className="body-copy runtime-boundary">模型不可修改检查结论或直接创建风险。</p></section>
    </section>
  )
}
