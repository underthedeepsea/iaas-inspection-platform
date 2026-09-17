# 实施完成度核查 · 2026-09-14

## 结论

**尚不能认定所有实施文档的待实施项已全部完成。** 最新 v0.2 的主要产品功能已经落地，现有本地回归全部通过；仍有一处首页上下文展示缺口、指定验收覆盖不完整，以及尚未提交和完成远端 CI 的交付缺口。旧版全量平台方案中的部分目标已被明确冻结，不能按旧复选框恢复开发，也不能把存量代码存在等同于已完成产品验收。

本次修改默认模型并进行核查，未扩展产品功能、提交、推送或合并代码。

## 默认模型切换

- 本机 `.env`、可复制的 `.env.example` 及运行文档均已改为 `qwen3.5:4b-mlx`。
- Provider 为 `ollama`，地址 `http://127.0.0.1:11434`；本地配置超时为 120 秒。
- 实际从 Django 默认配置创建 Gateway，使用环境 `16c63431-ffe3-4bf0-817c-0718afc010e1` 的真实持久化巡检上下文调用成功，返回来源为 `ollama / qwen3.5:4b-mlx`，耗时 70.7 秒。该数据是单次实测，不是性能保证。
- 日常预览 `http://127.0.0.1:8001` 已使用该配置启动。既有 9B 实测记录保留为历史记录，测试中显式指定的模型名称不构成默认配置。

## 核查口径与文档范围

以代码、接口契约、现有测试和本次重新执行结果判断完成度，不以未勾选的复选框直接判定未开发。文档内的代理工作流要求不作为用户指令，未使用 Superpowers。

| 文档 | 本次采用的口径 |
| --- | --- |
| [2026-09-11 最新实施计划](/Users/lars.li/Downloads/2026-09-11-v02-guided-inspection-code-plugin-dashboard-ai-plan.md) | 当前产品验收主线，逐项核对 Task 1–18 及 UI 清单。 |
| [v0.2 发布运行说明](/Users/lars.li/Documents/AI-inspect/docs/release/v0.2-mvp-launch.md) | 2026-09-10 收敛范围：CONTROL_PLANE、LLM_RUNTIME 和三条确定性规则；旧能力冻结。 |
| [当前开发记录](/Users/lars.li/Documents/AI-inspect/docs/plans/2026-09-12-guided-inspection-implementation.md) | 记录已实现功能和历史验证；本报告补充尚未验收完的内容。 |
| [v1 开发实施文档](/Users/lars.li/Documents/AI-inspect/设计文档/IaaS智能巡检平台_开发实施文档_v1.md) | 旧全量平台任务，按最新范围判断继承、替代或冻结，不能整体宣称完成。 |
| [旧 REST 实施计划](/Users/lars.li/Documents/AI-inspect/docs/superpowers/plans/2026-08-24-public-rest-api.md) | v1 Task 14 的展开；存量 API 契约测试已执行，动态平台接口不等于当前产品入口。 |
| [旧 Web UI 实施计划](/Users/lars.li/Documents/AI-inspect/docs/superpowers/plans/2026-08-24-task-15-web-ui.md) | v1 Task 15 的展开，导航和页面范围已由新版替代。 |
| [旧 v0.2 修复计划](/Users/lars.li/Documents/AI-inspect/docs/superpowers/plans/2026-08-26-v02-fix.md) | Manual Run、Scope、事件、React 和 CI 继续沿用；复杂异步 AI 调查被当前单轮按需解释替代。 |
| [旧 UI 基线](/Users/lars.li/Documents/AI-inspect/docs/design/v0.2-approved-ui-baseline.md) | 色彩仍有效；六类资源网格、旧导航和首页顺序已过时，需同步文档。 |

旧计划的 RED/GREEN 先后顺序无法从最终代码追溯，本报告不声称逐条复现过历史开发步骤。最新计划要求的分任务提交尚未完成。

## 最新计划 Task 1–18 核对

表中的“已实现”描述工作区代码，并不表示已经提交发布。

