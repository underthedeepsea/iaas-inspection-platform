# IaaS 智能巡检 v0.2 最小上线包

当前版本只做 5 件事：

1. 修正结果正确性；
2. 完成“本次巡检”闭环；
3. 明确 CODE / AI 来源；
4. 增加只读规则库；
5. 首页增加最小 AI 输入框。

开发顺序：

```text
Phase 0 正确性修复
  ↓
Phase 1 本次巡检闭环
  ↓
Phase 2 CODE / AI 来源
  ↓
Phase 3 只读规则库
  ↓
Phase 4 首页最小 AI
  ↓
Phase 5 E2E + Release Gate
```

本版本明确不做：

- 巡检报告导出
- LLM 对话式报告
- 报告选择卡片
- O1 真实快照导入
- O2 Run Comparison
- O3 Rule Dry Run
- 动态 Capability / Plugin 平台
- 规则编辑、发布、Shadow
- Experience-to-Code
- 多 Agent
- 多轮复杂 AI
- 新 Redis / Celery / MQ
