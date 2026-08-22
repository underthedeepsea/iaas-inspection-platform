# IaaS 智能巡检平台详细设计文档 v1

> 基于 Demo v4.1 的“风险闭环 + 插件化自进化”设计扩展为可本地开发、可持续演进的产品级架构。
>
> 核心原则：**Code-first、AI-on-demand、Experience-to-Code、Risk Lifecycle、Plugin-first Capability Registry**。

---

## 1. 文档目标

本文档用于指导 IaaS 智能巡检平台第一阶段产品化开发，覆盖：

- 每日自动巡检与 Daily Snapshot；
- 风险跨天生命周期；
- 插件式巡检能力与 Capability Registry；
- “已代码化 / 部分代码化 / LLM 依赖 / 待代码化 / Shadow”成熟度管理；
- 运维人员与 LLM 围绕具体风险、巡检项进行上下文交互；
- LLM 主动调用只读巡检插件补充证据；
- 人工反馈进入 Experience-to-Code 闭环；
- PostgreSQL 持久化；
- 本地 Docker PostgreSQL；
- 本地 Ollama LLM；
- Airflow 每日批量编排；
- 模拟巡检数据替代真实生产数据源；
- 产品说明页面与开发者说明页面。

本阶段的目标不是对接真实 Prometheus、Kubernetes、CMDB、日志平台，而是先把**产品流程、数据模型、插件接口、LLM 调查链路、人机反馈和代码化演进闭环**做完整。

---

## 2. 产品定位

平台不是“AI 帮忙看一遍监控”，而是：

> **Code-first、AI-discovery 的自进化巡检平台。**

长期目标不是让 LLM 参与率越来越高，而是让成熟场景逐步转化成确定性代码、规则或插件，最终减少 LLM 调用。

平台同时存在两条主线。

### 2.1 风险闭环主线

```text
发现风险
  ↓
持续 / 加重
  ↓
确定性分析
  ↓
必要时 AI 调查
  ↓
已定位
  ↓
待处置
  ↓
处置中
  ↓
下一轮巡检自动复验
  ↓
已恢复 / 仍存在
```

### 2.2 能力演进主线

```text
AI 发现未知
  ↓
DISCOVERED EXPERIENCE
  ↓
人工反馈 / 经验确认
  ↓
简单规则 ─────────────→ CODE_ACTIVE
  ↓
复杂逻辑 / 新采集能力
  ↓
CODE_PENDING
  ↓
开发插件
  ↓
SHADOW
  ↓
验证通过
  ↓
CODE_ACTIVE
  ↓
下一次同类 Case 不再进入 AI
```

---

## 3. 第一阶段范围

### 3.1 必须实现

1. 每日巡检任务自动生成模拟巡检数据并执行巡检。
2. PostgreSQL 保存 Daily Snapshot、巡检运行、风险、证据、能力、对话、反馈和经验。
3. 风险使用稳定 `risk_id` 跨天关联，不按天重复创建无关记录。
4. 巡检项目显示执行模式、代码化程度和 LLM 依赖边界。
5. Capability Registry 支持 RULE、EXEC、REST、MCP 四类 Manifest；第一阶段真实执行 RULE、EXEC 和内部 REST Stub，MCP 保留协议适配器和测试桩。
6. 运维人员可在风险详情或巡检项目详情发起“询问 AI”。
7. LLM 可以基于当前 Risk/Inspection Context 主动调用只读插件补查模拟数据。
8. 所有 Tool Call、Evidence、LLM 消息、模型信息和人工反馈可追踪。
9. 本地开发默认使用 Ollama。
10. 产品说明页面解释平台定位、风险闭环、Code/AI 分工、插件化、数据来源和安全边界。
11. Airflow 每天调度一次巡检，同时支持手动触发。
12. 页面保持 v4.1 的渐进式披露：默认简洁，技术详情折叠。

### 3.2 第一阶段不实现

- 不接真实 Prometheus / VictoriaMetrics。
- 不接真实 Kubernetes API。
- 不接真实 CMDB / ITSM / AlphaOps。
- 不允许 LLM 执行写操作。
- 不允许自动重启、迁移、修改配置或扩缩容。
- 不做复杂 RBAC 平台化，先提供最小用户和角色模型。
- 不做多租户隔离，字段预留 `environment_id`、`tenant_key`。
- 不实现真正的插件签名发布平台，只实现 Manifest 注册、版本、启停和状态管理。

---

## 4. 固定软件版本与运行约束

