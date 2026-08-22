# IaaS 智能巡检平台开发实施文档 v1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Demo v4.1 的产品理念基础上，建设一套可本地运行的 IaaS 智能巡检平台：使用 PostgreSQL 持久化、Airflow 每日编排、模拟巡检数据、Capability Registry 插件体系、Ollama LLM、LangGraph 调查链路、人机反馈和 Experience-to-Code 闭环。

**Architecture:** Django 4.2.16 作为产品 API 和 Web 后端；LangGraph 1.2.10 + LangChain 1.3.14 运行在线只读调查图；Airflow 2.3.2 在独立 Python 环境中通过内部 HTTP API 编排每日巡检，避免旧版 Airflow 与现代 LLM 依赖发生 Python 包冲突。PostgreSQL 14.x 由本机 Docker 启动；第一阶段所有巡检数据由固定 seed 的生成器产生，不连接真实生产数据源。

**Tech Stack:** Python 3.10.x、Django 4.2.16、Django REST Framework 3.15.x、Airflow 2.3.2、LangGraph 1.2.10、LangChain 1.3.14、PostgreSQL 14.x、Ollama、Vanilla ES Modules/CSS、pytest/pytest-django。

**Spec:** `IaaS智能巡检平台_详细设计文档_v1.md`

## Global Constraints

- Django 必须固定为 `4.2.16`。
- Airflow 必须固定为 `2.3.2`。
- LangGraph 必须固定为 `1.2.10`。
- LangChain 必须固定为 `1.3.14`。
- Python 使用 `3.10.x`。
- Airflow 与 Django/LLM Runtime 使用两个独立虚拟环境，不允许合并 requirements。
- PostgreSQL 使用本机 Docker 启动，第一阶段推荐 `postgres:14`。
- 第一阶段不连接真实 Prometheus、Kubernetes、CMDB、日志或 ITSM。
- 模拟数据必须使用 seed 可复现。
- LLM 本地默认 Provider 为 Ollama。
- LLM 只能调用 `read_only=true` 的 Capability。
- 不允许 LLM 执行重启、迁移、写配置、扩缩容、删除等写操作。
- Tool Call 输入必须通过 JSON Schema 校验。
- 所有 Tool Call、LLM 消息、人工反馈、风险状态变化必须持久化并可审计。
- “记录已处理”只能把风险变为 `PENDING_REVERIFY`，不能直接标记 `RECOVERED`。
- 新插件/规则必须经 `SHADOW` 后才能进入 `CODE_ACTIVE`。
- UI 默认简洁，Evidence、Tool Call、内部状态、Raw JSON 默认折叠。
- 每个巡检项目必须显示 `execution_mode`、`code_status`、`code_coverage_percent` 和 `llm_responsibilities`。
- 每个开发任务先写失败测试，再做最小实现，再运行相关测试和回归测试。

---

# 第一部分：工程与运行环境

## 1. 推荐仓库结构

```text
iaas-inspection/
├── manage.py
├── pyproject.toml
├── requirements/
│   ├── web.txt
│   ├── web-dev.txt
│   └── airflow.txt
├── .env.example
├── docker-compose.yml
├── docker/
│   └── postgres/
│       └── init-multiple-dbs.sh
├── config/
│   ├── __init__.py
│   ├── urls.py
│   ├── wsgi.py
│   └── settings/
│       ├── base.py
│       ├── dev.py
│       └── test.py
├── apps/
│   ├── core/
│   ├── assets/
│   ├── inspections/
│   ├── risks/
│   ├── capabilities/
│   ├── investigations/
│   ├── conversations/
│   ├── feedback/
│   ├── experiences/
│   ├── mockdata/
│   └── audit/
├── services/
│   ├── model_gateway/
│   │   ├── base.py
│   │   ├── ollama.py
│   │   └── openai_compatible.py
│   ├── investigation_graph/
│   │   ├── state.py
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   └── schemas.py
│   ├── plugin_runtime/
│   │   ├── registry.py
│   │   ├── executor.py
│   │   ├── rule_executor.py
│   │   ├── exec_executor.py
│   │   ├── rest_executor.py
│   │   └── mcp_executor.py
│   └── mock_generator/
│       ├── generator.py
│       └── scenarios.py
├── plugins/
│   ├── manifests/
│   ├── rules/
│   └── exec/
├── airflow/
│   └── dags/
│       └── daily_iaas_inspection.py
├── templates/
│   ├── app.html
│   └── product_about.html
├── static/
│   ├── css/
│   └── js/
│       ├── app.js
│       ├── api.js
│       ├── dashboard.js
│       ├── risks.js
│       ├── capabilities.js
│       ├── conversation.js
│       └── about.js
├── docs/
│   ├── api.md
│   ├── database.md
│   └── product.md
└── tests/
    ├── api/
    ├── domain/
    ├── services/
    └── integration/
```

## 2. 双 Python 环境

由于 Airflow 2.3.2 与 LangChain/LangGraph 的依赖年代差异较大，必须分离：

```text
.venv-web
  Django 4.2.16
  LangGraph 1.2.10
  LangChain 1.3.14
  DRF
  httpx
  psycopg

.venv-airflow
  Airflow 2.3.2
  requests
  使用 Airflow 官方对应 Python 3.10 constraints 安装
```

Airflow **不得 import Django/LangGraph 业务模块**，只通过内部 HTTP API 驱动批处理阶段。

## 3. `requirements/web.txt`

```text
Django==4.2.16
djangorestframework>=3.15,<3.16
langgraph==1.2.10
langchain==1.3.14
psycopg[binary]>=3.2,<3.3
httpx>=0.27,<0.29
jsonschema>=4.23,<5
python-dotenv>=1.0,<2
```

开发依赖：

```text
pytest>=8.3,<9
pytest-django>=4.9,<5
pytest-cov>=5,<6
freezegun>=1.5,<2
```

Airflow 独立安装：

```bash
python3.10 -m venv .venv-airflow
source .venv-airflow/bin/activate

AIRFLOW_VERSION=2.3.2
PYTHON_VERSION=3.10
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}"
pip install requests
```

> 若本地无法访问 constraints URL，应提前保存对应约束文件到仓库内部开发依赖镜像；不能绕过 constraints 直接混装。

## 4. Docker PostgreSQL

`docker-compose.yml`：

```yaml
services:
  postgres:
    image: postgres:14
    container_name: iaas-inspection-postgres
    environment:
      POSTGRES_USER: inspection
      POSTGRES_PASSWORD: inspection_dev
      POSTGRES_DB: inspection
      POSTGRES_MULTIPLE_DATABASES: airflow
    ports:
      - "5432:5432"
    volumes:
      - inspection_pgdata:/var/lib/postgresql/data
      - ./docker/postgres/init-multiple-dbs.sh:/docker-entrypoint-initdb.d/init-multiple-dbs.sh:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U inspection -d inspection"]
      interval: 5s
      timeout: 3s
      retries: 20

volumes:
  inspection_pgdata:
```

`init-multiple-dbs.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

if [ -n "${POSTGRES_MULTIPLE_DATABASES:-}" ]; then
  for db in $(echo "$POSTGRES_MULTIPLE_DATABASES" | tr ',' ' '); do
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE DATABASE "$db";
SQL
  done
fi
```

应用 DSN：

```text
DATABASE_URL=postgresql://inspection:inspection_dev@127.0.0.1:5432/inspection
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://inspection:inspection_dev@127.0.0.1:5432/airflow
```

## 5. `.env.example`

```text
DJANGO_SETTINGS_MODULE=config.settings.dev
DJANGO_SECRET_KEY=local-dev-only-change-me
DATABASE_URL=postgresql://inspection:inspection_dev@127.0.0.1:5432/inspection
APP_TIMEZONE=Asia/Shanghai

LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
LLM_TIMEOUT_SECONDS=120
LLM_MAX_ROUNDS=3
LLM_MAX_TOOL_CALLS=5
LLM_MAX_EVIDENCE_ITEMS=30

AIRFLOW_BASE_URL=http://127.0.0.1:8080
AIRFLOW_DAG_ID=daily_iaas_inspection
AIRFLOW_INTERNAL_TOKEN=local-airflow-token

MOCK_DEFAULT_SEED=20260823
MOCK_DEFAULT_SCENARIO=llm_scheduler_pressure
```

---

# 第二部分：PostgreSQL 数据库设计

## 6. 通用规则

- 对外主键统一 UUID；
- 数据库时区统一 UTC，API 输出带 timezone；
- JSON 结构使用 `jsonb`；
- 标签集合优先 `jsonb`，需要查询的固定集合使用 PostgreSQL `text[]`；
- 所有主表至少包含 `created_at`，可编辑主表包含 `updated_at`；
- 日志型表不做物理更新；
- 高访问外键建 B-Tree index；
- 所有枚举在 Django 中使用 `TextChoices`，数据库保存字符串，避免 PostgreSQL ENUM 迁移复杂度。
- 本文完整描述项目自定义业务表；Django 自带的 `auth_*`、`django_*` 表由 Django 4.2.16 migrations 管理，Airflow metadata 表由 Airflow 2.3.2 管理，不在业务模型中复制定义。

---

## 7. `environments`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 环境 ID |
| `name` | varchar(128) | 否 | - | - | 显示名称 |
| `slug` | varchar(64) | 否 | - | UNIQUE | API/URL 标识 |
| `environment_type` | varchar(32) | 否 | `DEV` | INDEX | DEV/TEST/PROD_SIM |
| `tenant_key` | varchar(128) | 是 | null | INDEX | 未来多租户预留 |
| `timezone` | varchar(64) | 否 | `Asia/Shanghai` | - | 展示时区 |
| `is_active` | boolean | 否 | true | INDEX | 是否启用 |
| `metadata` | jsonb | 否 | `{}` | GIN 可选 | 扩展信息 |
| `created_at` | timestamptz | 否 | now | - | 创建时间 |
| `updated_at` | timestamptz | 否 | now | - | 更新时间 |

---

## 8. `assets`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 资产 ID |
| `environment_id` | UUID | 否 | - | FK environments, INDEX | 所属环境 |
| `external_key` | varchar(192) | 否 | - | UNIQUE(environment, external_key) | 模拟/未来真实资产唯一键 |
| `asset_type` | varchar(32) | 否 | - | INDEX | CLUSTER/HOST/VM/POD/GPU/LLM_INSTANCE |
| `name` | varchar(192) | 否 | - | INDEX | 资产名称 |
| `parent_id` | UUID | 是 | null | FK assets, INDEX | 父资产 |
| `status` | varchar(32) | 否 | `ACTIVE` | INDEX | ACTIVE/INACTIVE |
| `labels` | jsonb | 否 | `{}` | GIN 可选 | 标签 |
| `topology` | jsonb | 否 | `{}` | - | rack/az/numa 等拓扑 |
| `first_seen_at` | timestamptz | 否 | now | - | 首次出现 |
| `last_seen_at` | timestamptz | 否 | now | INDEX | 最近出现 |
| `created_at` | timestamptz | 否 | now | - | 创建时间 |
| `updated_at` | timestamptz | 否 | now | - | 更新时间 |