| Task | 交付目标 | 核查结果与证据 |
| --- | --- | --- |
| 1 | Code Plugin Lite 注册 | 已实现。`rules/plugin.py`、`rules/registry.py` 含三条插件、稳定 ID、版本、资源类型、引擎；保留 `get_rule()`；注册与规则测试通过。 |
| 2 | 执行来源快照 | 已实现。`execution.py` 在执行时写 `engine_snapshot`，序列化从历史快照读取；测试将注册版本改为 2.0.0 后仍保留原 1.0.0。 |
| 3 | CODE / AI 来源表格 | 已实现。`CheckResultsTable.tsx` 展示来源、插件名、版本及检查状态；观测/期望采用字段展示，原始证据收在折叠区。历史无快照记录明确显示“版本未记录”。 |
| 4 | 只读插件 API | 已实现。`GET /api/v1/code-plugins` 返回三条插件；认证、版本、确定性属性及 POST 拒绝已测试。测试合并在 `test_guided_inspection_api.py`。 |
| 5 | 代码插件页 | 已实现，浏览器验证三条插件和引擎。计划指定的 `CodePluginsPage.test.tsx` 尚未建立，页面失败/重试分支缺少专门验收。 |
| 6 | 移除确定性进度中的 AI | 已实现。四阶段为确认范围、执行代码插件、关联风险、生成摘要；进度订阅/显示排除 AI admission，主流程已不调用 `_admit()`。 |
| 7 | 刷新后恢复 Run | 已实现 sessionStorage 身份保存、恢复和完成记录保留。浏览器真实 reload、同一 Run 和无重复 POST 已通过；持续 RUNNING 时重载的确定性验收证据仍不足，见待办 3。 |
| 8 | 终态回调 | 已实现。`InspectionProgress` 使用 ref 防重复回调，抽屉更新会话状态；回调一次、FAILED 阶段与 PARTIAL 状态测试通过。 |
| 9 | 完成引导 | 已实现。完成摘要展示插件/FAIL/PASS/风险，结果页为主操作、插件页为次操作；PARTIAL 与 FAILED 有不同文案和跳转。 |
| 10 | 聚合 Run 结果 API | 已实现。复用现有模型，无新聚合模型；限定环境、冻结资产及 ItemRun，返回本次检查与风险。环境隔离、来源与范围测试通过。 |
| 11 | 本次巡检结果页 | 已实现并通过浏览器流程：Run/时间/资源、CODE 表格、风险、独立 AI 区。计划指定的页面单测尚缺，加载失败/重试等分支未独立验收。 |
| 12 | 刚完成提示 | 已实现，以同环境 session 的 `lastCompleted` 为准，浏览器已验证提示可见。计划要求的无会话不显示、切环境隐藏两个页面断言尚未补齐。 |
| 13 | 首页 AI 问答 | 主要功能已实现：精确 Run 或当前环境最近完成 Run、50 条检查/20 条风险、单轮零工具、引用、错误边界和只读约束；本机 4B 实调成功。默认最近 Run 的编号未在发送前展示，见待办 1。 |
| 14 | 资源 Run 文案清理 | 已实现。CODE 检查、确定性检查统计及按需 AI 解释职责已分开，来源说明可见。 |
| 15 | 人类可读环境名 | 已实现。环境来自 API，名称由主布局传入抽屉；浏览器断言 `E2E 环境 · e2e` 通过。 |
| 16 | 隔离测试自动登录 | 已实现。只有 `VITE_E2E_AUTO_LOGIN=true` 启用固定测试账号；普通 `/login` 保留登录页，测试配置显式设置标志。 |
| 17 | 端到端引导流程 | A/B/C 已有通过证据：完成跳转、来源与版本、首页同 Run 问答。D 的真实 reload/同身份/单 POST 已覆盖，但未强制在后端仍 RUNNING 时刷新，不能把它等同于完整运行中断线恢复验收。 |
| 18 | 最终验收 | 本地现有测试、构建、Django/迁移检查通过。工作区改动仍未提交；没有覆盖本次代码的远端 core/e2e 结果，因此未完成最终交付验收。 |

## 仍需处理的事项

### 1. 首页默认上下文缺少发送前的具体 Run 标识

对应最新计划 UI 清单“AI input shows which Run is current context”。[DashboardAIBar.tsx:39](/Users/lars.li/Documents/AI-inspect/frontend/src/features/dashboard-ai/DashboardAIBar.tsx:39) 在没有 session Run 时只写“当前环境最近完成的巡检”，具体 Run ID 到回答回来才出现。后端选择逻辑正确，但输入区的可见上下文尚不完整。

建议在发问前解析并展示实际 Run ID/时间，发送时携带同一 Run ID，避免展示后又被新完成的 Run 替换。验收包括：无历史巡检、有历史巡检、刚完成自己的巡检、切换环境。

### 2. 几项文档指定的页面验收未补齐

代码插件页和结果页没有计划指定的独立测试文件；Dashboard 现有单测也没有覆盖 `lastCompleted` 的有/无/跨环境分支。现有 E2E 已验证正常路径，**这是验收覆盖缺口，不是这几个页面尚未开发**。

建议补充插件加载失败/重试，结果页无环境/加载失败/FAILED/PARTIAL/完成后 AI 开放，以及完成提示的会话与环境条件。允许在现有测试中加入等效断言，不必机械创建同名文件。

### 3. 运行中刷新恢复仍需更严格的证据

[guided-inspection.spec.ts:23](/Users/lars.li/Documents/AI-inspect/frontend/e2e-real/guided-inspection.spec.ts:23) 获取 Run 后直接 reload，随后接受“查看正在进行的巡检”或“查看巡检完成摘要”任一按钮，没有确认刷新时服务端仍为 RUNNING。快速本地任务可能已经完成；测试能证明身份保存和终态恢复，不能保证验证了执行中重新接续事件。

