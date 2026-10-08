# IaaS 智能巡检平台

> Code-first、AI-on-demand 的 IaaS 巡检平台。

本项目面向基础设施运维场景，目标是把“发现风险、分析风险、人工反馈、经验沉淀、能力代码化、下一轮自动复验”串成一个可追踪的闭环。

`v0.4.0` 发布内容包含推理性能画像、GPU / 宿主机健康巡检、风险与复验流程，以及 AI 解读和提示词管理。本轮补充了规则详情中的可采集指标与具体判定规则、[20 项推理性能指标清单](docs/api/inference-performance-metrics.md)，并统一 `VERSION` 和前端项目版本为 `0.4.0`。完整变化及升级要求见 [v0.4.0 发布说明](docs/release/v0.4.0.md)。此前 `v0.3.0` 覆盖推理性能插件与提示词管理；GPU / 宿主机巡检由其后的主分支更新加入。

正式巡检使用外部监控程序推送的聚合快照；平台负责保存、评估、展示和风险闭环。当前代码不直接连接 Prometheus、Kubernetes、CMDB、日志平台、GPU 驱动或 SSH。仓库保留模拟数据工具用于开发和测试，正式数据路径不会默认生成模拟数据。已有代码与本地检查不代表生产采集接入、迁移或性能验收已经完成。

## 当前支持

| 资源 | 正式巡检规则 | 输入与评估 |
| --- | --- | --- |
| LLM 运行时 `LLM_RUNTIME` | `llm.performance_profile`，插件 `inference-performance` | vLLM / SGLang 的 20 项性能指标；固定阈值、14 天动态基线、默认 60 分钟趋势、质量与时效检查 |
| GPU 资源 `GPU_POOL` | `hardware.gpu_health`，插件 `gpu-host-health` | 利用率、显存、温度、窗口 Xid 事件及 DRAM 单 / 双比特 ECC 增量 |
| 主机基础环境 `HOST` | `hardware.host_health`，插件 `gpu-host-health` | CPU、可用内存、文件系统容量、磁盘吞吐与平均延迟、IO 忙碌比例 |

- 手动巡检支持 LLM / GPU / HOST 混合选择，按插件冻结输入，并生成检查结果、证据、风险和后续复验。
- 硬件巡检覆盖 17 项指标字段，保留有效、缺测、不支持及计数重置状态；条件基线、持续退化、容量趋势和疑似引擎关联均输出限制说明。缺少覆盖或处置验证证据时，不能自动宣告硬件风险恢复。
- 页面支持首页、资源与运行结果、风险详情、代码插件目录、AI 运行配置和提示词管理。AI 解读基于代码巡检事实，提示词写入需要服务端管理员令牌。
- 规则列表与详情 API 提供 `input_contract`、`supported_metrics`、`judgment_rules` 和 `policy_profiles`。详情展示 LLM 20 项、GPU 7 项、HOST 10 项指标的中文含义、单位与范围、输入路径及用途，并展示默认与模型有效阈值、具体判定和未就绪边界；字段与阈值来自后端实际 schema 和策略文件。
- Airflow 通过内部 HTTP API 驱动巡检；本地开发可使用本地后台任务。定时输入支持推理、硬件以及混合外部快照。

详细字段及接入约束见 [推理性能指标与 API](docs/api/inference-performance-metrics.md) 和 [GPU / 宿主机巡检接入](docs/api/gpu-host-inspection.md)。

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
| 前端 | React 19、TypeScript、Vite、Ant Design、ECharts |
| 在线调查 | LangGraph 1.2.10、LangChain 1.3.14、Ollama |
| 批量编排 | Airflow 2.3.2 |
| 数据库 | PostgreSQL 14.x |
| 运行时 | Python 3.10.x，Web 与 Airflow 两个独立虚拟环境 |
| 正式数据源 | 外部聚合推理 / 硬件快照，支持单条与批量推送 |

## 当前目录