---

## 9. `inspection_items`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 巡检项目 ID |
| `code` | varchar(128) | 否 | - | UNIQUE | 稳定编码，如 `llm.performance` |
| `name` | varchar(192) | 否 | - | INDEX | 中文名称 |
| `domain` | varchar(64) | 否 | - | INDEX | 控制面/LLM/GPU/网络/容量等 |
| `description` | text | 否 | `''` | - | 产品说明 |
| `execution_mode` | varchar(40) | 否 | - | INDEX | CODE_ONLY/CODE_FIRST_AI_FALLBACK/AI_INVESTIGATION/LEARNING_MODE |
| `code_status` | varchar(32) | 否 | - | INDEX | CODE_ACTIVE/PARTIAL_CODE/CODE_PENDING/SHADOW/NOT_CODED |
| `code_coverage_percent` | numeric(5,2) | 否 | 0 | - | 0~100 |
| `default_severity` | varchar(8) | 否 | `P3` | - | P1/P2/P3/P4 |
| `enabled` | boolean | 否 | true | INDEX | 是否启用 |
| `schedule_policy` | jsonb | 否 | `{}` | - | 频率/适用环境 |
| `required_claims` | jsonb | 否 | `[]` | - | 必须闭环的 Claim |
| `resolved_claims` | jsonb | 否 | `[]` | - | 当前 Code 已覆盖 Claim |
| `llm_responsibilities` | jsonb | 否 | `[]` | - | LLM 当前负责内容 |
| `version` | varchar(32) | 否 | `1.0.0` | - | 巡检定义版本 |
| `created_at` | timestamptz | 否 | now | - | 创建时间 |
| `updated_at` | timestamptz | 否 | now | - | 更新时间 |

---

## 10. `mock_datasets`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 数据集 ID |
| `environment_id` | UUID | 否 | - | FK, INDEX | 所属环境 |
| `seed` | bigint | 否 | - | INDEX | 可复现随机种子 |
| `scenario` | varchar(64) | 否 | - | INDEX | 场景编码 |
| `dataset_date` | date | 否 | - | INDEX | 模拟业务日期 |
| `version` | varchar(32) | 否 | `1` | - | 生成器版本 |
| `status` | varchar(32) | 否 | `GENERATING` | INDEX | GENERATING/READY/FAILED |
| `generator_config` | jsonb | 否 | `{}` | - | 生成参数快照 |
| `asset_count` | integer | 否 | 0 | - | 资产数 |
| `metric_count` | integer | 否 | 0 | - | 指标点数 |
| `log_count` | integer | 否 | 0 | - | 日志数 |
| `event_count` | integer | 否 | 0 | - | 事件数 |
| `change_count` | integer | 否 | 0 | - | 变更数 |
| `error_message` | text | 是 | null | - | 失败原因 |
| `created_at` | timestamptz | 否 | now | - | 创建时间 |
| `ready_at` | timestamptz | 是 | null | - | 完成时间 |

---

## 11. `mock_metrics`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | bigint | 否 | identity | PK | 内部点 ID |
| `dataset_id` | UUID | 否 | - | FK, INDEX | 数据集 |
| `asset_id` | UUID | 否 | - | FK, INDEX | 资产 |
| `metric_name` | varchar(128) | 否 | - | INDEX | 指标名 |
| `ts` | timestamptz | 否 | - | INDEX | 时间点 |
| `value` | double precision | 否 | - | - | 数值 |
| `labels` | jsonb | 否 | `{}` | GIN 可选 | 标签 |

建议联合索引：`(dataset_id, asset_id, metric_name, ts)`。

---

## 12. `mock_logs`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | bigint | 否 | identity | PK | 日志 ID |
| `dataset_id` | UUID | 否 | - | FK, INDEX | 数据集 |
| `asset_id` | UUID | 否 | - | FK, INDEX | 资产 |
| `ts` | timestamptz | 否 | - | INDEX | 时间 |
| `source` | varchar(64) | 否 | - | INDEX | kernel/runtime/kubelet 等 |
| `level` | varchar(16) | 否 | `INFO` | INDEX | 日志级别 |
| `message` | text | 否 | - | - | 日志正文 |
| `attributes` | jsonb | 否 | `{}` | GIN 可选 | 结构化字段 |

---

## 13. `mock_events`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | bigint | 否 | identity | PK | 事件 ID |
| `dataset_id` | UUID | 否 | - | FK, INDEX | 数据集 |
| `asset_id` | UUID | 是 | null | FK, INDEX | 关联资产 |
| `ts` | timestamptz | 否 | - | INDEX | 时间 |
| `event_type` | varchar(64) | 否 | - | INDEX | 类型 |
| `reason` | varchar(128) | 否 | `''` | - | 原因 |
| `message` | text | 否 | `''` | - | 描述 |
| `attributes` | jsonb | 否 | `{}` | - | 附加字段 |

---

## 14. `mock_changes`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | bigint | 否 | identity | PK | 变更 ID |
| `dataset_id` | UUID | 否 | - | FK, INDEX | 数据集 |
| `asset_id` | UUID | 是 | null | FK, INDEX | 关联资产 |
| `start_at` | timestamptz | 否 | - | INDEX | 开始时间 |
| `end_at` | timestamptz | 是 | null | - | 结束时间 |
| `change_type` | varchar(64) | 否 | - | INDEX | deploy/config/scale 等 |
| `summary` | text | 否 | - | - | 摘要 |
| `attributes` | jsonb | 否 | `{}` | - | 详情 |

---

## 15. `inspection_runs`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 每日/手工运行 ID |
| `environment_id` | UUID | 否 | - | FK, INDEX | 环境 |
| `dataset_id` | UUID | 是 | null | FK, INDEX | 本次模拟数据集 |
| `run_date` | date | 否 | - | INDEX | 业务日期 |
| `trigger_type` | varchar(32) | 否 | - | INDEX | AIRFLOW/MANUAL/API |
| `airflow_dag_run_id` | varchar(250) | 是 | null | UNIQUE 可选 | DAG Run ID |
| `status` | varchar(32) | 否 | `PENDING` | INDEX | PENDING/RUNNING/SUCCEEDED/PARTIAL/FAILED |
| `started_at` | timestamptz | 是 | null | - | 开始 |
| `finished_at` | timestamptz | 是 | null | - | 结束 |
| `total_items` | integer | 否 | 0 | - | 计划项数 |
| `success_items` | integer | 否 | 0 | - | 成功数 |
| `failed_items` | integer | 否 | 0 | - | 失败数 |
| `risk_count` | integer | 否 | 0 | - | 风险数 |
| `config_snapshot` | jsonb | 否 | `{}` | - | 运行配置 |
| `error_message` | text | 是 | null | - | 失败原因 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

唯一建议：`(environment_id, run_date, trigger_type, airflow_dag_run_id)` 按业务约束处理幂等。

---

## 16. `inspection_item_runs`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 巡检项执行 ID |
| `inspection_run_id` | UUID | 否 | - | FK, INDEX | 所属运行 |
| `inspection_item_id` | UUID | 否 | - | FK, INDEX | 巡检项目 |
| `status` | varchar(32) | 否 | `PENDING` | INDEX | PENDING/RUNNING/SUCCEEDED/FAILED |
| `ai_admission_status` | varchar(40) | 否 | `NOT_EVALUATED` | INDEX | NOT_EVALUATED/NO_AI/AI_ELIGIBLE/AI_DEFERRED/DATA_INVALID |
| `asset_scope` | jsonb | 否 | `{}` | - | 实际资产范围 |
| `summary` | jsonb | 否 | `{}` | - | 结果摘要 |
| `started_at` | timestamptz | 是 | null | - | 开始 |
| `finished_at` | timestamptz | 是 | null | - | 结束 |
| `model_provider` | varchar(32) | 是 | null | - | 使用 AI 时记录 |
| `model_name` | varchar(128) | 是 | null | - | 模型 |
| `input_tokens` | integer | 否 | 0 | - | 输入 Token 估算/返回值 |
| `output_tokens` | integer | 否 | 0 | - | 输出 Token |
| `error_code` | varchar(64) | 是 | null | - | 错误码 |
| `error_message` | text | 是 | null | - | 错误 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

唯一：`(inspection_run_id, inspection_item_id)`。

---

## 17. `findings`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | Finding ID |
| `inspection_item_run_id` | UUID | 否 | - | FK, INDEX | 来源执行 |
| `asset_id` | UUID | 是 | null | FK, INDEX | 关联资产 |
| `finding_code` | varchar(128) | 否 | - | INDEX | 如 TTFT_DEGRADED |
| `title` | varchar(192) | 否 | - | - | 中文标题 |
| `category` | varchar(64) | 否 | - | INDEX | performance/capacity/topology 等 |
| `severity` | varchar(8) | 否 | `P3` | INDEX | P1-P4 |
| `materiality` | numeric(5,4) | 否 | 0 | - | 重要度 0~1 |
| `status` | varchar(32) | 否 | `ACTIVE` | INDEX | ACTIVE/RESOLVED/INVALID |
| `value` | jsonb | 否 | `{}` | - | 指标/趋势/结构化值 |
| `source_type` | varchar(32) | 否 | - | INDEX | METRIC/LOG/EVENT/TOPOLOGY/RULE |
| `observed_at` | timestamptz | 否 | - | INDEX | 观察时间 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

---