以下版本为项目基线，不允许开发人员自行升级：

| 软件 | 固定版本 / 约束 | 用途 |
|---|---|---|
| Django | **4.2.16** | Web/API 后端 |
| Airflow | **2.3.2** | 每日批量巡检编排 |
| LangGraph | **1.2.10** | LLM 调查状态机 |
| LangChain | **1.3.14** | LLM/Tool 抽象 |
| Python | **3.10.x** | 兼容上述运行时的统一开发版本 |
| PostgreSQL | **14.x** | 应用数据库与 Airflow 元数据库，Docker 启动 |
| Ollama | 本机安装，模型名可配置 | 本地 LLM Provider |
| Docker / Docker Compose | 本机已有版本 | PostgreSQL、本地辅助服务 |

### 4.1 运行时必须分离

由于 Airflow 2.3.2 与 LangGraph 1.2.10 / LangChain 1.3.14 所处依赖年代差异较大，第一阶段必须使用两个独立 Python 3.10 虚拟环境：

```text
.venv-web
  Django 4.2.16
  LangGraph 1.2.10
  LangChain 1.3.14
  Django REST Framework
  PostgreSQL Driver

.venv-airflow
  Airflow 2.3.2
  requests
  Airflow 官方 Python 3.10 constraints
```

Airflow DAG 不直接 import Django/LangGraph 业务模块，而通过 `/api/internal/v1/batch/*` 内部 HTTP API 驱动每日批处理阶段。这样可以隔离依赖，同时让批处理任务和在线产品服务保持清晰边界。

### 4.2 为什么 Airflow 只负责批处理

Airflow 2.3.2 用于：

- 每日巡检 DAG；
- 模拟数据生成；
- 批量巡检执行；
- Snapshot 汇总；
- 自动复验任务。

Airflow **不负责**：

- 在线聊天；
- SSE 流式响应；
- LangGraph 交互状态机；
- 用户实时 Tool Calling。

这样避免老版本 Airflow 和在线交互链路耦合。

---

## 5. 总体架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│                            Web UI                                   │
│ 每日巡检 | 风险中心 | 待处置 | 巡检能力 | 能力演进 | AI运行 | 产品说明 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ REST / SSE
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Django 4.2.16                                 │
│                                                                     │
│  Dashboard API   Risk Service      Inspection Catalog               │
│  Conversation    Feedback Service  Capability Registry              │
│  Experience      Model Gateway     Product Docs API                 │
│  Audit Service   Mock Data API     Airflow Trigger Adapter          │
└────────────┬────────────────────────┬───────────────────────────────┘
             │                        │
             │                        │
             ▼                        ▼
┌──────────────────────┐   ┌─────────────────────────────────────────┐
│ PostgreSQL 14.x      │   │ Investigation Runtime                   │
│                      │   │ LangGraph 1.2.10                       │
│ risks                │   │ LangChain 1.3.14                       │
│ inspection_runs      │   │                                         │
│ evidence             │   │ Context Builder                         │
│ conversations        │   │ Planner → Tool → Validator → Answer     │
│ feedback             │   │            │                            │
│ capabilities         │   │            ▼                            │
│ experiences          │   │       Capability Registry               │
│ audit_events         │   └────────────┬────────────────────────────┘
└────────────┬─────────┘                │
             │                          │ read-only
             │                          ▼
             │              ┌───────────────────────────────────────┐
             │              │ Inspection Plugins                    │
             │              │ RULE | EXEC | REST | MCP Adapter      │
             │              └───────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Airflow 2.3.2                               │
│ mock_data → execute_inspections → correlate_risks → snapshot       │
│                                  → schedule_reverification          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. 核心领域对象

### 6.1 Inspection Item

一个“巡检项目”代表用户可理解的巡检能力，例如：

- 控制面反亲和巡检；
- KVM 集群容量巡检；
- LLM 推理性能巡检；
- GPU 容量趋势巡检；
- Host 网络接收路径巡检；
- CVE 风险巡检；
- 证书有效期巡检。

每个巡检项目必须显式维护：

```text
execution_mode
code_status
code_coverage_percent
llm_responsibilities
resolved_claims
unresolved_claims
bound_capabilities
```

### 6.2 执行模式

| 值 | 含义 |
|---|---|
| `CODE_ONLY` | 全部由代码/规则闭环，默认 0 Token |
| `CODE_FIRST_AI_FALLBACK` | 代码先执行，仅未知 Claim 进入 AI |
| `AI_INVESTIGATION` | 当前核心根因仍需 AI 调查 |
| `LEARNING_MODE` | 明确进行知识发现，不属于普通每日巡检 |

