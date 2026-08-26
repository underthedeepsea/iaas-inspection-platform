const sections = [
  ['problem', '这个系统解决什么问题', '传统巡检容易陷入两端：规则很多但解释不够，或者把所有问题都交给 LLM，结果慢、贵且难以审计。本平台把每日巡检、风险生命周期、证据、AI 调查和人工反馈放在同一条可追踪链路里。'],
  ['daily', '每日巡检如何工作', 'Airflow 按日编排模拟数据、巡检项目、风险关联、待复验和 Daily Snapshot。首页先给出今天的总体状态、重点风险、变化和完整性；用户需要时再进入风险详情查看证据和调查过程。'],
  ['division', '为什么不是所有问题都交给 LLM', '已知且可验证的断言适合代码：它快、稳定、成本低，也能在回归测试中复现。LLM 适合处理 Claim Gap、证据路径探索和原因分类等不确定问题。先代码、后 AI，能减少幻觉和无效调用。'],
  ['code-ai', 'Code / AI 如何分工', 'Code 负责确定性检测、阈值、关联和已代码化 Resolver；AI 只补充尚未覆盖的 Claim，并通过只读 Capability 获取允许的证据。每个巡检项目都会显示执行模式、代码状态、覆盖率和 LLM 职责。'],
  ['plugin', '插件化是什么', 'Capability Registry 把巡检能力描述为带版本的插件。插件可以是 RULE、EXEC、REST 或 MCP，并声明输入输出 Schema、超时、只读属性和可解决的 Claim；解析器会优先选择已激活且安全的版本。'],
  ['coverage', '什么叫代码化程度', '代码化程度不是“有没有写脚本”，而是所需 Claims 中有多少已由可验证的代码 Resolver 覆盖。Code Coverage Rate、Deterministic Deflection Rate 和 AI Displacement Rate 分别描述覆盖范围、免进 AI 的比例以及被代码替代的 AI 调查。'],
  ['feedback', '人工反馈如何帮助系统进化', '用户可以对 AI 结论标记有帮助、指出不准确或确认根因。确认后的反馈可以生成 Experience，经过 CODE_PENDING、SHADOW 和质量门槛后，才会形成 CODE_ACTIVE Capability；反馈不会绕过验证直接改变线上行为。'],
  ['reverify', '为什么“已处理”后还要自动复验', '“记录已处理”只代表人已经执行了动作，不代表问题已经消失。系统会把风险置为 PENDING_REVERIFY，下一轮巡检重新观察；Finding 消失才进入 RECOVERED，仍存在则保持或升级风险。'],
  ['mock', '当前 Demo 使用模拟数据', '第一阶段使用固定 seed 生成可重复的正常、异常、趋势和冲突 Case，不连接真实 Prometheus、Kubernetes、CMDB、日志或 ITSM。这样可以稳定演示巡检、调查、Replay 和 Shadow 流程。'],
  ['ollama', 'LLM 本地开发使用 Ollama', '本地默认 Provider 是 Ollama，模型名称和地址来自环境配置。Django、LangGraph 和 LangChain 在 Web Runtime 中运行，Airflow 使用独立环境通过内部 API 编排，避免依赖冲突。'],
] as const

const glossary = [
  ['Finding', '一次巡检执行观察到的具体异常。'],
  ['Risk', '跨运行稳定关联后的风险对象，有自己的生命周期。'],
  ['Evidence', '支持 Finding、Risk 或调查结论的结构化证据。'],
  ['Claim Gap', '当前代码和已有证据无法回答的判断缺口。'],
  ['Capability', '注册在平台中的可审计巡检能力。'],
  ['Shadow', '新能力只观察、不影响正式结论的验证阶段。'],
  ['AI Displacement Rate', '已被稳定代码能力替代的 AI 调查比例。'],
] as const

export function ProductInfoPage() {
  return (
    <section aria-labelledby="product-info-title" className="view product-info-page">
      <div className="product-info-content">
        <section className="about-hero">
          <span className="eyebrow">PRODUCT NOTE · DEMO V4.1</span>
          <h1 id="product-info-title">让巡检结果<br /><em>可解释、可复验、会进化。</em></h1>
          <p>这是给基础设施团队使用的 IaaS 智能巡检控制面：先用确定性的代码快速发现问题，再让 AI 在证据缺口处补充调查。</p>
          <div className="about-meta"><span>数据源：MOCK</span><span>Provider：Ollama</span><span>安全模式：只读 Tool Calling</span></div>
        </section>
        <div className="about-layout">
          <nav aria-label="产品说明目录" className="about-index">
            {sections.map(([id, title], index) => <a href={`#${id}`} key={id}>{String(index + 1).padStart(2, '0')} · {title}</a>)}
            <a href="#security">11 · 安全边界：只读 Tool Calling</a>
            <a href="#terms">12 · 术语解释</a>
          </nav>
          <div className="about-sections">
            {sections.map(([id, title, body], index) => <section className="about-section" id={id} key={id}><span className="section-number">{String(index + 1).padStart(2, '0')}</span><h2>{title}</h2><p>{body}</p></section>)}
            <section className="about-section about-section-security" id="security"><span className="section-number">11</span><h2>安全边界：只读 Tool Calling</h2><p>LLM 只能调用 <code>read_only=true</code> 的 Capability。Tool 参数必须通过 JSON Schema，EXEC 只能使用白名单目录，REST 仅允许注册的内部地址；有超时和调查轮次上限，禁止任意 shell、重启、迁移、写配置、扩缩容和删除。</p></section>
            <section className="about-section" id="terms"><span className="section-number">12</span><h2>术语解释</h2><dl className="glossary">{glossary.map(([term, meaning]) => <div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>)}</dl></section>
          </div>
        </div>
      </div>
    </section>
  )
}