## 18. `risks`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 稳定 risk_id |
| `environment_id` | UUID | 否 | - | FK, INDEX | 环境 |
| `inspection_item_id` | UUID | 否 | - | FK, INDEX | 来源巡检项目 |
| `primary_asset_id` | UUID | 是 | null | FK, INDEX | 主要对象 |
| `risk_key` | varchar(192) | 否 | - | INDEX | 人类可读风险 key |
| `fingerprint` | varchar(128) | 否 | - | UNIQUE(environment, fingerprint) | 跨天去重核心 |
| `title` | varchar(255) | 否 | - | INDEX | 标题 |
| `domain` | varchar(64) | 否 | - | INDEX | 领域 |
| `severity` | varchar(8) | 否 | - | INDEX | P1-P4 |
| `status` | varchar(32) | 否 | `NEW` | INDEX | 生命周期状态 |
| `current_conclusion` | text | 否 | `''` | - | 当前根因/结论 |
| `impact_summary` | text | 否 | `''` | - | 影响 |
| `recommendation` | text | 否 | `''` | - | 处置建议 |
| `first_seen_at` | timestamptz | 否 | - | INDEX | 首次发现 |
| `last_seen_at` | timestamptz | 否 | - | INDEX | 最近发现 |
| `recovered_at` | timestamptz | 是 | null | INDEX | 恢复时间 |
| `occurrence_count` | integer | 否 | 1 | - | 命中次数 |
| `duration_days` | integer | 否 | 1 | - | 持续天数 |
| `llm_involved_last` | boolean | 否 | false | INDEX | 最近一次是否 AI 参与 |
| `current_investigation_id` | UUID | 是 | null | INDEX | 当前调查，迁移后加 FK |
| `created_at` | timestamptz | 否 | now | - | 创建 |
| `updated_at` | timestamptz | 否 | now | - | 更新 |

---

## 19. `risk_observations`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 每次观察 |
| `risk_id` | UUID | 否 | - | FK, INDEX | 风险 |
| `inspection_run_id` | UUID | 否 | - | FK, INDEX | 每日运行 |
| `inspection_item_run_id` | UUID | 否 | - | FK, INDEX | 巡检项执行 |
| `observed_at` | timestamptz | 否 | - | INDEX | 时间 |
| `detected` | boolean | 否 | true | INDEX | 本轮是否仍检测到 |
| `severity` | varchar(8) | 否 | - | - | 本轮严重度 |
| `status_after` | varchar(32) | 否 | - | - | 本轮后状态 |
| `finding_count` | integer | 否 | 0 | - | Finding 数 |
| `evidence_count` | integer | 否 | 0 | - | Evidence 数 |
| `snapshot` | jsonb | 否 | `{}` | - | 当时风险摘要 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

唯一：`(risk_id, inspection_run_id)`。

---

## 20. `risk_status_history`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 历史记录 |
| `risk_id` | UUID | 否 | - | FK, INDEX | 风险 |
| `from_status` | varchar(32) | 是 | null | - | 原状态 |
| `to_status` | varchar(32) | 否 | - | INDEX | 新状态 |
| `reason` | text | 否 | `''` | - | 原因 |
| `source` | varchar(32) | 否 | - | INDEX | SYSTEM/HUMAN/REVERIFY |
| `actor_user_id` | bigint | 是 | null | FK auth_user | 人工操作人 |
| `inspection_run_id` | UUID | 是 | null | FK, INDEX | 触发运行 |
| `created_at` | timestamptz | 否 | now | INDEX | 时间 |

---

## 21. `evidence`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | Evidence ID |
| `inspection_run_id` | UUID | 是 | null | FK, INDEX | 来源运行 |
| `inspection_item_run_id` | UUID | 是 | null | FK, INDEX | 来源巡检项 |
| `risk_id` | UUID | 是 | null | FK, INDEX | 风险 |
| `investigation_id` | UUID | 是 | null | INDEX | 调查，迁移后 FK |
| `asset_id` | UUID | 是 | null | FK, INDEX | 资产 |
| `evidence_type` | varchar(32) | 否 | - | INDEX | METRIC/LOG/EVENT/TOPOLOGY/TOOL_RESULT/CHANGE |
| `evidence_key` | varchar(192) | 否 | - | INDEX | 稳定/可读 key |
| `summary` | text | 否 | - | - | LLM 可消费摘要 |
| `payload` | jsonb | 否 | `{}` | - | 结构化数据 |
| `source` | varchar(128) | 否 | - | INDEX | generator/capability 等 |
| `window_start` | timestamptz | 是 | null | - | 时间窗 |
| `window_end` | timestamptz | 是 | null | - | 时间窗 |
| `confidence` | numeric(5,4) | 否 | 1 | - | 置信度 |
| `materiality` | numeric(5,4) | 否 | 0 | - | 重要度 |
| `raw_ref` | varchar(255) | 是 | null | - | 未来原始数据引用 |
| `created_at` | timestamptz | 否 | now | INDEX | 创建 |

---

## 22. `daily_snapshots`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | Snapshot ID |
| `environment_id` | UUID | 否 | - | FK | 环境 |
| `snapshot_date` | date | 否 | - | UNIQUE(environment, date) | 日期 |
| `inspection_run_id` | UUID | 否 | - | FK, UNIQUE | 来源运行 |
| `assets_total` | integer | 否 | 0 | - | 资产总数 |
| `assets_covered` | integer | 否 | 0 | - | 覆盖资产 |
| `inspection_item_count` | integer | 否 | 0 | - | 巡检项数 |
| `risk_total` | integer | 否 | 0 | - | 风险总量 |
| `p1_count` | integer | 否 | 0 | - | P1 |
| `p2_count` | integer | 否 | 0 | - | P2 |
| `new_count` | integer | 否 | 0 | - | 新增 |
| `worsened_count` | integer | 否 | 0 | - | 加重 |
| `recovered_count` | integer | 否 | 0 | - | 恢复 |
| `pending_action_count` | integer | 否 | 0 | - | 待处置 |
| `pending_reverify_count` | integer | 否 | 0 | - | 待复验 |
| `code_only_cases` | integer | 否 | 0 | - | 纯代码 Case |
| `ai_dependent_cases` | integer | 否 | 0 | - | AI Case |
| `code_coverage_rate` | numeric(6,3) | 否 | 0 | - | 代码化覆盖率 |
| `deterministic_deflection_rate` | numeric(6,3) | 否 | 0 | - | 0 Token 转移率 |
| `ai_displacement_rate` | numeric(6,3) | 否 | 0 | - | AI 被代码替代比例 |
| `data_completeness_rate` | numeric(6,3) | 否 | 0 | - | 数据完整性 |
| `summary` | jsonb | 否 | `{}` | - | 首页摘要 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

---

## 23. `capabilities`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | Registry 内部 ID |
| `capability_id` | varchar(192) | 否 | - | UNIQUE | 稳定能力 ID |
| `name` | varchar(192) | 否 | - | INDEX | 名称 |
| `description` | text | 否 | `''` | - | 说明 |
| `domain` | varchar(64) | 否 | - | INDEX | 领域 |
| `status` | varchar(32) | 否 | `ACTIVE` | INDEX | ACTIVE/DISABLED/RETIRED |
| `current_version_id` | UUID | 是 | null | INDEX | 当前版本，迁移后 FK |
| `owner` | varchar(128) | 否 | `platform` | - | 维护人/团队 |
| `read_only` | boolean | 否 | true | INDEX | LLM 工具安全门 |
| `created_at` | timestamptz | 否 | now | - | 创建 |
| `updated_at` | timestamptz | 否 | now | - | 更新 |

---

## 24. `capability_versions`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 版本 ID |
| `capability_id_fk` | UUID | 否 | - | FK capabilities, INDEX | 能力 |
| `version` | varchar(32) | 否 | - | UNIQUE(capability, version) | 语义版本 |
| `implementation_type` | varchar(16) | 否 | - | INDEX | RULE/EXEC/REST/MCP |
| `status` | varchar(32) | 否 | `CANDIDATE` | INDEX | CANDIDATE/SHADOW/ACTIVE/RETIRED |
| `manifest` | jsonb | 否 | `{}` | - | 完整 Manifest |
| `semantic_tags` | text[] | 否 | `{}` | GIN | 语义标签 |
| `subjects` | text[] | 否 | `{}` | GIN | 适用对象 |
| `resolves` | text[] | 否 | `{}` | GIN | 可解决 Claim |
| `input_schema` | jsonb | 否 | `{}` | - | JSON Schema |
| `output_schema` | jsonb | 否 | `{}` | - | JSON Schema |
| `endpoint` | varchar(512) | 是 | null | - | REST URL |
| `script_path` | varchar(512) | 是 | null | - | EXEC 白名单路径 |
| `mcp_server` | varchar(192) | 是 | null | - | MCP Server 标识 |
| `mcp_tool` | varchar(192) | 是 | null | - | MCP Tool |
| `timeout_seconds` | integer | 否 | 15 | - | 超时 |
| `retry_count` | integer | 否 | 0 | - | 重试次数 |
| `health_status` | varchar(32) | 否 | `UNKNOWN` | INDEX | UNKNOWN/HEALTHY/UNHEALTHY |
| `last_health_check_at` | timestamptz | 是 | null | - | 健康检查 |
| `activated_at` | timestamptz | 是 | null | - | 激活时间 |
| `retired_at` | timestamptz | 是 | null | - | 退役时间 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

---

## 25. `inspection_capability_bindings`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 绑定 ID |
| `inspection_item_id` | UUID | 否 | - | FK, INDEX | 巡检项目 |
| `capability_version_id` | UUID | 否 | - | FK, INDEX | 能力版本 |
| `role` | varchar(32) | 否 | - | INDEX | DETECTOR/ENRICHER/RESOLVER/VALIDATOR |
| `claim` | varchar(192) | 否 | - | INDEX | 该绑定服务的 Claim |
| `priority` | integer | 否 | 100 | - | 越小越优先 |
| `required` | boolean | 否 | false | - | 是否必需 |
| `enabled` | boolean | 否 | true | INDEX | 是否生效 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

唯一建议：`(inspection_item_id, capability_version_id, role, claim)`。

---

## 26. `investigations`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 调查 ID |
| `risk_id` | UUID | 是 | null | FK, INDEX | 风险 |
| `inspection_item_run_id` | UUID | 是 | null | FK, INDEX | 巡检执行 |
| `trigger_type` | varchar(32) | 否 | - | INDEX | HUMAN/AUTO/LEARNING |
| `status` | varchar(32) | 否 | `CREATED` | INDEX | CREATED/RUNNING/RESOLVED/UNRESOLVED/FAILED/CANCELLED |
| `entry_reason` | varchar(64) | 否 | - | INDEX | CLAIM_GAP/CONFLICT/TREND_GAP/USER_QUESTION/LEARNING_EVENT |
| `missing_claim` | varchar(192) | 是 | null | INDEX | 缺失 Claim |
| `model_provider` | varchar(32) | 否 | - | - | ollama 等 |
| `model_name` | varchar(128) | 否 | - | - | 模型名 |
| `max_rounds` | integer | 否 | 3 | - | 最大轮数 |
| `rounds_used` | integer | 否 | 0 | - | 已用轮数 |
| `max_tool_calls` | integer | 否 | 5 | - | 工具预算 |
| `tool_calls_used` | integer | 否 | 0 | - | 已用工具 |
| `conclusion` | text | 否 | `''` | - | 当前结论 |
| `confidence` | numeric(5,4) | 是 | null | - | 0~1 |
| `started_at` | timestamptz | 是 | null | - | 开始 |
| `finished_at` | timestamptz | 是 | null | - | 结束 |
| `created_at` | timestamptz | 否 | now | - | 创建 |
| `updated_at` | timestamptz | 否 | now | - | 更新 |