### 6.3 代码化状态

| 值 | 含义 |
|---|---|
| `CODE_ACTIVE` | 已完全代码化并正式执行 |
| `PARTIAL_CODE` | 部分 Claim 代码化，部分依赖 AI |
| `CODE_PENDING` | 已识别需要工程化但尚未完成 |
| `SHADOW` | 新插件/规则影子验证中 |
| `NOT_CODED` | 尚无确定性实现 |

---

## 7. Capability Registry 与插件模型

### 7.1 核心原则

上层巡检流程只依赖 Capability Registry，不直接依赖具体 Python 文件、REST URL 或 MCP Server。

Capability Manifest 示例：

```yaml
capability_id: llm.scheduler.pressure
version: 0.9.0
name: Scheduler Pressure Resolver
status: SHADOW
implementation_type: REST
subjects:
  - llm_instance
  - runtime_pod
semantic_tags:
  - llm
  - scheduler
  - latency
resolves:
  - llm.performance.degradation_category
input_schema:
  type: object
  required: [entity_id, start_time, end_time]
output_schema:
  type: object
security:
  read_only: true
runtime:
  timeout_seconds: 15
  retry: 2
```

### 7.2 第一阶段插件类型

#### RULE

用于确定性条件：

```text
PACKET_LOSS_CONFIRMED
+
SOFTIRQ_SURGE
+
RX_MISSED_ERRORS
→ RX_PATH_PRESSURE
```

#### EXEC

本地开发时执行受控 Python 脚本：

```text
plugins/network/check_rx_path.py
```

必须满足：

- 白名单目录；
- 固定参数 Schema；
- 禁止 shell 拼接；
- 超时；
- 只读；
- stdout 为 JSON。

#### REST

调用平台内部 Stub 或后续独立 Inspector 服务。

#### MCP

第一阶段实现 Manifest 与 Adapter 接口，不连接生产 MCP；使用 fake MCP adapter 完成测试。

### 7.3 Resolver 覆盖机制

```text
Risk / Inspection Goal
        ↓
Required Claims
        ↓
Capability Registry.resolve(claim)
        ↓
找到 CODE_ACTIVE Resolver?
   ├─ YES → Code 执行
   └─ NO
       ↓
存在已知补查能力?
   ├─ YES → Code Enrichment
   └─ NO
       ↓
Material Residual / Claim Gap?
   ├─ NO → 结束
   └─ YES → AI Eligible
```

这保证新插件注册并激活后，同类 Case 自动减少 LLM 调用。

---

## 8. 每日巡检执行设计

### 8.1 Airflow DAG

建议 DAG：`daily_iaas_inspection`

```text
generate_mock_dataset
      ↓
create_inspection_run
      ↓
execute_code_only_items
      ↓
execute_hybrid_code_phase
      ↓
run_deterministic_coverage
      ↓
create_risks_and_findings
      ↓
correlate_existing_risks
      ↓
run_reverification
      ↓
build_daily_snapshot
      ↓
close_inspection_run
```

注意：每日批量任务默认**不强制调用 LLM**。对于需要 AI 的 Case，可以配置两种模式：

1. `DEFERRED`：生成“待 AI 调查”状态，用户打开后再调查；
2. `AUTO_READONLY`：批量任务调用只读 Investigation Runtime，设置每日预算。

第一阶段默认 `DEFERRED`，避免本地开发每天自动占用 Ollama。

### 8.2 Daily Snapshot

每天固定以下统计：

- 资产总数 / 覆盖数；
- 巡检项目数；
- 重点风险；
- 新增风险；
- 风险加重；
- 已恢复；
- 待处置；
- 待复验；
- Code-only Case 数；
- AI-dependent Case 数；
- Code Coverage Rate；
- Deterministic Deflection Rate；
- AI Displacement Rate；
- 数据完整性。

---

## 9. 风险生命周期设计

状态：

```text
NEW
PERSISTING
WORSENED
INVESTIGATING
LOCATED
PENDING_ACTION
IN_PROGRESS
PENDING_REVERIFY
RECOVERED
IGNORED
FALSE_POSITIVE
```

核心规则：

- 风险身份由 `fingerprint` 进行跨天关联；
- `risk_id` 首次创建后稳定；
- 每次巡检产生一个 Risk Observation；
- 连续观察不到且达到恢复条件后才进入 `RECOVERED`；
- 人工点击“已处理”不会直接标记恢复，只进入 `PENDING_REVERIFY`；
- 下一轮相同巡检项目重新执行后确认是否恢复。

