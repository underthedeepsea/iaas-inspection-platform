# v0.2 最小上线验收

## 正确性
- [ ] health delta 口径正确。
- [ ] anti-affinity 有组边界。
- [ ] queue 文案与算法一致。
- [ ] 单资产错误隔离。
- [ ] execution coverage / conclusive rate 分开。
- [ ] UNKNOWN / ERROR 不等于健康。

## 本次巡检
- [ ] 完成后有“查看本次巡检结果”。
- [ ] 多资源 Run 有统一结果页。
- [ ] Run ID / 时间 / 范围清晰。
- [ ] reload 后仍是同一个 Run。
- [ ] reload 不重复 trigger。

## CODE / AI
- [ ] CheckResult 有 CODE 标识。
- [ ] Rule 可见。
- [ ] Plugin 可见。
- [ ] Version 可见。
- [ ] 历史缺失显示“未记录”。
- [ ] AI 标明“只读解释”。
- [ ] AI 不修改 CheckResult。
- [ ] AI 不直接创建 Risk。

## 规则库
- [ ] `/rules` 可访问。
- [ ] 3 条首期规则可见。
- [ ] 插件与 operation 可见。
- [ ] 参数可见。
- [ ] 没有编辑 / 发布 / Shadow / Dry Run。

## 首页 AI
- [ ] 输入框可见。
- [ ] 明确绑定 Run。
- [ ] 单轮问答。
- [ ] 引用 CheckResult / Risk / Evidence。
- [ ] AI 故障不影响巡检。

## 本版本不得出现
- [ ] 报告导出。
- [ ] LLM 报告。
- [ ] Snapshot Import。
- [ ] Run Comparison。
- [ ] Rule Dry Run。
- [ ] 动态插件市场。
- [ ] 多 Agent。