---

## 27. `investigation_events`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 事件 ID |
| `investigation_id` | UUID | 否 | - | FK, INDEX | 调查 |
| `sequence` | integer | 否 | - | UNIQUE(investigation, sequence) | SSE 顺序 |
| `event_type` | varchar(64) | 否 | - | INDEX | context.ready/tool.started 等 |
| `node_name` | varchar(64) | 否 | `''` | - | LangGraph node |
| `status` | varchar(32) | 否 | `INFO` | - | INFO/STARTED/COMPLETED/FAILED |
| `payload` | jsonb | 否 | `{}` | - | 事件数据 |
| `created_at` | timestamptz | 否 | now | INDEX | 时间 |

---

## 28. `conversations`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 会话 ID |
| `environment_id` | UUID | 否 | - | FK, INDEX | 环境 |
| `user_id` | bigint | 否 | - | FK auth_user, INDEX | 用户 |
| `context_type` | varchar(32) | 否 | - | INDEX | RISK/INSPECTION_ITEM/INVESTIGATION/EXPERIENCE |
| `context_id` | UUID | 否 | - | INDEX | 对应对象 ID |
| `risk_id` | UUID | 是 | null | FK, INDEX | 便捷关联 |
| `investigation_id` | UUID | 是 | null | FK, INDEX | 当前调查 |
| `title` | varchar(255) | 否 | - | - | 会话标题 |
| `status` | varchar(32) | 否 | `ACTIVE` | INDEX | ACTIVE/CLOSED |
| `created_at` | timestamptz | 否 | now | INDEX | 创建 |
| `updated_at` | timestamptz | 否 | now | - | 更新 |

---

## 29. `conversation_messages`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 消息 ID |
| `conversation_id` | UUID | 否 | - | FK, INDEX | 会话 |
| `role` | varchar(16) | 否 | - | INDEX | USER/ASSISTANT/SYSTEM/TOOL |
| `content` | text | 否 | `''` | - | 文本内容 |
| `structured_content` | jsonb | 否 | `{}` | - | 结构化结果 |
| `model_provider` | varchar(32) | 是 | null | - | AI 消息记录 |
| `model_name` | varchar(128) | 是 | null | - | 模型 |
| `prompt_version` | varchar(64) | 是 | null | - | Prompt 版本 |
| `input_tokens` | integer | 否 | 0 | - | 输入 Token |
| `output_tokens` | integer | 否 | 0 | - | 输出 Token |
| `latency_ms` | integer | 是 | null | - | 时延 |
| `parent_message_id` | UUID | 是 | null | FK self | 父消息 |
| `created_at` | timestamptz | 否 | now | INDEX | 创建 |

---

## 30. `tool_calls`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | Tool Call ID |
| `investigation_id` | UUID | 否 | - | FK, INDEX | 调查 |
| `conversation_id` | UUID | 是 | null | FK, INDEX | 会话 |
| `assistant_message_id` | UUID | 是 | null | FK, INDEX | 触发消息 |
| `capability_version_id` | UUID | 否 | - | FK, INDEX | 调用能力版本 |
| `call_id` | varchar(128) | 否 | - | UNIQUE | Graph 内稳定 call id |
| `tool_name` | varchar(192) | 否 | - | INDEX | 展示名称 |
| `input_args` | jsonb | 否 | `{}` | - | 已校验参数 |
| `status` | varchar(32) | 否 | `PENDING` | INDEX | PENDING/RUNNING/SUCCEEDED/FAILED/TIMEOUT/REJECTED |
| `started_at` | timestamptz | 是 | null | - | 开始 |
| `finished_at` | timestamptz | 是 | null | - | 结束 |
| `duration_ms` | integer | 是 | null | - | 耗时 |
| `result_summary` | text | 否 | `''` | - | 给 LLM 的压缩摘要 |
| `result_payload` | jsonb | 否 | `{}` | - | 结构化原始结果 |
| `error_code` | varchar(64) | 是 | null | - | 错误码 |
| `error_message` | text | 是 | null | - | 错误 |
| `evidence_id` | UUID | 是 | null | FK evidence, INDEX | 成功后产生 Evidence |
| `created_at` | timestamptz | 否 | now | INDEX | 创建 |

---

## 31. `human_feedback`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 反馈 ID |
| `environment_id` | UUID | 否 | - | FK, INDEX | 环境 |
| `user_id` | bigint | 否 | - | FK auth_user, INDEX | 用户 |
| `risk_id` | UUID | 是 | null | FK, INDEX | 风险 |
| `investigation_id` | UUID | 是 | null | FK, INDEX | 调查 |
| `conversation_id` | UUID | 是 | null | FK, INDEX | 会话 |
| `message_id` | UUID | 是 | null | FK, INDEX | 针对的 LLM 消息 |
| `feedback_type` | varchar(40) | 否 | - | INDEX | HELPFUL/INCORRECT/MISSING_EVIDENCE/WRONG_TOOL_PATH/CONFIRMED_ROOT_CAUSE/FALSE_POSITIVE/CUSTOM |
| `rating` | smallint | 是 | null | CHECK 1..5 | 可选评分 |
| `comment` | text | 否 | `''` | - | 人工说明 |
| `confirmed_conclusion` | text | 否 | `''` | - | 人工确认根因 |
| `correction` | jsonb | 否 | `{}` | - | 结构化纠正 |
| `create_experience` | boolean | 否 | false | INDEX | 是否请求形成经验 |
| `created_at` | timestamptz | 否 | now | INDEX | 时间 |

---

## 32. `experiences`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 经验 ID |
| `experience_key` | varchar(192) | 否 | - | UNIQUE | 稳定 key |
| `title` | varchar(255) | 否 | - | INDEX | 标题 |
| `domain` | varchar(64) | 否 | - | INDEX | 领域 |
| `status` | varchar(32) | 否 | `DISCOVERED` | INDEX | DISCOVERED/CONFIRMED/RULE_CANDIDATE/CODE_PENDING/SHADOW/CODE_ACTIVE/REJECTED/RETIRED |
| `source_type` | varchar(32) | 否 | - | INDEX | INVESTIGATION/FEEDBACK/LEARNING_EVENT |
| `source_risk_id` | UUID | 是 | null | FK, INDEX | 来源风险 |
| `source_investigation_id` | UUID | 是 | null | FK, INDEX | 来源调查 |
| `hypothesis` | text | 否 | `''` | - | 假设 |
| `conclusion` | text | 否 | - | - | 结论 |
| `applicable_scope` | jsonb | 否 | `{}` | - | 适用范围 |
| `trigger_conditions` | jsonb | 否 | `[]` | - | 触发条件 |
| `required_evidence` | jsonb | 否 | `[]` | - | 必需证据 |
| `tool_sequence` | jsonb | 否 | `[]` | - | 有效补查路径 |
| `human_summary` | text | 否 | `''` | - | 人工说明 |
| `support_count` | integer | 否 | 0 | - | 历史支持数 |
| `precision` | numeric(6,4) | 是 | null | - | Replay/Shadow 精度 |
| `code_status` | varchar(32) | 否 | `NOT_CODED` | INDEX | CODE_ACTIVE/PARTIAL_CODE/CODE_PENDING/SHADOW/NOT_CODED |
| `target_claim` | varchar(192) | 否 | `''` | INDEX | 希望替代 AI 的 Claim |
| `confirmed_at` | timestamptz | 是 | null | - | 人工确认时间 |
| `created_at` | timestamptz | 否 | now | - | 创建 |
| `updated_at` | timestamptz | 否 | now | - | 更新 |

---

## 33. `experience_evidence`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 关联 ID |
| `experience_id` | UUID | 否 | - | FK, INDEX | 经验 |
| `evidence_id` | UUID | 否 | - | FK, INDEX | 证据 |
| `relation` | varchar(32) | 否 | `SUPPORT` | INDEX | SUPPORT/COUNTEREXAMPLE/CONTEXT |
| `weight` | numeric(5,4) | 否 | 1 | - | 权重 |
| `created_at` | timestamptz | 否 | now | - | 创建 |

唯一：`(experience_id, evidence_id, relation)`。

---

## 34. `codeization_tasks`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 代码化任务 ID |
| `experience_id` | UUID | 否 | - | FK, INDEX | 来源经验 |
| `inspection_item_id` | UUID | 否 | - | FK, INDEX | 目标巡检项目 |
| `target_capability_id` | varchar(192) | 否 | - | INDEX | 未来 Capability ID |
| `task_type` | varchar(32) | 否 | - | INDEX | RULE/PLUGIN/NEW_DATA |
| `status` | varchar(32) | 否 | `CODE_PENDING` | INDEX | CODE_PENDING/DEVELOPING/SHADOW/CODE_ACTIVE/REJECTED |
| `title` | varchar(255) | 否 | - | - | 标题 |
| `target_claim` | varchar(192) | 否 | - | INDEX | 要解决的 Claim |
| `implementation_type` | varchar(16) | 否 | - | - | RULE/EXEC/REST/MCP |
| `specification` | jsonb | 否 | `{}` | - | 开发规格 |
| `owner` | varchar(128) | 否 | `''` | - | 工程负责人 |
| `historical_support` | integer | 否 | 0 | - | 历史支持数 |
| `precision` | numeric(6,4) | 是 | null | - | 验证精度 |
| `critical_false_positive` | integer | 否 | 0 | - | 严重误报数 |
| `shadow_cases` | integer | 否 | 0 | - | Shadow Case 数 |
| `started_at` | timestamptz | 是 | null | - | 开发开始 |
| `completed_at` | timestamptz | 是 | null | - | 代码激活 |
| `created_at` | timestamptz | 否 | now | - | 创建 |
| `updated_at` | timestamptz | 否 | now | - | 更新 |

---

## 35. `audit_events`

