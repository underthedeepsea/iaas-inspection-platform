# IaaS 智能巡检平台

> Code-first、AI-on-demand 的自进化 IaaS 巡检平台开发基线。

本项目面向基础设施运维场景，目标是把“发现风险、分析风险、人工反馈、经验沉淀、能力代码化、下一轮自动复验”串成一个可追踪的闭环。

当前仓库是 `v0.1.0` 开发基线，包含产品设计、开发实施约束、Django 运行骨架、依赖清单和基础测试。真实 Prometheus、Kubernetes、CMDB、日志平台以及生产写操作尚未接入。

## 核心思路

- 风险生命周期：发现、持续/加重、定位、处置、下一轮复验、恢复。
- Capability Registry：以 RULE、EXEC、REST、MCP Manifest 管理巡检能力。
- Code-first：成熟场景逐步从 LLM 调查转成确定性代码、规则或插件。
- AI-on-demand：LLM 只在必要时基于当前风险上下文进行只读调查。
- Experience-to-Code：人工反馈沉淀为经验，并经过 `CODE_PENDING`、`SHADOW` 后再激活。

## 技术栈

| 组件 | 基线 |
| --- | --- |
| Web/API | Django 4.2.16、Django REST Framework 3.15.x |
| 在线调查 | LangGraph 1.2.10、LangChain 1.3.14、Ollama |
| 批量编排 | Airflow 2.3.2 |
| 数据库 | PostgreSQL 14.x |
| 运行时 | Python 3.10.x，Web 与 Airflow 两个独立虚拟环境 |
| 数据源 | 第一阶段使用固定 seed 的模拟数据 |

## 当前目录

```text
manage.py                         Django 入口
config/                           Django 最小运行配置
requirements/                     Web、开发和 Airflow 依赖
tests/                            版本约束与 Django 基线检查
设计文档/                         详细设计与开发实施文档
VERSION                           当前版本号（0.1.0）
```

## 本地检查

使用 Python 3.10 创建 Web 环境并安装开发依赖：

```bash
python3.10 -m venv .venv-web
source .venv-web/bin/activate
python -m pip install -r requirements/web-dev.txt
python -m pytest -q
python manage.py check
```

Airflow 使用独立环境，安装约束和运行方式见[开发实施文档](设计文档/IaaS智能巡检平台_开发实施文档_v1.md)。

## 文档

- [详细设计文档](设计文档/IaaS智能巡检平台_详细设计文档_v1.md)：产品定位、风险闭环、插件模型、LLM 调查和安全边界。
- [开发实施文档](设计文档/IaaS智能巡检平台_开发实施文档_v1.md)：工程结构、数据库、API、Airflow、前端和测试实施约束。

## 开发状态

`v0.1.0` 主要用于冻结第一阶段的产品与工程基线。后续实现应遵守以下边界：

- LLM 只能调用 `read_only=true` 的巡检能力。
- 不允许自动重启、迁移、改配置、扩缩容或删除等写操作。
- Airflow 不直接 import Django/LangGraph 业务模块，通过内部 HTTP API 驱动批处理。
- 新能力必须先经过 `SHADOW` 验证，再进入 `CODE_ACTIVE`。

## 安全提示

本地密钥、数据库密码和 Ollama 配置应通过环境变量提供，不要提交到仓库。项目中的默认密钥仅用于本地开发占位，不能用于生产环境。