---

## 10. 模拟巡检数据设计

### 10.1 目标

模拟数据必须能稳定产生可复现的正常、异常、趋势和冲突 Case，支持 UI、LLM 调查、Tool Calling、Replay 和 Shadow。

### 10.2 数据域

第一阶段生成：

- Asset/Topology：Cluster、Host、VM、Pod、GPU、LLM Instance；
- Metrics：CPU、Memory、TTFT、Queue、GPU Util、rx_missed、softirq、capacity；
- Logs：kernel、runtime、kubelet、scheduler；
- Events：Pod Restart、Xid、NIC drop、config change；
- Change：模拟部署、参数变更；
- Vulnerability：CVE 清单；
- Certificate：剩余有效天数。

### 10.3 Scenario Seed

内置固定种子：

| Scenario | 目标 |
|---|---|
| `healthy_baseline` | 全部正常 |
| `llm_scheduler_pressure` | 代码确认性能退化，AI/Shadow Resolver 定位 Scheduler Pressure |
| `control_plane_anti_affinity` | 纯代码闭环 |
| `network_rx_pressure` | AI/部分代码化根因调查 |
| `gpu_capacity_exhaustion` | 趋势代码 + AI 解释 |
| `data_incomplete` | 数据无效，不进入 AI |
| `post_action_reverify` | 处置后自动复验 |

生成器必须支持同一 `seed` 输出完全一致的数据，便于测试。

---

## 11. LLM 接入设计

### 11.1 Model Gateway

业务代码只调用统一接口：

```python
class ModelGateway:
    def invoke(self, request: ModelRequest) -> ModelResponse: ...
    def stream(self, request: ModelRequest): ...
```

Provider：

```text
OllamaProvider          ← 本地默认
OpenAICompatibleProvider ← 后续企业模型预留
```

环境变量：

```text
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
LLM_MAX_TOKENS=4096
LLM_TIMEOUT_SECONDS=120
```

模型名只是本地示例，必须可配置，不写死在代码中。

### 11.2 LLM 不允许看到的内容

- PostgreSQL 密码；
- 未来真实监控 AK/SK；
- MCP 身份凭证；
- 任意生产写权限；
- 未经过 Evidence Builder 筛选的大规模原始数据。

---

## 12. 运维人员与 LLM 交互设计

### 12.1 交互入口

允许从以下位置启动会话：

- Risk Detail → “询问 AI”；
- Inspection Item Detail → “询问此巡检能力”；
- Investigation Detail → “继续调查”；
- Experience Detail → “解释这条经验是怎么来的”。

### 12.2 上下文绑定

每个 Conversation 必须绑定：

```text
conversation_id
context_type: RISK | INSPECTION_ITEM | INVESTIGATION | EXPERIENCE
context_id
inspection_run_id (optional)
risk_id (optional)
```

用户不需要把风险信息复制到 Prompt。

### 12.3 Context Builder

默认给 LLM：

- 当前风险摘要；
- 关键 Findings；
- 最近 Evidence；
- 当前已知结论；
- Required Claim Gap；
- 可用只读 Capability；
- 用户历史反馈摘要；
- 预算和工具约束。

默认不提供：

- 所有数据库记录；
- 全量日志；
- 全量时间序列；
- 无关资产数据。

### 12.4 LangGraph Investigation Graph

```text
START
  ↓
build_context
  ↓
plan_or_answer
  ├─ 可以直接回答 ────────────┐
  │                           │
  └─ 需要新证据               │
        ↓                     │
    select_tool               │
        ↓                     │
    execute_readonly_tool     │
        ↓                     │
    validate_evidence         │
        ↓                     │
    update_hypothesis         │
        ├─ unresolved → tool（受 max_rounds 限制）
        └─ resolved ──────────┘
                             ↓
                         final_answer
                             ↓
                            END
```

硬限制：

```text
max_rounds = 3
max_tool_calls = 5
max_evidence_items = 30
max_single_query_window = 2h
read_only_only = true
```

### 12.5 回答结构

最终回答不是自由散文，至少包含：

```json
{
  "summary": "...",
  "current_conclusion": "...",
  "confidence": 0.86,
  "confirmed_facts": [],
  "hypotheses": [],
  "new_evidence": [],
  "recommended_next_steps": [],
  "tool_calls": [],
  "unresolved_questions": []
}
```

