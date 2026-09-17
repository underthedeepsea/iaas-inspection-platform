# 鉴权移除与代码清理最终审计 · 2026-09-17

## 结论

PASS。项目已改为单租户、匿名直达；人类账号登录、session、角色、owner、actor 校验及账号 schema 已删除。内部 Airflow / mock 服务令牌、对象关系、状态机、事务、幂等、输入验证和 v0.2 核心闭环均保留。

本次包含开始前已有的 tracked 修改与 untracked 文件，未执行 reset、stash、clean，也未从 HEAD 覆盖用户工作。

## 已完成范围

- 删除 Django auth/contenttypes/sessions app、Session/Auth middleware、账号外键及其 migration dependency。
- 删除 `/api/v1/auth/login|me|logout`、登录页、AuthGuard、session API、账号 UI、E2E 登录凭据与账号 seed。
- 所有公开 API 改为匿名单租户语义；未知 API 与已删除 auth API 返回普通 `404 NOT_FOUND`。
- 保留 `AIRFLOW_INTERNAL_TOKEN`、mock internal token、Provider token、脱敏和内部服务边界。
- 删除 SectionOverview 占位页面与路由、旧 Django 页面壳、零引用 AIConversation 组件及 helper。
- 将有真实数据请求的 AI Runtime 抽为独立正式页面，保留规则、Run、风险和单轮 AI 能力。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 全量后端测试 | 475 passed |
| 前端单元测试 | 25 files / 51 tests passed |
| 前端生产构建 | passed |
| Mocked Playwright | 2 passed |
| Real Playwright | 5 passed，浏览器流程无 auth 请求 |
| Fresh database migrate | passed |
| `manage.py check` | no issues |
| `makemigrations --check --dry-run` | no changes detected |
| `seed_e2e` | passed，无账号创建 |
| Auth/未知 API/占位路由回归 | passed |
| Internal token 回归 | passed |
| `git diff --check` | passed |
| 统一 Code Review | 无 P1/P2 finding |
| Final Audit | PASS |

前端单测仍会打印既有 jsdom XHR `AggregateError` 噪声，Vite 仍提示主 chunk 超过 500 kB；两者均不影响通过结果。首次浏览器验证因本地缺少 Playwright bundled Chromium 失败，改用已安装 Edge 后通过；首次 Django 命令误用系统 Python，改用项目 `.venv-web` 后通过。这些均为环境问题，不是代码回归。

## 数据与部署边界

- 仅支持全新数据库。历史 migration state 已直接移除账号依赖，旧数据库不支持原地升级；存量数据按用户授权可全部舍弃。
- 公开 API 不再提供账号隔离或用户权限控制，只适用于单租户可信网络。内部服务 token 仍是独立强制边界。

## 交付状态

- 未提交、未推送、未部署。
- 工作区原有和本次新增的 dirty/untracked 文件均保留在当前目录。
