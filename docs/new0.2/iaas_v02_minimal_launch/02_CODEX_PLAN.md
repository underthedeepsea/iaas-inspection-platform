# v0.2 Minimal Launch Implementation Plan

> 本文替代上一版大计划。只执行这里的内容，不得自动恢复延期功能。

## Global Constraints

- 保留 React / Django / PostgreSQL / CheckResult / Finding / Risk / Evidence / Model Gateway。
- CODE 决定状态，AI 只解释。
- 每个 Task 一个 commit。
- 先写失败测试再实现。
- 开发前重新 fetch 实际 HEAD。
- 不 reset / 不覆盖用户新提交。
- 不新增报告系统、动态插件平台、多 Agent、新队列。

---

# Phase 0：正确性修复

## 0.1 健康度变化口径

修改 Dashboard：

```text
yesterday_diff.new_count
```

不得作为 health delta。

没有同口径健康度变化时显示：

```text
资源类型平均值
```

或：

```text
不可比较
```

Commit:

```text
fix: stop using risk delta as health delta
```

## 0.2 反亲和分组

测试：

```text
同组同 Host → FAIL
同组不同 Host → PASS
不同组共享 Host → 不互相影响
缺关键映射 → UNKNOWN
```

不要引入通用策略 DSL。

Commit:

```text
fix: scope anti affinity by replica group
```

## 0.3 Queue 语义

维持现算法时，规则命名和说明必须改成：

```text
最近 N 点连续超限
```

测试：

```text
最后3点超限 → FAIL
中间有未超限 → PASS
不足3点 → UNKNOWN
```

Commit:

```text
fix: align queue rule semantics with evidence
```

## 0.4 单资产错误隔离

要求：

```text
A 合法 → 正常 PASS/FAIL
B 坏样本 → ERROR/UNKNOWN
```

B 不能覆盖 A。

Commit:

```text
fix: isolate per asset inspection errors
```

## 0.5 Coverage / Conclusive Rate

保留旧 coverage 字段含义：

```text
execution coverage = 有 CheckResult 的资产 / 目标资产
```

新增：

```text
conclusive rate = 有 PASS/FAIL 的 applicable 资产 / applicable 资产
```

Commit:

```text
fix: separate execution coverage from conclusive rate
```

---

# Phase 1：本次巡检闭环

## 1.1 Run Result API

新增：

```text
GET /api/v1/inspection-runs/{run_id}/result
```

返回：

```text
run
scope
summary
check_results
risks
```

必须严格绑定 run_id 和 environment_id。

Commit:

```text
feat: add aggregate inspection run result api
```

## 1.2 Run Result Page

新增：

```text
/inspection-runs/:runId
```

展示：

```text
Run ID
状态
环境
资源类型
时间
PASS/FAIL/UNKNOWN/ERROR
风险
检查结果
CODE 来源
AI 入口
```

异常排序：

```text
ERROR → FAIL → UNKNOWN → PASS → NOT_APPLICABLE
```

Commit:

```text
feat: add exact inspection run result page
```

## 1.3 完成 CTA

完成后：

```text
[查看本次巡检结果 →]
[关闭]
```

失败：

```text
[查看失败详情 →]
```

Commit:

```text
feat: guide users to completed inspection results
```

## 1.4 真 reload 恢复

sessionStorage 只保存：

```text
environment_id
run_id
resource_types
```

运行状态仍从服务端读取。

Playwright 必测：

```text
Start Run
→ reload
→ same Run ID
→ trigger POST 次数仍为 1
```

Commit:

```text
fix: preserve active inspection identity across reloads
```

---

# Phase 2：CODE / AI 来源

## 2.1 最小静态 RuleDefinition

新增静态定义：

```python
RuleDefinition(
    rule_code,
    name,
    rule_version,
    plugin_id,
    plugin_version,
    operation_key,
    resource_types,
    handler,
)
```

只覆盖当前三条规则。

保留兼容：

```python
get_rule(code)
```

Commit:

```text
feat: describe launch rules with plugin provenance
```

## 2.2 冻结执行来源

每次执行保存：

```json
{
  "source_type": "CODE",
  "rule_code": "...",
  "rule_version": "...",
  "plugin_id": "...",
  "plugin_version": "...",
  "operation_key": "..."
}
```

旧历史没有则显示：

```text
未记录
```

禁止回填当前版本。

Commit:

```text
feat: freeze deterministic rule provenance
```

## 2.3 前端来源标识

CheckResult：

```text
[CODE]
规则名
plugin · version
```

AI：

```text
[AI 解释]
AI 不参与 PASS / FAIL 判定
```

Commit:

```text
feat: show code and ai provenance
```

---

# Phase 3：只读规则库

## 3.1 API

新增：

```text
GET /api/v1/rules
GET /api/v1/rules/{rule_code}
```

只读。

不提供 POST / PUT / PATCH / DELETE。

Commit:

```text
feat: expose read only rule catalog
```

## 3.2 UI

新增：

```text
/rules
```

功能仅：

```text
搜索
ResourceType 筛选
规则列表
详情 Drawer
```

不做编辑、发布、Shadow、Dry Run。

Commit:

```text
feat: add read only rule library ui
```

---

# Phase 4：首页最小 AI

## 4.1 API

新增：

```text
POST /api/v1/dashboard/ask
```

Request：

```json
{
  "environment_id": "...",
  "inspection_run_id": "...",
  "question": "为什么本次 TTFT 异常？"
}
```

限制：

```text
one-shot
no tools
no writes
timeout <= 30s
```

Context 只含：

```text
CheckResult
Risk
Evidence
本 Run 摘要
```

Commit:

```text
feat: add run scoped dashboard ai explanation
```

## 4.2 首页输入框

放在标题与 KPI 之间。

显示：

```text
当前上下文：RUN-xxxx
```

Quick prompts：

```text
本次巡检发现了什么？
哪些是 CODE 发现的？
为什么 TTFT 异常？
```

无明确 Run：

```text
请先完成或选择一次巡检
```

Commit:

```text
feat: add minimal ai assistant to dashboard
```

---

# Phase 5：E2E + Release Gate

必须覆盖：

1. CONTROL_PLANE → 本次 Run → CODE 反亲和结果；
2. LLM_RUNTIME → TTFT / Queue → CODE 来源；
3. 启动 Run → reload → 同一个 Run；
4. 首页问 AI → 引用 CODE CheckResult；
5. AI Provider 故障 → 巡检结果仍正常。

Backend：

```bash
DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.dev python manage.py makemigrations --check
DJANGO_SETTINGS_MODULE=config.settings.dev python -m pytest -q
```

Frontend：

```bash
cd frontend
npm ci
npm test
npm run build
npm run e2e:real
```

GitHub：

```text
core = success
e2e = success
```

---

# Stop Conditions

出现任何一项立即停止扩张：

- 为三条规则重新建设动态插件平台；
- 首页 AI 需要多 Agent；
- 规则库出现编辑/发布需求；
- 开始设计报告服务；
- 开始设计 Run Comparison / Rule Dry Run；
- 引入 Redis / Celery / MQ；
- 为演示硬编码业务最终答案。

满足本计划后，v0.2 停止加功能，进入上线候选。