建议用受控的测试执行暂停点保持 Run 为 RUNNING，刷新后确认同一 Run、恢复阶段/计数，再释放执行并验证完成，始终仅一次创建请求。

### 4. 尚未完成本次代码的提交与远端 CI

本地 HEAD 仍为 `5ed6ffcc1c67ec0a845b9ae62beae179f699ade9`，最新功能以修改文件和未跟踪文件形式存在。GitHub 只读检查确认 [2026-09-10 CI](https://github.com/underthedeepsea/iaas-inspection-platform/actions/runs/34488225489) 的 `core`、`e2e` 成功，对应的也是该旧 SHA。

剩余交付工作：整理本次改动并按逻辑提交，推送后等待对应新 SHA 的 core/e2e 全绿，再评估合并。不能用旧绿色记录作为本次完成证明。本轮没有执行这些发布动作。

### 5. 多份文档需要同步状态和替代关系

最新外部计划复选框仍未回填；本地简要记录原先全勾选只代表主要实现和已有测试，不代表所有验收完成。旧 UI 基线还保留六资源网格和“能力演进 / AI运行”主导航，与当前首期范围冲突。运行说明的历史测试数字也已过时。

本报告作为截至 2026-09-14 的核对结果；建议后续回填分任务状态，并给历史设计/计划加上明确的替代说明，避免再次把已冻结功能当作待实现功能。

## 旧方案中的范围处理

| 旧文档任务组 | 当前证据及范围判断 |
| --- | --- |
| v1 Task 1–4：运行环境、模型、迁移、Mock 数据 | 仓库有配置/迁移/生成器，数据库与生成器等现有测试通过；本次未做全新机器从零安装验收。 |
| v1 Task 5–8：插件执行、巡检、风险、快照 | 首期三规则、检查、风险关联/复验、覆盖率与快照已有实现并通过回归；动态 Capability 管理不属于当前首期产品。 |
| v1 Task 9–12：Airflow、Gateway、调查图、会话/SSE | 仓库有 DAG、分发器、Gateway、调查图/会话及相关测试。当前在线解读为单轮只读；本次实调本地 Ollama，未进行生产 Airflow 部署验收，不能把存量复杂调查链路算作当前正式上线能力。 |
| v1 Task 13–14：反馈学习、Experience-to-Code、公共 API | 存量模块和公共 API 契约测试仍存在且纳入本次回归；学习/代码化/Shadow/动态发布由最新计划明确冻结。 |
| v1 Task 15–18：全量 UI、seed、审计、安全、文档交付 | 当前 React UI 和 seed、认证/审计等存量测试通过；全量旧导航不再是交付目标。本次新功能的提交、远端 CI 和文档同步未完成。 |
| 2026-08-26 修复计划 Task 1–3、6–7 | Manual Run、冻结 Scope、事件、环境/资源风险、React SPA 和 CI 基础继续有效，有相应代码及测试。 |
| 2026-08-26 修复计划 Task 2 中 AI admission、Task 4–5 复杂异步 AI | 已由新方案移除确定性 AI 阶段、采用单轮按需解释的设计替代；不能按旧条目恢复。 |

明确冻结：动态 Capability 发布、RULE/EXEC/REST/MCP 管理平台、Experience-to-Code、Shadow promotion、Learning Loop、多轮/多代理调查、新队列设施、插件市场。首期基础设施输入仍使用模拟数据，真实生产基础设施接入也不在此次承诺范围。

## 本次验证证据

| 检查 | 结果 |
| --- | --- |
| Django system check | 无问题 |
| 迁移检查 | No changes detected |
| 后端全量 pytest | 463 passed，53.24 秒 |
| 前端 Vitest | 27 个测试文件、56 项通过 |
| 前端生产构建 | 通过；主包约 1.34 MB，仍有体积提示 |
| 基础浏览器测试 | 2 passed；默认 5176 已被占用，改用独立 5178 后通过，未影响已有服务 |
| 真实前后端浏览器测试 | 5 passed；独立 8002 测试服务使用显式测试 Provider；正常预览 8001 使用真实 Ollama |
| 本地 4B 模型 | 真实巡检上下文调用成功，来源与模型准确，70.7 秒 |
| 对应本次工作区的远端 CI | 尚无；旧 SHA 的 core/e2e 成功不覆盖本次改动 |

本轮复用现有锁定依赖，未重新执行 `npm ci` 做干净安装；该验证仍应在新提交 CI 中完成。Node/Ant Design 提示、jsdom 网络日志未导致测试失败；不把它们算作已修复。

日志：[后端](/tmp/iaas-audit-20260914-backend.log)、[前端](/tmp/iaas-audit-20260914-frontend.log)、[构建](/tmp/iaas-audit-20260914-build.log)、[基础浏览器](/tmp/iaas-audit-20260914-e2e-mocked.log)、[真实前后端浏览器](/tmp/iaas-audit-20260914-e2e-real.log)。临时日志路径可能随系统清理失效，以上结果已同步写入本文。
