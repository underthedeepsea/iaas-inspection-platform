# 匿名化与未完成代码清理实施计划 · 2026-09-17

## 目标

将项目改为单租户、匿名直达：删除所有人类账号登录、session、角色、owner 和 actor 校验；保留内部 Airflow / mock 服务令牌。删除有明确证据的占位页面、零引用组件和 React 前旧页面壳，同时保持 v0.2 巡检闭环、静态规则库和单轮 AI 正常。

存量数据可全部舍弃。本次只保证 fresh database 正常迁移，不提供旧库原地升级兼容。

## 不可变边界

- CODE 决定 PASS / FAIL，AI 只读解释。
- 保留当前 dirty / untracked 的 v0.2 完成成果，不 reset、stash、clean 或从 HEAD 覆盖。
- 保留 `AIRFLOW_INTERNAL_TOKEN`、mock internal token、Provider token 和脱敏逻辑。
- `sessionStorage` 的 Run 恢复状态、消息 role、Capability binding role 不是登录鉴权，不删除。
- 环境绑定、对象关系、状态机、事务、幂等和输入验证保持不变。

## 实施范围

### 1. 数据模型与 Django 基础设施

- 从 `INSTALLED_APPS` 移除 auth、contenttypes、sessions，移除 Session/Auth middleware。
- 删除 `Conversation.user`、`HumanFeedback.user`、`AuditEvent.user`、`RiskStatusHistory.actor_user`。
- 直接修正 audits、risks、investigations 的历史 migration state，删除 auth dependency；只支持空库迁移。
- 不创建匿名用户、system user 或兼容账号。

### 2. 后端公开边界

- 删除 `apps/api/auth.py` 和 `/auth/login|me|logout`。
- 所有 public API decorator 仅检查 HTTP method，不检查 session、group、role 或 owner。
- 删除 `request.user`、actor/actor_user 必填与 owner scope；对象仍按主键、环境和上下文关系约束。
- 未知 public API 匿名返回普通 404。
- internal batch/mock token 行为保持原样。

### 3. 前端匿名直达

- 删除 Login、AuthGuard、session API 和账号 UI。
- `MainLayout` 直接作为根 layout。
- Playwright 不再自动登录或提供用户名密码。

### 4. 已证实未完成或死亡代码

- 删除 SectionOverview 中 history、pending、capabilities、experiences、evolution、settings 占位页及路由；删除未挂载的旧 RiskCenter。
- 将真实调用 product-info 的 AI Runtime 抽为独立正式页面保留。
- 删除旧 Django 页面壳 `templates/app.html`、`templates/product_about.html`、`static/js/*`、`static/css/app.css`。
- 再次确认零引用后删除 `AIConversation` 组件、测试和 `createConversationTurn` helper。

### 5. 测试与文档

- 删除 session API 测试；其余测试改为匿名单租户语义。
- 删除 401/403、role、owner 隔离断言，改为 method、validation、not-found、状态机与成功契约。
- 新增 auth 三端点普通 404、未知 API 404、内部 token 仍强制的回归测试。
- 更新 E2E、CI、seed 和 release 文档。

## 验收条件

- `/`、`/resources`、`/risks`、`/rules`、`/inspection-runs/:id` 匿名直达且无 `/auth/**` 请求。
- auth 三端点返回普通 404；删除的占位 URL 返回 404。
- 代码、模型和 migration 中不存在 `AUTH_USER_MODEL`、`request.user`、`force_login` 或 E2E 账号密码。
- `django.contrib.auth/contenttypes/sessions` 未安装。
- 空数据库 migrate 成功；Django check 与 makemigrations check 通过。
- 全量 pytest、Vitest、前端 build、mocked Playwright、real Playwright 和 `git diff --check` 通过。
- 核心 v0.2 Run、规则、风险与 one-shot AI 功能不回归。

## Cost-aware 路由

- 类型：复杂跨模块重构（权限边界、schema、API、前端、测试联动）。
- Development：Sol medium，一次实现尝试。
- Verification：Luna max，只执行和整理测试，不修改实现。
- Code Review：6 low。
- Final Audit：6 low。
- Sol 第一次实现未满足验收即由 6 low 接管当前文档剩余工作，不再返回 Sol。