UI 再转换成中文结构化卡片。

---

## 13. 人工反馈设计

### 13.1 反馈类型

每条 LLM 回答提供：

- `HELPFUL`：有帮助；
- `INCORRECT`：结论不准确；
- `MISSING_EVIDENCE`：缺少证据；
- `WRONG_TOOL_PATH`：补查方向不正确；
- `CONFIRMED_ROOT_CAUSE`：人工确认根因；
- `FALSE_POSITIVE`：巡检误报；
- `CUSTOM`：自定义说明。

### 13.2 反馈不是审批

反馈用于：

- 改善当前 Risk/Investigation；
- 形成 Experience；
- 统计 LLM 质量；
- 提供代码化候选。

生产变更审批不在本系统实现。

### 13.3 反馈进入经验闭环

```text
Conversation / Investigation
        ↓
Human Feedback
        ↓
Feedback Aggregator
        ↓
满足形成经验条件?
    ├─ NO → 仅保存
    └─ YES
        ↓
      Experience(DISCOVERED)
        ↓
人工确认经验语义
        ↓
Rule Candidate / CODE_PENDING
```

---

## 14. Experience-to-Code 设计

Experience 包含：

- 问题类型；
- Applicable Scope；
- Hypothesis；
- 支持 Evidence；
- 反证；
- Tool Sequence；
- 人工反馈；
- 适用条件；
- 历史 Case；
- 可转换 Claim；
- 当前代码化阶段。

阶段：

```text
DISCOVERED
CONFIRMED
RULE_CANDIDATE
CODE_PENDING
SHADOW
CODE_ACTIVE
REJECTED
RETIRED
```

对于简单规则，可直接生成 DSL Candidate；对于复杂经验，创建 Codeization Task，等待工程开发插件。

---

## 15. PostgreSQL 数据架构总览

数据库分为应用 DB `inspection` 与 Airflow metadata DB `airflow`，运行在同一个本地 PostgreSQL Docker 实例中。

应用主要实体：

```text
environments
assets
inspection_items
inspection_runs
inspection_item_runs
findings
evidence
risks
risk_observations
risk_status_history
daily_snapshots
capabilities
capability_versions
inspection_capability_bindings
investigations
investigation_events
conversations
conversation_messages
tool_calls
human_feedback
experiences
experience_evidence
codeization_tasks
mock_datasets
audit_events
```

详细字段定义见《开发实施文档》。

---

## 16. API 设计原则

统一前缀：

```text
/api/v1/
```

规则：

- JSON 使用 `snake_case`；
- 时间使用 ISO 8601 + timezone；
- 主键对外使用 UUID；
- 分页：`page` / `page_size`；
- 过滤用 query 参数；
- 错误返回统一 `error.code / error.message / error.details`；
- 对话流式输出使用 SSE；
- Tool Call 必须产生持久化记录；
- 所有写操作产生 Audit Event。

接口完整清单、请求响应示例、错误码见《开发实施文档》。

---

## 17. UI 产品信息架构

### 17.1 一级导航

```text
每日巡检
风险中心
历史趋势
待处置
──────────
巡检能力
规则与经验
能力演进
──────────
AI 运行情况
产品说明
系统设置
```

### 17.2 每日巡检

默认只显示：

- 今日总体状态；
- P1/P2 重点风险；
- 新增 / 加重 / 恢复 / 待处置；
- 昨日变化；
- 7/30 天趋势；
- 巡检能力成熟度摘要；
- 巡检完整性。

不默认显示内部 JSON、Prompt、Token、Pattern、Residual。

### 17.3 风险详情

四级信息：

```text
L1 当前判断 / 影响 / 建议
L2 关键证据 / 风险生命周期 / 自动复验
L3 调查过程 / AI 介入原因 / Tool Calls
L4 Raw Evidence / Findings / Prompt Metadata / JSON
```

新增：

```text
[询问 AI]
[有帮助]
[结论不准确]
[补充反馈]
[记录已处理]
```

### 17.4 巡检能力

必须回答：

- 哪些巡检完全代码化；
- 哪些是 Code-first + AI；
- 哪些仍依赖 LLM；
- LLM 具体负责哪个 Claim；
- 哪些 Resolver 是 `CODE_PENDING` 或 `SHADOW`；
- 每个插件是什么实现方式。

### 17.5 产品说明页面

产品说明页面不是 README 的复制，而是面向产品使用者的内置说明：