| 字段 | 类型 | Null | 默认 | 索引/约束 | 说明 |
|---|---|---:|---|---|---|
| `id` | UUID | 否 | uuid4 | PK | 审计事件 |
| `environment_id` | UUID | 是 | null | FK, INDEX | 环境 |
| `user_id` | bigint | 是 | null | FK auth_user, INDEX | 操作人 |
| `event_type` | varchar(64) | 否 | - | INDEX | 事件类型 |
| `object_type` | varchar(64) | 否 | - | INDEX | Risk/Capability/Feedback 等 |
| `object_id` | varchar(128) | 否 | - | INDEX | 对象 ID |
| `trace_id` | varchar(128) | 是 | null | INDEX | 链路 ID |
| `payload` | jsonb | 否 | `{}` | - | 非敏感审计数据 |
| `created_at` | timestamptz | 否 | now | INDEX | 时间 |

---

# 第三部分：API 设计

## 36. API 通用规范

Base URL：

```text
/api/v1
```

内部 Airflow/Plugin Stub：

```text
/api/internal/v1
```

统一错误：

```json
{
  "error": {
    "code": "CAPABILITY_NOT_READ_ONLY",
    "message": "LLM 只能调用只读巡检能力",
    "details": {
      "capability_id": "ops.restart.pod"
    },
    "trace_id": "tr_01..."
  }
}
```

分页：

```text
?page=1&page_size=50
```