```text
manage.py                         Django 入口
config/                           Django 配置、推理评估策略
apps/                             巡检、快照、风险、调查等领域模块
services/                         插件运行、模型网关、任务调度
frontend/                         React 页面及前端测试
airflow/                          通过内部 HTTP API 编排的 DAG
requirements/                     Web、开发和 Airflow 依赖
tests/                            API、领域、算法和集成检查
docs/                             接入、设计、实施与发布文档
设计文档/                         详细设计与开发实施文档
VERSION                           项目版本号（0.4.0）
```

## 命令行启动

以下命令在仓库根目录执行。macOS 使用 Docker Desktop 时先启动引擎，再启动 PostgreSQL：

```bash
docker desktop start
docker compose up -d postgres
```

若 `iaas-inspection-postgres` 容器已存在，可用 `docker start iaas-inspection-postgres` 启动它。等待数据库健康后继续。

首次安装使用 Python 3.10 创建 Web 环境并安装开发依赖：

```bash
python3.10 -m venv .venv-web
source .venv-web/bin/activate
python -m pip install -r requirements/web-dev.txt
```

首次安装时将 `.env.example` 复制为 `.env`，按本地环境填写；已有 `.env` 应保留。Django 会读取仓库根目录的 `.env`。然后迁移数据库并注册正式巡检规则：

```bash
source .venv-web/bin/activate
python manage.py migrate
python manage.py seed_launch
python manage.py runserver 127.0.0.1:8000
```

在另一个终端启动前端：

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

打开 [前端页面](http://127.0.0.1:5174/)，[后端健康检查](http://127.0.0.1:8000/api/v1/health) 用于确认 API 可用。首次安装仍需配置环境并接入快照；没有外部数据时应显示无数据或未就绪。AI 解读另需可访问的模型服务及对应 `.env` 配置。

已有部署升级前需备份并演练迁移；旧推理快照的资产关联回填、Airflow 切换和提示词配置按 [发布运行说明](docs/release/iaas-llm-plugin-prompt-runbook.md) 执行。Airflow 使用独立虚拟环境，安装约束见 [开发实施文档](设计文档/IaaS智能巡检平台_开发实施文档_v1.md)。

## 本地检查

```bash
source .venv-web/bin/activate
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
```

前端在 `frontend/` 目录执行 `npm test` 和 `npm run build`；浏览器端到端检查使用 `npm run e2e`。检查结果需对应实际提交，发布与部署验证边界见 [v0.4.0 发布说明](docs/release/v0.4.0.md)。

## 文档

- [详细设计文档](设计文档/IaaS智能巡检平台_详细设计文档_v1.md)：产品定位、风险闭环、插件模型、LLM 调查和安全边界。
- [开发实施文档](设计文档/IaaS智能巡检平台_开发实施文档_v1.md)：工程结构、数据库、API、Airflow、前端和测试实施约束。
- [推理性能画像设计](docs/LLM/inference_performance_mvp_design.md)：性能画像 MVP 的设计背景。
- [推理性能指标清单](docs/api/inference-performance-metrics.md)：当前 20 项指标、评估用途与接入 API。
- [GPU / 宿主机巡检接入](docs/api/gpu-host-inspection.md)：硬件指标、数据质量、身份绑定、复验与批量输入。
- [推理插件与提示词发布运行说明](docs/release/iaas-llm-plugin-prompt-runbook.md)：保留历史数据的升级、真实输入验证与回滚。
- [v0.4.0 发布说明](docs/release/v0.4.0.md)：本次发布范围、升级步骤和验证边界。

## 安全与运行边界

当前实现遵守以下边界，生产部署仍需单独验证：

- LLM 只能调用 `read_only=true` 的巡检能力。
- 不允许自动重启、迁移、改配置、扩缩容或删除等写操作。
- Airflow 不直接 import Django/LangGraph 业务模块，通过内部 HTTP API 驱动批处理。
- 新能力代码化流程要求先经过 `SHADOW` 验证，再进入 `CODE_ACTIVE`；正式巡检使用已注册的代码插件。
- 公开 API 依赖可信网络或网关边界；提示词修改另受服务端 `PROMPT_ADMIN_TOKEN` 保护，令牌不进入前端构建或持久存储。

## 安全提示

本地密钥、数据库密码和 Ollama 配置应通过环境变量提供，不要提交到仓库。项目中的默认密钥仅用于本地开发占位，不能用于生产环境。