1. 这个系统解决什么问题；
2. 每日巡检如何工作；
3. 为什么不是所有问题都交给 LLM；
4. Code / AI 如何分工；
5. 插件化是什么；
6. 什么叫代码化程度；
7. 人工反馈如何帮助系统进化；
8. 为什么“已处理”后还要自动复验；
9. 当前 Demo 使用模拟数据；
10. LLM 本地开发使用 Ollama；
11. 安全边界：只读 Tool Calling；
12. 术语解释。

---

## 18. 安全边界

### 18.1 第一阶段强约束

- LLM 只允许调用 `read_only=true` Capability；
- EXEC 插件必须来自白名单目录；
- 禁止任意 shell；
- REST 只允许注册到允许的本地/内部地址前缀；
- Tool 参数通过 JSON Schema 校验；
- 每次 Tool Call 有 timeout；
- 对话最多 3 轮工具调查；
- Prompt 不包含数据库密码；
- Audit 保存调用但不保存机密环境变量。

### 18.2 未来生产写操作

如果未来需要自动修复，应建立独立 `Action Gateway`，与当前只读 `Capability Registry` 分开，不复用同一执行器。

---

## 19. 可观测性与质量指标

### 19.1 巡检质量

- Risk Precision；
- Risk Recovery Accuracy；
- False Positive Rate；
- Reverification Success Rate；
- Coverage Rate。

### 19.2 AI 质量

- Admission Precision；
- AI Miss Rate；
- Hypothesis Precision；
- Evidence Request Precision；
- Human Helpful Rate；
- Confirmed Root Cause Rate；
- Average Tool Calls；
- Average Investigation Latency。

### 19.3 自进化指标

- Code Coverage Rate；
- Deterministic Deflection Rate；
- AI Displacement Rate；
- AI-dependent Cases；
- CODE_ACTIVE Added；
- CODE_PENDING / SHADOW；
- Experience → Code Conversion Rate。

---

## 20. 本地部署拓扑

```text
Mac / Developer Machine
│
├─ Django API        :8000
├─ Web UI            Django static/template or same dev server
├─ Ollama            :11434
├─ PostgreSQL Docker :5432
├─ Airflow Webserver :8080
└─ Airflow Scheduler
```

建议本地只把 PostgreSQL 放入 Docker；Django、Airflow 和 Ollama 可以直接运行在宿主机 Python/本机进程，便于调试。也允许后续把 Django/Airflow 一并 Compose 化。

---

## 21. 成功验收标准

第一阶段完成必须满足：

1. `docker compose up -d postgres` 可启动 PostgreSQL；
2. Django 4.2.16 可迁移数据库并启动；
3. Airflow 2.3.2 可触发每日巡检 DAG；
4. 固定 seed 可生成稳定模拟数据；
5. 首页能显示 Daily Snapshot；
6. 风险跨多日保持同一 `risk_id`；
7. 至少 5 个巡检项目展示代码化程度和 LLM 职责；
8. 至少存在 CODE_ONLY、PARTIAL_CODE、CODE_PENDING、SHADOW 四种演示状态；
9. 风险详情可发起 Ollama 对话；
10. LLM 可调用只读插件并在 UI 中看到 Tool Call 和 Evidence；
11. 人工反馈可以保存并关联具体 LLM 消息 / Risk / Investigation；
12. 人工确认根因后可生成 Experience；
13. Experience 可进入 CODE_PENDING/SHADOW 演示流程；
14. “记录已处理”只进入 PENDING_REVERIFY，不直接恢复；
15. 下一轮巡检能自动验证恢复；
16. 产品说明页面完整解释产品机制；
17. 所有 API 有接口文档；
18. 所有 PostgreSQL 表字段有字段说明；
19. 全量自动化测试通过。

---

## 22. 推荐实施顺序

```text
Phase 1  基础工程 + PostgreSQL + Django
Phase 2  模拟数据 + 巡检数据模型
Phase 3  Daily Inspection + Airflow
Phase 4  Risk Lifecycle + Daily Snapshot
Phase 5  Capability Registry + Plugin Runtime
Phase 6  Ollama Model Gateway + LangGraph Investigation
Phase 7  Human Feedback + Experience-to-Code
Phase 8  Web UI + 产品说明页面
Phase 9  Replay / Shadow Demo + 指标
Phase 10 完整回归与开发者文档
```

对应详细任务、API、数据库字段和测试步骤见：

`IaaS智能巡检平台_开发实施文档_v1.md`