响应：

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```


## 36.1 认证与权限约定

- `/api/v1/health`、`/api/v1/product-info`：本地开发允许匿名读取。
- 其余 `/api/v1/*`：默认使用 Django Session Authentication；后续生产可切换企业 OIDC，不改变业务接口。
- Capability 注册、版本激活、Codeization 状态推进：仅 `platform_admin`。
- 风险查看、AI 对话：`viewer` 及以上。
- 记录已处理、人工反馈：`operator` 及以上。
- `/api/internal/v1/*`：不接受普通 Session，必须携带内部 Token。

## 36.2 API 总索引

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/product-info` | 产品/版本信息 |
| GET | `/api/v1/dashboard/today` | 今日驾驶舱 |
| GET | `/api/v1/daily-snapshots` | 历史 Daily Snapshot |
| GET | `/api/v1/daily-snapshots/{id}` | 单日 Snapshot |
| GET | `/api/v1/inspection-items` | 巡检项目列表 |
| GET | `/api/v1/inspection-items/{id}` | 巡检项目详情 |
| POST | `/api/v1/inspection-items/{id}/ask` | 围绕巡检项发起 AI 对话 |
| POST | `/api/v1/inspection-runs/trigger` | 手工触发 Airflow |
| GET | `/api/v1/inspection-runs` | 巡检运行列表 |
| GET | `/api/v1/inspection-runs/{id}` | 巡检运行详情 |
| GET | `/api/v1/inspection-item-runs/{id}` | 单巡检项执行详情 |
| GET | `/api/v1/findings` | Finding 查询 |
| GET | `/api/v1/risks` | 风险列表 |
| GET | `/api/v1/risks/{id}` | 风险详情 |
| GET | `/api/v1/risks/{id}/timeline` | 风险生命周期 |
| GET | `/api/v1/risks/{id}/evidence` | 风险证据 |
| POST | `/api/v1/risks/{id}/mark-handled` | 记录已处理并进入待复验 |
| POST | `/api/v1/risks/{id}/ignore` | 忽略风险 |
| POST | `/api/v1/risks/{id}/reverify` | 手工复验 |
| POST | `/api/v1/risks/{id}/investigations` | 发起 AI 调查 |
| GET | `/api/v1/capabilities` | Capability 列表 |
| GET | `/api/v1/capabilities/{id}` | Capability 详情 |
| POST | `/api/v1/capabilities` | 注册 Capability |
| POST | `/api/v1/capabilities/{id}/versions` | 新建能力版本 |
| POST | `/api/v1/capabilities/{id}/versions/{version}/test` | 测试能力版本 |
| POST | `/api/v1/capabilities/{id}/versions/{version}/shadow` | 进入 Shadow |
| POST | `/api/v1/capabilities/{id}/versions/{version}/activate` | 激活能力版本 |
| POST | `/api/v1/capabilities/resolve` | 查询 Claim Resolver |
| POST | `/api/v1/conversations` | 创建会话 |
| GET | `/api/v1/conversations/{id}` | 会话详情 |
| GET | `/api/v1/conversations/{id}/messages` | 会话消息 |
| POST | `/api/v1/conversations/{id}/turns` | 发起一轮 LLM 交互 |
| GET | `/api/v1/conversations/{id}/turns/{turn_id}/events` | SSE 流 |
| POST | `/api/v1/conversations/{id}/close` | 关闭会话 |
| GET | `/api/v1/investigations/{id}` | 调查详情 |
| GET | `/api/v1/investigations/{id}/events` | 调查事件 |
| GET | `/api/v1/investigations/{id}/tool-calls` | Tool Call 列表 |
| POST | `/api/v1/investigations/{id}/cancel` | 取消调查 |
| POST | `/api/v1/feedback` | 提交人工反馈 |
| GET | `/api/v1/feedback` | 查询人工反馈 |
| POST | `/api/v1/feedback/{id}/create-experience` | 反馈转经验 |
| GET | `/api/v1/experiences` | 经验列表 |
| GET | `/api/v1/experiences/{id}` | 经验详情 |
| POST | `/api/v1/experiences/{id}/confirm` | 确认经验语义 |
| POST | `/api/v1/experiences/{id}/codeization-tasks` | 创建代码化任务 |
| GET | `/api/v1/codeization-tasks` | 代码化任务列表 |
| PATCH | `/api/v1/codeization-tasks/{id}` | 更新代码化任务 |
| POST | `/api/v1/mock-datasets/generate` | 生成模拟数据 |
| GET | `/api/v1/mock-datasets` | 模拟数据集列表 |
| GET | `/api/v1/mock-datasets/{id}` | 模拟数据集详情 |
| POST | `/api/internal/v1/mock/metrics/query` | 内部指标查询 |
| POST | `/api/internal/v1/mock/logs/search` | 内部日志查询 |
| POST | `/api/internal/v1/mock/events/query` | 内部事件查询 |
| POST | `/api/internal/v1/mock/topology/query` | 内部拓扑查询 |
| POST | `/api/internal/v1/batch/datasets` | Airflow 生成数据集 |
| POST | `/api/internal/v1/batch/inspection-runs` | Airflow 创建巡检 Run |
| POST | `/api/internal/v1/batch/inspection-runs/{id}/execute` | 执行确定性巡检 |
| POST | `/api/internal/v1/batch/inspection-runs/{id}/correlate-risks` | 风险关联 |
| POST | `/api/internal/v1/batch/inspection-runs/{id}/reverify` | 风险复验 |
| POST | `/api/internal/v1/batch/inspection-runs/{id}/snapshot` | 生成 Snapshot |
| POST | `/api/internal/v1/batch/inspection-runs/{id}/complete` | 完成 Run |

## 37. 错误码

| HTTP | code | 含义 |
|---:|---|---|
| 400 | `VALIDATION_ERROR` | 请求参数不合法 |
| 401 | `AUTH_REQUIRED` | 未登录 |
| 403 | `CAPABILITY_NOT_READ_ONLY` | LLM 请求写能力 |
| 403 | `PERMISSION_DENIED` | 用户无权限 |
| 404 | `NOT_FOUND` | 对象不存在 |
| 409 | `INVALID_RISK_TRANSITION` | 风险状态不允许跳转 |
| 409 | `CAPABILITY_NOT_ACTIVE` | 能力未激活 |
| 409 | `DATASET_NOT_READY` | 模拟数据未生成完成 |
| 409 | `INVESTIGATION_LIMIT_REACHED` | 调查轮数/工具次数超限 |
| 422 | `STRUCTURED_OUTPUT_INVALID` | LLM 结构化输出无法校验 |
| 429 | `LLM_BUDGET_EXCEEDED` | LLM 预算超限 |
| 502 | `AIRFLOW_TRIGGER_FAILED` | Airflow 调度失败 |
| 503 | `LLM_UNAVAILABLE` | Ollama/模型不可用 |
| 504 | `TOOL_TIMEOUT` | 插件超时 |

---

## 38. 健康与产品说明 API

### `GET /api/v1/health`

响应：

```json
{
  "status": "ok",
  "database": "ok",
  "ollama": "ok",
  "airflow": "ok",
  "version": "0.1.0"
}
```

### `GET /api/v1/product-info`

返回产品说明页面需要的版本、当前数据源模式、安全边界。

```json
{
  "product_name": "IaaS 智能巡检",
  "data_mode": "MOCK",
  "llm_provider": "ollama",
  "security_mode": "READ_ONLY_TOOLS",
  "versions": {
    "django": "4.2.16",
    "airflow": "2.3.2",
    "langgraph": "1.2.10",
    "langchain": "1.3.14"
  }
}
```

---

## 39. Daily Snapshot / Dashboard API

### `GET /api/v1/dashboard/today?environment=dev`

返回首页聚合数据：

```json
{
  "snapshot": {
    "date": "2026-08-23",
    "p1_count": 1,
    "p2_count": 3,
    "new_count": 5,
    "worsened_count": 2,
    "pending_action_count": 4,
    "pending_reverify_count": 1,
    "code_coverage_rate": 90.5,
    "ai_displacement_rate": 42.1,
    "data_completeness_rate": 99.4
  },
  "top_risks": [],
  "yesterday_diff": {},
  "trend_7d": [],
  "capability_maturity": {}
}
```

### `GET /api/v1/daily-snapshots`

Query：`environment`、`date_from`、`date_to`。

### `GET /api/v1/daily-snapshots/{snapshot_id}`

返回单日详情。

---

## 40. 巡检项目 API

### `GET /api/v1/inspection-items`

过滤：

```text
?domain=LLM
?execution_mode=CODE_FIRST_AI_FALLBACK
?code_status=PARTIAL_CODE
?ai_dependent=true
?enabled=true
```

每项必须返回：

```json
{
  "id": "...",
  "code": "llm.performance",
  "name": "LLM 推理性能巡检",
  "execution_mode": "CODE_FIRST_AI_FALLBACK",
  "code_status": "PARTIAL_CODE",
  "code_coverage_percent": 78.0,
  "resolved_claims": ["performance.status"],
  "llm_responsibilities": [
    "未知性能退化原因分类",
    "未知证据路径探索"
  ]
}
```

### `GET /api/v1/inspection-items/{id}`

同时返回绑定 Capability。

### `POST /api/v1/inspection-items/{id}/ask`

快捷创建绑定巡检项目的 Conversation。

请求：

```json
{
  "message": "这个巡检现在还有哪些部分依赖 LLM？"
}
```

响应 `201`：

```json
{
  "conversation_id": "...",
  "turn_id": "...",
  "events_url": "/api/v1/conversations/.../turns/.../events"
}
```

---

## 41. 巡检运行 API

### `POST /api/v1/inspection-runs/trigger`

用途：用户手工触发 Airflow DAG。

请求：

```json
{
  "environment_id": "...",
  "run_date": "2026-08-23",
  "scenario": "llm_scheduler_pressure",
  "seed": 20260823
}
```

响应 `202`：

```json
{
  "dag_id": "daily_iaas_inspection",
  "dag_run_id": "manual__2026-08-23T04:30:00+00:00",
  "status": "QUEUED"
}
```

### `GET /api/v1/inspection-runs`

过滤：`environment_id`、`run_date`、`status`。

### `GET /api/v1/inspection-runs/{id}`

返回运行摘要及 Item Runs。

### `GET /api/v1/inspection-item-runs/{id}`

返回 Findings、AI Admission、统计。

### `GET /api/v1/findings`

过滤：`run_id`、`item_run_id`、`risk_id`、`finding_code`。

---

## 42. 风险 API

### `GET /api/v1/risks`

过滤：

```text
?severity=P1,P2
?status=PENDING_ACTION
?domain=LLM
?change=NEW
?ai_involved=true
?inspection_item_id=...
```

### `GET /api/v1/risks/{risk_id}`

返回：当前状态、影响、建议、代码化方式、最近调查摘要。

### `GET /api/v1/risks/{risk_id}/timeline`

响应：

```json
{
  "risk_id": "...",
  "events": [
    {
      "at": "2026-08-20T07:10:00+08:00",
      "type": "STATUS_CHANGE",
      "to_status": "NEW",
      "label": "首次发现"
    }
  ]
}
```

### `GET /api/v1/risks/{risk_id}/evidence`

参数：`type`、`limit`。

### `POST /api/v1/risks/{risk_id}/mark-handled`

含义：人工说明已经执行处置，系统进入待复验。

请求：

```json
{
  "comment": "已调整 scheduler worker 配置",
  "external_ticket": "CHG-20260823-001"
}
```

响应：

```json
{
  "risk_id": "...",
  "status": "PENDING_REVERIFY"
}
```

**禁止直接设置 RECOVERED。**

### `POST /api/v1/risks/{risk_id}/ignore`

请求需 `reason`，状态进入 `IGNORED`。

### `POST /api/v1/risks/{risk_id}/reverify`

手工立即发起复验，不等待下一日 DAG。

响应 `202`。

### `POST /api/v1/risks/{risk_id}/investigations`

请求：

```json
{
  "trigger_type": "HUMAN",
  "question": "为什么 GPU 利用率下降但 TTFT 上升？"
}
```

返回 investigation + conversation。

---

## 43. Capability Registry API

### `GET /api/v1/capabilities`

过滤：`domain`、`status`、`implementation_type`、`resolves`、`read_only`。

### `GET /api/v1/capabilities/{capability_id}`

返回当前版本、历史版本、绑定巡检项目。

### `POST /api/v1/capabilities`

平台管理员创建能力元数据。

请求：

```json
{
  "capability_id": "network.rx_path.pressure",
  "name": "RX Path Pressure Resolver",
  "domain": "network",
  "description": "分析 rx_missed/softirq/ring fill",
  "read_only": true
}
```

### `POST /api/v1/capabilities/{capability_id}/versions`

请求：

```json
{
  "version": "0.9.0",
  "implementation_type": "EXEC",
  "status": "CANDIDATE",
  "semantic_tags": ["network", "rx", "packet_loss"],
  "subjects": ["host"],
  "resolves": ["network.packet_loss.cause_category"],
  "input_schema": {
    "type": "object",
    "required": ["asset_id", "start_time", "end_time"]
  },
  "output_schema": {"type": "object"},
  "script_path": "plugins/exec/check_rx_path.py",
  "timeout_seconds": 15,
  "retry_count": 1
}
```

### `POST /api/v1/capabilities/{capability_id}/versions/{version}/test`

仅使用模拟数据执行测试。

### `POST /api/v1/capabilities/{capability_id}/versions/{version}/shadow`

进入 SHADOW。

### `POST /api/v1/capabilities/{capability_id}/versions/{version}/activate`

要求：

- `read_only=true`；
- Schema 校验通过；
- 达到演示阈值；
- 具有平台管理员权限。

### `POST /api/v1/capabilities/resolve`

开发/诊断接口。

请求：

```json
{
  "claim": "llm.performance.degradation_category",
  "subject_type": "llm_instance",
  "tags": ["scheduler", "latency"]
}
```

返回候选 Resolver 排序。

---

## 44. Conversation / LLM API

### `POST /api/v1/conversations`

请求：

```json
{
  "context_type": "RISK",
  "context_id": "<risk_uuid>",
  "title": "分析 LLM 推理时延风险"
}
```

### `GET /api/v1/conversations/{conversation_id}`

返回会话元数据。

### `GET /api/v1/conversations/{conversation_id}/messages`

按时间返回消息。

### `POST /api/v1/conversations/{conversation_id}/turns`

创建一轮对话并异步/线程内运行 Investigation Graph。

请求：

```json
{
  "message": "GPU 利用率下降但 TTFT 上涨，继续帮我确认原因",
  "allow_tools": true
}
```

响应 `202`：

```json
{
  "turn_id": "turn_...",
  "investigation_id": "...",
  "events_url": "/api/v1/conversations/<id>/turns/<turn_id>/events"
}
```

### `GET /api/v1/conversations/{conversation_id}/turns/{turn_id}/events`

`Content-Type: text/event-stream`

事件定义见第 47 节。

### `POST /api/v1/conversations/{conversation_id}/close`

关闭会话，不删除历史。

---

## 45. Investigation API

### `GET /api/v1/investigations/{id}`

返回：状态、entry_reason、missing_claim、结论、预算、已用工具。

### `GET /api/v1/investigations/{id}/events`

非 SSE 的完整事件查询，用于刷新恢复。

### `GET /api/v1/investigations/{id}/tool-calls`

返回工具调用。

### `POST /api/v1/investigations/{id}/cancel`

只允许 CREATED/RUNNING。

---

## 46. Human Feedback API

### `POST /api/v1/feedback`

请求：

```json
{
  "risk_id": "...",
  "investigation_id": "...",
  "conversation_id": "...",
  "message_id": "...",
  "feedback_type": "CONFIRMED_ROOT_CAUSE",
  "rating": 5,
  "comment": "现场验证 scheduler worker starvation 与结论一致",
  "confirmed_conclusion": "SCHEDULER_PRESSURE",
  "correction": {},
  "create_experience": true
}
```

响应：

```json
{
  "feedback_id": "...",
  "experience_created": true,
  "experience_id": "..."
}
```

### `GET /api/v1/feedback`

过滤：`risk_id`、`investigation_id`、`feedback_type`。

### `POST /api/v1/feedback/{id}/create-experience`

当原反馈未立即创建经验时手工转换。

---

## 47. SSE 事件协议

统一结构：

```text
id: 12
event: tool.completed
data: {"investigation_id":"...","tool_call_id":"..."}

```

事件类型：

| event | 说明 |
|---|---|
| `turn.started` | 开始一轮 |
| `context.ready` | 上下文压缩完成 |
| `assistant.delta` | 文本增量，可选 |
| `hypothesis.created` | 新假设 |
| `tool.requested` | LLM 请求能力 |
| `tool.started` | 工具开始 |
| `tool.completed` | 工具成功 |
| `tool.failed` | 工具失败 |
| `evidence.created` | 新 Evidence 落库 |
| `validator.result` | 代码验证结果 |
| `assistant.final` | 结构化最终回答 |
| `turn.completed` | 完成 |
| `turn.error` | 本轮失败 |
| `heartbeat` | 长任务保活 |

`assistant.final`：

```json
{
  "summary": "调度器排队压力是当前最可能原因",
  "current_conclusion": "SCHEDULER_PRESSURE",
  "confidence": 0.86,
  "confirmed_facts": [
    "TTFT P95 410ms -> 690ms",
    "GPU Util 72% -> 43%",
    "Request Rate 稳定"
  ],
  "hypotheses": [],
  "new_evidence": [],
  "recommended_next_steps": ["检查 scheduler worker 配置"],
  "unresolved_questions": []
}
```

SSE 恢复：客户端发送 `Last-Event-ID`，服务端从 `investigation_events.sequence` 继续输出。

---

## 48. Experience / Codeization API

### `GET /api/v1/experiences`

过滤：`status`、`domain`、`code_status`、`target_claim`。

### `GET /api/v1/experiences/{id}`

返回来源 Risk、Evidence、Feedback、代码化状态。

### `POST /api/v1/experiences/{id}/confirm`

人工确认经验语义，不代表生产变更审批。

请求：

```json
{
  "human_summary": "RX Path Pressure 模式可复现",
  "target_claim": "network.packet_loss.cause_category"
}
```

### `POST /api/v1/experiences/{id}/codeization-tasks`

请求：

```json
{
  "inspection_item_id": "...",
  "target_capability_id": "network.rx_path.pressure",
  "task_type": "PLUGIN",
  "implementation_type": "EXEC",
  "target_claim": "network.packet_loss.cause_category"
}
```

### `GET /api/v1/codeization-tasks`

过滤状态。

### `PATCH /api/v1/codeization-tasks/{id}`

允许更新 `owner`、`status`、验证指标；状态跳转由服务层校验。

---

## 49. Mock Data API

### `POST /api/v1/mock-datasets/generate`

请求：

```json
{
  "environment_id": "...",
  "scenario": "network_rx_pressure",
  "dataset_date": "2026-08-23",
  "seed": 20260823,
  "config": {
    "host_count": 20,
    "duration_minutes": 120
  }
}
```

### `GET /api/v1/mock-datasets`

### `GET /api/v1/mock-datasets/{id}`

返回数据计数和场景配置，不默认返回全部原始点。

---

## 50. 内部 Mock Query API（供 REST Plugin）

必须校验 `X-Internal-Token`。

### `POST /api/internal/v1/mock/metrics/query`

```json
{
  "dataset_id": "...",
  "asset_ids": ["..."],
  "metric_names": ["llm_ttft_p95", "scheduler_queue_ratio"],
  "start_time": "...",
  "end_time": "...",
  "aggregation": "avg"
}
```

### `POST /api/internal/v1/mock/logs/search`

```json
{
  "dataset_id": "...",
  "asset_ids": ["..."],
  "sources": ["runtime"],
  "query": "scheduler starvation",
  "start_time": "...",
  "end_time": "...",
  "limit": 50
}
```

### `POST /api/internal/v1/mock/events/query`

### `POST /api/internal/v1/mock/topology/query`

以上接口只返回有限窗口和有限条数。

---

## 51. Airflow 内部编排 API

所有请求头：

```text
X-Airflow-Token: <AIRFLOW_INTERNAL_TOKEN>
```

### `POST /api/internal/v1/batch/datasets`

生成数据集；返回 `dataset_id`。

### `POST /api/internal/v1/batch/inspection-runs`

创建 Run；请求含 `dataset_id/run_date/environment_id/dag_run_id`。

### `POST /api/internal/v1/batch/inspection-runs/{id}/execute`

执行所有启用巡检项的确定性阶段。

### `POST /api/internal/v1/batch/inspection-runs/{id}/correlate-risks`

执行 Fingerprint、Risk Observation、状态演进。

### `POST /api/internal/v1/batch/inspection-runs/{id}/reverify`

只处理 `PENDING_REVERIFY` 风险。

### `POST /api/internal/v1/batch/inspection-runs/{id}/snapshot`

生成 Daily Snapshot。

### `POST /api/internal/v1/batch/inspection-runs/{id}/complete`

汇总并完成 Run。

Airflow Task 只调用这些 API，不 import Django Models。

---

# 第四部分：LLM 与 Tool Calling 实现

## 52. Ollama Provider

为降低对特定模型“原生 function calling”能力的依赖，第一阶段采用**应用层结构化动作协议**。

LLM 每次返回两种动作之一：

```json
{
  "action": "FINAL",
  "answer": {
    "summary": "...",
    "confidence": 0.8
  }
}
```

或：

```json
{
  "action": "CALL_TOOL",
  "tool": {
    "capability_id": "llm.scheduler.pressure",
    "arguments": {
      "asset_id": "...",
      "start_time": "...",
      "end_time": "..."
    },
    "reason": "需要确认 scheduler queue ratio"
  }
}
```

执行流程：

1. Pydantic/Schema 校验结构；
2. Registry 查能力；
3. `read_only` 安全门；
4. input_schema 校验；
5. 执行 Tool；
6. output_schema 校验；
7. 压缩成 Evidence；
8. 返回 Graph 下一轮。

这样即使 Ollama 模型不支持标准 function calling，也能演示完整 Agent Tool Loop。

## 53. Ollama HTTP

`POST ${OLLAMA_BASE_URL}/api/chat`

请求示意：

```json
{
  "model": "qwen3:8b",
  "stream": false,
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "format": "json"
}
```

Provider 负责：

- timeout；
- 健康检查；
- JSON 解析；
- 模型元数据；
- Token 字段可用则记录，不可用时保存 0/估算来源；
- 不把 Ollama URL 暴露给 Agent State。

---

# 第五部分：Airflow DAG

## 54. `daily_iaas_inspection.py`

DAG 参数：

```python
DAG_ID = "daily_iaas_inspection"
SCHEDULE = os.getenv("INSPECTION_DAG_SCHEDULE", "0 7 * * *")
```

Task：

```text
generate_dataset
  ↓
create_run
  ↓
execute_inspections
  ↓
correlate_risks
  ↓
reverify_pending_risks
  ↓
build_snapshot
  ↓
complete_run
```

每个 Task 用 `requests` 调 Django internal API，XCom 仅保存 UUID 和少量状态，不保存模拟数据。

### 幂等

- `dataset`: environment + date + seed + scenario 可查重；
- `inspection_run`: dag_run_id 幂等；
- `risk_observation`: risk_id + inspection_run_id 唯一；
- `daily_snapshot`: environment + date 唯一。

---

# 第六部分：前端与产品说明页面

## 55. 页面

### `/`

每日巡检驾驶舱。

### `/risks`

风险中心。

### `/risks/{id}`

风险详情，右侧或完整页；包含 `[询问 AI]`。

### `/capabilities`

巡检能力 / 插件中心。

### `/evolution`

AI → Code 能力演进。

### `/experiences`

规则与经验。

### `/ai-runtime`

LLM 健康、调查次数、工具调用、Helpful Rate。

### `/about`

产品说明页面。

## 56. 产品说明页面必须包含

- 产品一句话定义；
- 每日巡检流程；
- 风险生命周期；
- Code-first / AI-on-demand；
- “为什么某些巡检依赖 LLM”；
- 代码化程度；
- Capability Registry；
- AI → Experience → Code；
- 人工反馈作用；
- 自动复验；
- Demo 模拟数据声明；
- Ollama 本地模型说明；
- 安全边界；
- 关键术语 Glossary；
- 当前固定版本。

---

# 第七部分：实施任务计划

## Task 1: 基础工程、版本和双虚拟环境

**Files:**
- Create: `requirements/web.txt`
- Create: `requirements/web-dev.txt`
- Create: `requirements/airflow.txt`
- Create: `.env.example`
- Create: `config/settings/base.py`
- Create: `config/settings/dev.py`
- Test: `tests/test_version_constraints.py`

**Interfaces:**
- Produces: 可启动 Django 4.2.16 的 Web Runtime；独立 Airflow 2.3.2 安装说明。

- [ ] **Step 1: 写版本失败测试**

```python
from importlib.metadata import version
import django

def test_pinned_runtime_versions():
    assert django.get_version() == "4.2.16"
    assert version("langgraph") == "1.2.10"
    assert version("langchain") == "1.3.14"
```

- [ ] **Step 2: 运行并确认因依赖未安装/版本不符失败**

```bash
pytest tests/test_version_constraints.py -q
```

- [ ] **Step 3: 创建 `.venv-web` 并安装 `requirements/web.txt`**

- [ ] **Step 4: 再运行版本测试并通过**

- [ ] **Step 5: 独立创建 `.venv-airflow`，用官方 constraints 安装 Airflow 2.3.2**

- [ ] **Step 6: 验证**

```bash
.venv-airflow/bin/airflow version
```

期望：`2.3.2`。

---

## Task 2: PostgreSQL Docker 与 Django 数据库连通

**Files:**
- Create: `docker-compose.yml`
- Create: `docker/postgres/init-multiple-dbs.sh`
- Modify: `config/settings/dev.py`
- Test: `tests/integration/test_database_health.py`

- [ ] 写测试：Django `SELECT 1` 成功并能创建 Environment。
- [ ] 在 PostgreSQL 未启动时验证测试失败。
- [ ] `docker compose up -d postgres`。
- [ ] 执行 migrations。
- [ ] 验证测试通过。

---

## Task 3: 核心模型与 migrations

**Files:**
- Create/Modify: `apps/*/models.py`
- Create: 各 app migrations
- Test: `tests/domain/test_models.py`

- [ ] 先测试 `inspection_item` 必须保存执行模式和代码化状态。
- [ ] 测试 Risk fingerprint 在同一 Environment 内唯一。
- [ ] 测试 `risk_observation` 对 `(risk, run)` 唯一。
- [ ] 测试 Capability Version 版本唯一。
- [ ] 测试 Human Feedback 可以关联 Message/Investigation/Risk。
- [ ] 实现模型和迁移。
- [ ] 执行 `python manage.py makemigrations --check` 和全量模型测试。

---

## Task 4: 模拟数据生成器

**Files:**
- Create: `services/mock_generator/generator.py`
- Create: `services/mock_generator/scenarios.py`
- Create: `apps/mockdata/services.py`
- Test: `tests/services/test_mock_generator.py`

- [ ] 测试相同 seed + scenario 产生相同关键点。
- [ ] 测试 `llm_scheduler_pressure` 产生 TTFT 上升、Queue 上升、GPU Util 下降。
- [ ] 测试 `control_plane_anti_affinity` 产生确定性拓扑风险。
- [ ] 测试 `data_incomplete` 缺少必要数据。
- [ ] 实现最小生成器。
- [ ] 把结果写入 mock_* 表。

---

## Task 5: Capability Registry 与插件执行器

**Files:**
- Create: `services/plugin_runtime/registry.py`
- Create: `services/plugin_runtime/executor.py`
- Create: `services/plugin_runtime/rule_executor.py`
- Create: `services/plugin_runtime/exec_executor.py`
- Create: `services/plugin_runtime/rest_executor.py`
- Create: `services/plugin_runtime/mcp_executor.py`
- Test: `tests/services/test_capability_registry.py`
- Test: `tests/services/test_plugin_security.py`

- [ ] 测试按 Claim 找到 CODE_ACTIVE Resolver。
- [ ] 测试 SHADOW 不能作为正式 Code Resolver，但可被 Shadow Runner 使用。
- [ ] 测试 LLM 调用 `read_only=false` 被拒绝。
- [ ] 测试 EXEC 非白名单路径被拒绝。
- [ ] 测试 input_schema 不匹配被拒绝。
- [ ] 实现 Registry 与 Executor。

---

## Task 6: 巡检执行与 Deterministic Coverage

**Files:**
- Create: `apps/inspections/services/execution.py`
- Create: `apps/inspections/services/coverage.py`
- Create: `apps/inspections/services/findings.py`
- Test: `tests/domain/test_inspection_execution.py`

- [ ] 测试控制面反亲和全部由 CODE_ONLY 结束。
- [ ] 测试 LLM 性能项目只留下 `degradation_category` Claim Gap。
- [ ] 测试 data_incomplete 不进入 AI。
- [ ] 保存 InspectionItemRun 和 Findings。

---

## Task 7: Risk Lifecycle、Fingerprint 和自动复验

**Files:**
- Create: `apps/risks/services/correlation.py`
- Create: `apps/risks/services/lifecycle.py`
- Create: `apps/risks/services/reverify.py`
- Test: `tests/domain/test_risk_lifecycle.py`

- [ ] 测试连续两天同一风险获得相同 risk_id。
- [ ] 测试 severity 提升进入 WORSENED。
- [ ] 测试 `mark_handled()` 只能进入 PENDING_REVERIFY。
- [ ] 测试复验成功才进入 RECOVERED。
- [ ] 测试复验失败回到 PERSISTING/WORSENED。

---

## Task 8: Daily Snapshot

**Files:**
- Create: `apps/inspections/services/snapshot.py`
- Test: `tests/domain/test_daily_snapshot.py`

- [ ] 测试新增/恢复/待处置统计。
- [ ] 测试 code_only_cases 与 ai_dependent_cases。
- [ ] 测试 code_coverage_rate 和 ai_displacement_rate。
- [ ] 写入 `daily_snapshots`。

---

## Task 9: Airflow 2.3.2 DAG 与内部批处理 API

**Files:**
- Create: `airflow/dags/daily_iaas_inspection.py`
- Create: `apps/inspections/api_internal.py`
- Create: `apps/inspections/internal_urls.py`
- Test: `tests/api/test_internal_batch_api.py`
- Test: `tests/integration/test_airflow_dag_structure.py`

- [ ] 测试无 `X-Airflow-Token` 返回 403。
- [ ] 测试每个批处理阶段幂等。
- [ ] 测试 DAG task dependency 顺序。
- [ ] Airflow 只通过 HTTP 调 Django。
- [ ] 手工 `airflow dags test daily_iaas_inspection <date>` 验证。

---

## Task 10: Model Gateway 与 Ollama

**Files:**
- Create: `services/model_gateway/base.py`
- Create: `services/model_gateway/ollama.py`
- Create: `services/model_gateway/openai_compatible.py`
- Test: `tests/services/test_model_gateway.py`

- [ ] 测试 Ollama 健康失败转换成 `LLM_UNAVAILABLE`。
- [ ] 测试 JSON action 解析。
- [ ] 测试非法 action 被 `STRUCTURED_OUTPUT_INVALID` 拒绝。
- [ ] 实现 `/api/chat` HTTP Provider。
- [ ] 模型名和 base URL 只能来自配置。

---

## Task 11: LangGraph Investigation Graph

**Files:**
- Create: `services/investigation_graph/state.py`
- Create: `services/investigation_graph/schemas.py`
- Create: `services/investigation_graph/nodes.py`
- Create: `services/investigation_graph/graph.py`
- Test: `tests/services/test_investigation_graph.py`

- [ ] 测试可直接回答时不调用 Tool。
- [ ] 测试 Claim Gap 时选择只读 Capability。
- [ ] 测试 tool result 生成 Evidence。
- [ ] 测试 max_rounds=3 强制停止。
- [ ] 测试 max_tool_calls=5 强制停止。
- [ ] 测试最终结构包含 summary/conclusion/facts/next_steps。

---

## Task 12: Conversation + SSE 恢复

**Files:**
- Create: `apps/conversations/views.py`
- Create: `apps/conversations/services.py`
- Create: `apps/conversations/sse.py`
- Test: `tests/api/test_conversation_api.py`
- Test: `tests/api/test_sse_resume.py`

- [ ] 测试创建绑定 Risk 的 Conversation。
- [ ] 测试一轮对话创建 USER Message 和 Investigation。
- [ ] 测试 SSE 顺序与 sequence 持久化。
- [ ] 测试 `Last-Event-ID` 可恢复。
- [ ] 测试刷新页面后消息仍从 PostgreSQL 恢复。

---

## Task 13: 人工反馈与 Experience-to-Code

**Files:**
- Create: `apps/feedback/services.py`
- Create: `apps/experiences/services.py`
- Create: `apps/experiences/codeization.py`
- Test: `tests/domain/test_feedback_experience.py`

- [ ] 测试 HELPFUL 只保存反馈。
- [ ] 测试 CONFIRMED_ROOT_CAUSE + create_experience 创建 DISCOVERED Experience。
- [ ] 测试 Experience confirm 后可创建 CodeizationTask。
- [ ] 测试状态 `CODE_PENDING → SHADOW → CODE_ACTIVE`。
- [ ] 测试 CODE_ACTIVE Capability 生效后 Registry Resolver 优先于 AI。

---

## Task 14: Public REST API

**Files:**
- Create/Modify: 各 app `serializers.py`、`views.py`、`urls.py`
- Modify: `config/urls.py`
- Test: `tests/api/`

- [ ] 按第 38~49 节逐一写 API contract test。
- [ ] 所有写 API 生成 AuditEvent。
- [ ] 所有枚举和错误码固定。
- [ ] OpenAPI/接口文档与实际 serializer 一致。

---

## Task 15: Web UI 与产品说明页面

**Files:**
- Create: `templates/app.html`
- Create: `templates/product_about.html`
- Create: `static/js/*.js`
- Create: `static/css/app.css`
- Test: `tests/api/test_web_pages.py`

- [ ] 首页默认不显示 Raw JSON/Prompt/Tool 参数。
- [ ] 风险详情可以打开 AI 对话 Drawer。
- [ ] Tool Call 默认显示摘要，详细输入输出折叠。
- [ ] 巡检能力页明确显示代码化和 LLM 职责。
- [ ] 能力演进页显示 AI Displacement Rate。
- [ ] 产品说明页覆盖第 56 节全部内容。

---

## Task 16: Demo Seed、Bootstrap 和验收数据

**Files:**
- Create: `apps/core/management/commands/bootstrap_demo.py`
- Create: `apps/core/management/commands/generate_demo_history.py`
- Test: `tests/integration/test_bootstrap_demo.py`

- [ ] 创建默认 Environment。
- [ ] 创建至少 7 个 Inspection Item。
- [ ] 创建 CODE_ONLY/PARTIAL_CODE/CODE_PENDING/SHADOW 示例。
- [ ] 注册至少 6 个 Capability。
- [ ] 生成至少 7 天历史 Snapshot。
- [ ] 确保首页第一次启动即有数据可看。

---

## Task 17: 安全与审计回归

**Files:**
- Test: `tests/security/test_tool_permissions.py`
- Test: `tests/security/test_exec_whitelist.py`
- Test: `tests/security/test_internal_api_token.py`
- Test: `tests/security/test_secret_leakage.py`

- [ ] 非只读 Capability 无法被 Investigation 调用。
- [ ] EXEC 路径逃逸测试失败。
- [ ] Internal API Token 缺失/错误返回 403。
- [ ] Ollama Prompt/Event/Audit 不包含 DB password 和内部 token。

---

## Task 18: 完整文档和最终验收

**Files:**
- Create: `README.md`
- Create: `docs/api.md`
- Create: `docs/database.md`
- Create: `docs/product.md`

- [ ] README 给出 10 分钟本地启动路径。
- [ ] `docs/api.md` 与本文件 API 清单一致。
- [ ] `docs/database.md` 与 migrations/model 字段一致。
- [ ] 产品页面与 `docs/product.md` 术语一致。
- [ ] 执行全量测试。

```bash
.venv-web/bin/pytest -q
.venv-web/bin/python manage.py check
.venv-web/bin/python manage.py makemigrations --check
.venv-airflow/bin/airflow dags list
```

---

# 第八部分：本地开发启动步骤

## 57. 启动 PostgreSQL

```bash
docker compose up -d postgres
docker compose ps
```

## 58. Web Runtime

```bash
python3.10 -m venv .venv-web
source .venv-web/bin/activate
pip install -r requirements/web.txt
pip install -r requirements/web-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py bootstrap_demo
python manage.py generate_demo_history --days 7 --seed 20260823
python manage.py runserver 0.0.0.0:8000
```

## 59. Ollama

```bash
ollama serve
ollama pull qwen3:8b
```

模型名称通过 `.env` 修改。

## 60. Airflow Runtime

```bash
python3.10 -m venv .venv-airflow
source .venv-airflow/bin/activate
# 按 Task 1 使用 Airflow 2.3.2 官方 constraints 安装
export AIRFLOW_HOME="$PWD/.airflow"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://inspection:inspection_dev@127.0.0.1:5432/airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$PWD/airflow/dags"
airflow db init
airflow users create --username admin --firstname Local --lastname Admin --role Admin --email local@example.com --password admin
airflow webserver --port 8080
airflow scheduler
```

## 61. 首次手工巡检

```bash
curl -X POST http://127.0.0.1:8000/api/v1/inspection-runs/trigger \
  -H 'Content-Type: application/json' \
  -d '{
    "environment_id":"<uuid>",
    "run_date":"2026-08-23",
    "scenario":"llm_scheduler_pressure",
    "seed":20260823
  }'
```

---

# 第九部分：验收场景

## 62. 场景 A：纯代码巡检

控制面反亲和：

```text
Mock Topology
→ Placement Capability
→ Finding
→ Risk
→ CODE_ONLY
→ AI 不准入
```

验收：Tool Call = 0，LLM 调用 = 0。

## 63. 场景 B：Code-first + AI 补充

LLM 推理性能：

```text
TTFT ↑ / Queue ↑ / GPU ↓
→ Code 确认 DEGRADED
→ degradation_category Claim Gap
→ 用户点击询问 AI
→ Ollama 请求 llm.scheduler.pressure
→ Registry 验证 read_only
→ Tool 返回 scheduler_queue_ratio=2.15
→ Evidence
→ Conclusion SCHEDULER_PRESSURE
→ 用户确认根因
→ Experience DISCOVERED
```

## 64. 场景 C：人工反馈形成代码化任务

```text
CONFIRMED_ROOT_CAUSE
→ create_experience=true
→ Experience
→ confirm
→ CodeizationTask CODE_PENDING
→ 创建 Capability 0.9.0
→ SHADOW
→ 达阈值
→ ACTIVE
→ Inspection Item resolved_claims 更新
→ code_coverage_percent 上升
→ 同类 Case 不再进入 AI
```

## 65. 场景 D：处置和复验

```text
Risk LOCATED
→ 用户“记录已处理”
→ PENDING_REVERIFY
→ 下一轮同巡检项目执行
→ Finding 消失
→ RECOVERED
```

如果 Finding 仍存在：返回 PERSISTING 或 WORSENED，不能错误关闭。

---

# 第十部分：最终 Definition of Done

- [ ] Django 实际版本为 4.2.16。
- [ ] Airflow 实际版本为 2.3.2，运行在独立环境。
- [ ] LangGraph 实际版本为 1.2.10。
- [ ] LangChain 实际版本为 1.3.14。
- [ ] PostgreSQL 由 Docker 启动且应用/Airflow 使用独立数据库。
- [ ] 模拟数据可复现。
- [ ] Daily DAG 可运行并生成 Snapshot。
- [ ] 风险跨天稳定关联。
- [ ] 待处置/待复验/恢复闭环可演示。
- [ ] 巡检项目明确显示代码化程度和 LLM 职责。
- [ ] Capability Registry 支持 RULE/EXEC/REST/MCP Manifest。
- [ ] LLM 只允许只读 Tool Call。
- [ ] Ollama 可以完成风险上下文对话。
- [ ] Tool Call、Evidence、Message、Feedback 全部写 PostgreSQL。
- [ ] 用户刷新页面后会话和调查历史可以恢复。
- [ ] 人工确认根因可以形成 Experience。
- [ ] Experience 可以进入 CODE_PENDING/SHADOW/CODE_ACTIVE 演示链路。
- [ ] CODE_ACTIVE Resolver 能替代同 Claim 的 AI 调查。
- [ ] 产品说明页面完成。
- [ ] API 文档覆盖本文件所有公开和内部接口。
- [ ] 数据库文档覆盖本文件所有表和字段。
- [ ] 安全回归测试通过。
- [ ] 全量测试通过。
