# v0.2 最小范围

## 产品目标

> 把一次巡检做完整：结果正确 → 找到刚刚那次巡检 → 看懂 CODE 与 AI → 能查询规则 → 能直接问 AI。

## 必做 A：正确性

- 健康度变化不能用风险 `new_count` 冒充。
- 反亲和规则必须按明确副本组/集群边界判断。
- Queue 规则如果没有时间连续性，只描述为“最近 N 点连续超限”。
- 单资产坏数据不能把整项所有资产变成 ERROR。
- Execution Coverage 与 Conclusive Rate 分开。
- UNKNOWN / ERROR / NOT_APPLICABLE 单独统计。

## 必做 B：本次巡检闭环

完成后主 CTA：

```text
查看本次巡检结果 →
```

统一页面：

```text
/inspection-runs/:runId
```

显示 Run ID、环境、资源范围、时间、五态结果、风险、CODE 来源和 AI 解释入口。

真正浏览器刷新后必须恢复同一 Run，且不能重复触发任务。

## 必做 C：CODE / AI

确定性结果：

```text
[CODE]
Rule
Plugin
Version
```

AI：

```text
[AI 解释]
只解释 CODE 结果，不参与 PASS / FAIL 判定。
```

## 必做 D：只读规则库

新增：

```text
/rules
```

显示：

- rule_code
- 名称
- plugin
- operation
- version
- resource type
- 参数
- 状态
- 描述

不允许编辑、发布、Shadow、Dry Run。

## 必做 E：首页最小 AI

一个输入框即可：

```text
AI 巡检助手
当前上下文：RUN-xxxx

[为什么这次 TTFT 异常？] [发送]
```

要求：

- 单轮；
- 绑定明确 Run；
- 只读；
- 引用 CheckResult / Risk / Evidence；
- AI 故障不影响巡检结果。
