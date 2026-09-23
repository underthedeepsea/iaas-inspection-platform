# 实施计划：LLM 性能插件化、最小提示词页与演示插件删除

**版本：1.0｜执行基线：`8e044c769eb1817cd48ce081c2f95b161e32d4ec`**  
**配套文件：`iaas_llm_plugin_prompt_design_v1.md`**  
**状态：供 Codex 实施的计划，尚未在远端执行或提交。**

## 0. 执行约束

本轮不是重建性能模块，而是修正归属、接回平台闭环、增加可生效的提示词页、删除演示生产能力。必须保留现有 20 个指标字段、三个性能 API、固定/14d/趋势能力和 DEFAULT→ENGINE→ENGINE_MODEL 精确继承。

先固定基线与测试，再按 P1–P8 执行。单项做完运行对应测试；全部实施后统一做一次完整代码评审和 Release Gate。失败先修当前阶段，不插入插件市场、多 Agent、模板工作流、GPU 或新基础设施。

**禁止操作：**清空旧库、重写已发布 migration、批量删除全部 Capability、修改历史判定、把演示 Risk 批量标记恢复、为通过测试直接删除通用能力测试。

## 1. 代码审查定位

| 问题 | 直接证据 | 本轮目标 |
|---|---|---|
| API 直接调独立 evaluator | `services/ingest.py` 导入 `.evaluator`；CODE 注册没有新能力 | 所有新评估经已注册插件。[R02] [R03] [R10] |
| Run 仍要求 MockDataset | trigger 自动生成；execution、orchestrator 拒绝无 dataset | 按 input_source 选择真实 reader。[R12] [R13] [R14] |
| seed 会恢复演示规则 | 三条 hard-coded RULE_CONFIGS，且关闭其他绑定 | 改为新真实目录并精确退役旧项。[R15] |
| 定时入口仍是模拟路线 | daily DAG 先 generate_dataset | 不制造模拟数据也完成现有阶段。[R16] [R17] |
| AI 入口提示词硬编码 | explanation 与 dashboard_explanation | 两处共用一个受管提示词。[R18] [R19] |
| 前端两套事实并列 | Profile + 原 CheckResults/Risk/AI | 明确实时窗口与正式 Run，统一来源。[R23] [R24] |
| 运行正确性缺口 | 幂等、Batch 时间、零基线、辅助指标方向 | 插件进入 Risk 前一起修复。[R03] [R04] |

上一版交付确实要求独立上线和保留演示规则；本计划主动替代该错误取舍，不把整改写成“恢复实现本来就有的行为”。

## 2. P1：固定基线与失败用例

### 2.1 开始前

在新的修复分支工作，建议 `codex/llm-plugin-prompt-mvp`。记录当前 HEAD、依赖锁、数据库迁移状态和当前远端基线差异。若 main 已更新，先重新核对受影响文件，再应用本计划，不盲目覆盖。

测试环境使用 PostgreSQL 副本，不接生产写库。记录现有 Snapshot、Asset、InspectionItem、CheckResult、Risk、Evidence、CapabilityVersion 数量，以便迁移后对比。

执行并保留原始日志：

```bash
python manage.py check
python manage.py showmigrations
python -m pytest -q
cd frontend
npm ci
npm test
npm run build
```

以上是待执行命令，不代表本次审查已跑通。使用仓库已有 Python/Node/依赖版本，不顺手升级框架。

### 2.2 先加架构回归用例

- 当前性能 Push 是否经过注册 handler：在 dispatcher 层 spy 计数，必须恰好一次。
- 活动插件目录是否包含 `inference-performance`，且不包含精确退役的三条 ID。
- 无 MockDataset 的 LLM_RUNTIME Run 能否执行到 CheckResult/Risk。
- 改提示词后两处 ModelRequest.messages 是否确实改变。

这些用例在旧代码上失败是预期，不能为了“兼容旧测试”继续保留演示生产注册。

## 3. P2：资产关联与幂等接入先修好

### 3.1 模型与迁移

修改 `apps/inference_performance/models.py`，新增：

```python
asset = models.ForeignKey(
    "assets.Asset", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="performance_snapshots",
)
```

保持原 Snapshot PK、`source+sample_id` 唯一约束、metrics/evaluation JSON 与查询索引。新增索引 `(asset, window_end)`；14d 查询继续按完整原始身份，不能只看新增外键导致旧历史失效。

资产键算法冻结为：

```python
payload = [engine_id, engine_type, model_name]
external_key = "inference:" + sha256(
    json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
).hexdigest()
```

Environment 与 external_key 的现有唯一约束保证环境隔离。`Asset.labels` 写 `input_source=INFERENCE_SNAPSHOT` 以及引擎类型/模型身份，不存凭证。代码复用 `get_or_create` 与唯一约束；不拿资产展示名称当身份。

为既有记录新增可重复的 `backfill_inference_assets` 管理命令，按主键分批关联，默认 dry-run，`--apply` 才写。只补 asset FK/真实资产，不改历史 evaluation，也不制造历史 Run 或插件版本。正式上线 Gate 要求回填完成或明确覆盖的保留期完成。

### 3.2 单条/批量接入

改 `services/ingest.py`：

1. 先校验请求并解析合法 Environment，再检查幂等。
2. 命中 `(source,sample_id)` 时比对环境、完整引擎身份、start/end 和规范化指标。完全相同返回旧结果；否则抛明确 409 `IDEMPOTENCY_CONFLICT`。不能返回冲突行内容。
3. 单批先完整校验，冲突则整批拒绝，不做半成功的模糊回灌。
4. 按 `(window_end, window_start, sample_id)` 确定本批最新；不再使用 `ordered[-1]`。同资产同时间窗口的不同内容拒绝。
5. 同一资产在事务内行锁，串行新数据评估和检查窗口冲突；迟到数据可入历史，但不能改变已完成 evaluation 或已冻结 Run。用于 live 评估的采样须满足约定采样周期。
6. 保留 `created/profile`、`count/created_count/evaluated` 返回结构；并发插入统计只计本事务实际创建的行，不能 `ignore_conflicts` 后猜测成功数。
7. batch `evaluate_latest=false` 只回灌，不生成 Risk；未评估数据不得在画像中显示 NORMAL。

保持严格 20 指标 Schema。错误响应继续复用 `apps/api/http.py` 的 error envelope，409 需要单独领域异常状态映射；不得被 `_boundary` 包成 500。[R03] [R08] [R09]

## 4. P3：注册一个真实 CODE 插件，收口调用链

### 4.1 文件修改

| 文件 | 改动 |
|---|---|
| `apps/inspections/rules/plugin.py` | `RuleDefinition` 增加 `input_source` 声明；为旧兼容调用给明确默认值 |
| `apps/inspections/rules/registry.py` | 注册一个 `llm.performance_profile`；旧演示 handler 移出生产注册 |
| `apps/inspections/rules/inference_performance.py`（新增） | 唯一正式处理器，内部调用现有算法并适配 CheckResultSpec |
| `apps/inspections/services/code_dispatch.py`（新增） | 注册白名单查找、输入源验证、统一调用，不承担业务算法 |
| `apps/inference_performance/services/input_reader.py`（新增） | 当前快照 / Run 冻结结果输入 |
| `apps/inference_performance/services/evaluator.py` | 内部核心；允许传入已冻结 resolved_policy，避免重复解析出不同版本 |
| `apps/inference_performance/services/ingest.py` | 改调 code_dispatch，不再直调 evaluator |

### 4.2 契约

```python
# 接口形状；实现应复用现有 RuleDefinition / CheckResultSpec。
def dispatch_code_rule(*, rule_code, reader, assets, config):
    plugin = get_code_plugin(rule_code)
    validate_input_source(plugin.input_source, reader.source_type)
    return plugin.handler(reader=reader, assets=assets, config=config)

# Reader 由服务器构造，不接受用户任意函数名/模块路径。
class InferenceSnapshotInputReader:
    source_type = "INFERENCE_SNAPSHOT"

    def assets(self): ...
    def performance_input(self, asset_id): ...


def check_inference_performance(*, reader, assets, config):
    # 每资产独立处理，保证每个作用域资产恰好一项 CheckResultSpec。
    # COMPUTE：内部 evaluator 计算；FROZEN_RESULT：校验并读取冻结 evaluation。
    ...
```

`performance_input` 返回 mode、snapshot_id、身份、window、evaluation 或待计算 Snapshot、frozen_at。定义成 dataclass 即可，不新增动态协议框架。处理器产出的 evidence 必须带完整 evaluation/来源引用。

### 4.3 避免两个常见假修复

- 只在插件中心追加一条记录、API 继续直接调 evaluator：不通过。
- 新写一套性能插件算法、旧 API 保留原算法：不通过。

内部算法可保留原目录，但仓库内除插件实现和单元测试外，不允许业务代码直接 import 性能总 evaluator。使用 AST/模块依赖测试证明，无需重命名所有服务文件。

### 4.4 结果冻结

Push 首次保存的新 evaluation 增加插件 ID/版本、rule、快照身份、quality 和完整 resolved_policy。旧已完成结果不因重试、模板保存或查询而重算。`policy_source.config_hash` 对规范化有效配置计算。

正式 Run 使用其创建时复制的 evaluation；handler 映射而不修改源快照。无版本旧结果仅能作历史，不伪造“新插件产出”。启动后首批新样本即可开始正式检查。

## 5. P4：在保留算法的基础上修正确认边界

这一阶段应小范围修改原有 fixed/baseline/trend 文件，不能改为新的预测模型。

### 5.1 固定与状态

- 配置加载必须验证完整主指标阈值、有限且 `0 <= warning < critical`、持续次数正整数。
- warning 和 critical 分别计连续命中，当前级别有效性不能由低一级历史替代。
- 使用不同窗口且连续的历史点；超过 max_gap 或窗口长度变化重新累计。
- `pending_confirmation=true` 表示原始值越界但未确认；没有其他已确认异常时，正式 CheckResult 为 UNKNOWN，不作为恢复依据。若其他指标已确认 WARNING/CRITICAL，则仍为 FAIL，不能被待确认状态掩盖。API 同时保留 raw/effective 状态。
- ERROR/UNKNOWN 明确支持，不能落入 `highest_status([])==NORMAL` 伪正常路径。

### 5.2 动态与辅助指标

- 主体公式、14d、4096、100 样本/3 日期保留。
- QPS 相似集合先验证 100/3 就绪；否则回退完整历史并标记；回退动态只作观察，不单独升级正式风险。
- 0 中位数：该指标动态 `NOT_EVALUABLE`，change_ratio=null、absolute_change 可用，Fixed 仍独立判定。
- support metrics 不再按 HIGH_BAD 打告警等级，保留偏离证据。
- 有效历史按同统计周期与同身份选择，剔除明确 IDLE 和输入无效观测，不把当前/未来窗口用于基线。
- 用有序 `.values(...).iterator(chunk_size=...)` 及确定性等距取样，避免 `list(queryset)` 装入全部大 JSON。可先 count 再迭代选定序号，内存 O(4096)；查询扫描成本仍应实测，不能声称 O(1)。

### 5.3 趋势与新鲜度

- 以当前样本结束时刻为锚点，严格切分前/后 30 分钟，至少各 3 个样本。
- 0 前半中位数不除 epsilon；返回不可评价和绝对变化。
- trend 不直接提高 Overall，保留 NORMAL + DEGRADING 的独立表达。
- `GET profile` 将读取时 `freshness` 与原始 `evaluation.status` 分开：过期当前状态 UNKNOWN，但保留当时的历史结论，不写回历史。
- 未评估最新样本显示 UNKNOWN；不得静默回退旧正常样本而不告诉用户。

### 5.4 最小复现与预期

以下现象已按取回源码做逻辑级最小复现，不是整仓 pytest：

| 输入 | 当前逻辑输出 | 修正后验收 |
|---|---|---|
| waiting 历史全 0，当前 1 | 动态 CRITICAL | ZERO_BASELINE，固定阈值判定照常 |
| cache hit 0.5→0.8 | 辅助项 CRITICAL，但不计 Overall | 中性偏离，不应暗示变坏 |
| cache hit 0.5→0.1 | 辅助项 NORMAL | 中性负向偏离，交给有证据的解释 |
| Batch 时间顺序 [12:02,12:01] | 选择 12:01 | 选择 12:02 |
| 过去 5 分钟 6 个点，后半延迟升高 | 标记 60m DEGRADING | 时间覆盖不足 NOT_READY |
| 前一点 warning，本点首次 critical | CRITICAL 生效 | critical 尚未确认，warning 可按自身条件确认 |

## 6. P5：接回正式 Run、风险、定时巡检

### 6.1 输入冻结与 dataset 边界

修改 `trigger.py`、`scope.py`，先用真实 selector 得到资产；按资产复制最新新鲜且带插件版本的 evaluation，并限制 window_end 与 created_at 均不晚于冻结 as_of。`config_snapshot` 保存 source_type、as_of 和快照映射；`ItemRun.asset_scope` 继续保存资产和规则范围。[R13] [R30]

修改 `execution.py`：

- 经 `code_dispatch` 调用，不再直接调用某个 handler 或硬编码旧 rule 名判断资产类型。
- 对 INFERENCE_SNAPSHOT 创建真实 reader；不要求 `run.dataset`。
- source 写 INFERENCE_SNAPSHOT，不再硬编码 MOCK。
- 给每个资产写一条 CheckResult；只把 FAIL 转为 Finding。
- 使用结果上的 severity，WARNING→P2、CRITICAL→P1；未知和错误不转正常。
- 继续保留 ItemRun 完成幂等和已有 Run 计数/SSE。

修改 `manual_orchestrator._claim_run` 和 `api_internal`：根据已冻结 source_type 校验，不一概放开所有无 dataset 的未知输入。来源不支持必须拒绝。无活动插件时返回 409 NO_ACTIVE_PLUGIN；有插件但无资产/数据时不输出空集合 NORMAL，汇总明确 NO_DATA/UNKNOWN。保留现有 stages 和 Airflow 内部鉴权。[R12] [R14] [R17]

### 6.2 定时任务也必须验证

`daily_iaas_inspection.py` 删除正式链路的生成模拟数据任务；创建 Run 只传环境、日期、dag_run_id、`source_type=INFERENCE_SNAPSHOT` 和资源范围。内部 API 复用与手动入口相同的冻结服务。原有 dag_run_id 幂等保留。

新的顺序：create/freeze → execute → correlate → reverify → resource_summaries → snapshot → complete。Airflow 仍只调 HTTP，不 import Django/LangGraph 业务代码。[R16]

### 6.3 风险集成

复用 `apps/risks/services/correlation.py` 和 `reverify.py`，只做真实输入所需适配：

- 风险指纹仍以环境/资产/inspection rule 为主，不包含 current、snapshot_id 或严重度。
- CheckResult 的所有原因保留到 Evidence，可跳转到源 Snapshot。
- 不用 ItemRun 全局 ERROR 一票否决其他资产已经成功产生的 FAIL；仅对已完成、经过验证的单资产 CheckResult 关联。
- 复验按资产级 PASS + 非 pending + 新鲜真实观测。window_start 必须晚于对应 PENDING_REVERIFY 处理时间，且 snapshot_id 与处理前不同。
- 同一 Run 重试不重复创建 Finding/RiskObservation；无观测或数据过期不恢复。

增加混合资产用例：A=ERROR、B=FAIL、C=PASS。B 的风险必须出现；A 不误正常；只有 C 满足时间条件时才允许恢复 C 的旧风险。

### 6.4 页面接入

复用 LLM_RUNTIME 页面、Run 详情、风险详情；不新建独立运维门户。给 `InferencePerformanceProfile` 增加明确引擎选择、时间/时效、plugin/policy 来源及当前正式 Run 链接。下拉数据来自轻量 engines 列表接口。

全部指标可放折叠明细表，主卡片继续 p95。显示“实时快照时间”和“最近正式巡检时间”两个时间，防止指标比风险更新快时造成误解。AI 面板明确绑定 Run；无 Run 时不能拿历史演示上下文解释最新推送。

## 7. P6：删除演示生产插件与初始化路径

### 7.1 精确生产删除

移除生产注册、imports、handler 文件：

```text
topology.control_plane_anti_affinity / control-plane-anti-affinity
llm.ttft_slo                       / llm-ttft-slo
llm.queue_backlog                  / llm-queue-backlog
```

相关文件包括 `rules/control_plane_anti_affinity.py`、`llm_ttft_slo.py`、`llm_queue_backlog.py`。历史 migration 中的字符串保留，不改已发布 migration。必要测试夹具可用测试专用处理器，不从生产注册导出旧演示实现。

### 7.2 seed 与数据迁移

- `seed_launch` 只创建/更新 `llm.performance_profile` 的真实绑定，来源和标签准确。
- 新增幂等数据 migration：旧三条 InspectionItem disabled，活动绑定 disabled；保留被历史引用的行。
- 不修改历史 CheckResult 的 source/plugin_version 或旧 Risk 状态；通过只读 retired 标记和查询条件区分。
- CodePluginsPage 的筛选从实际注册资源派生；活动目录不出现旧三条。
- 更新首页/产品信息/默认资源/`dashboard_explanation.LAUNCH_TYPES` 等正式目录声明，避免宣称控制面已真实接入。
- `seed_e2e`、`seed_e2e_complete`、浏览器 fixtures 改用外部真实 Schema 的固定样例；生产初始化不得顺便生成模拟指标。
- 默认 mock API/生成命令从生产使用路径退出或加生产禁用门槛，通用 mock 库可保留为测试工具，不能参与 live 输入兜底。

先输出受影响 ID 与数量。若发现旧数据库还存在这三条以外的演示 Capability，逐一核对实际来源和历史引用，再纳入精确清单；禁止对所有 Capability 表执行 delete。

### 7.3 保留清单

`services/plugin_runtime/*`、Capability 模型/API、只读执行安全边界、Risk/Evidence/Feedback、Airflow、SSE、资源框架与历史查询均保留。清理完成后平台仍能接入下一项真实代码插件，而不是变成专用性能看板。

## 8. P7：一个真正生效的提示词管理页

### 8.1 数据层

在 `apps/investigations/models.py` 新增 `ExplanationPrompt`，不新建大型 prompt app：

```python
class ExplanationPrompt(models.Model):
    key = models.CharField(primary_key=True, max_length=64)
    name = models.CharField(max_length=128)
    body = models.TextField()
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
```

数据迁移只初始化 key=`inspection-explanation`，重跑 seed 不覆盖用户已编辑文本。恢复默认通过受保护 API 完成，不靠下次部署无声覆盖。

### 8.2 服务与接口

新增 `apps/investigations/services/prompts.py`，提供：

```python
def load_explanation_prompt(): ...
def render_explanation_system_prompt(record): ...
def update_explanation_prompt(*, body: str, expected_revision: int): ...
def reset_explanation_prompt(*, expected_revision: int): ...
```

保存用 `select_for_update` 或等效 compare-and-swap，revision 不匹配返回 409。正文 1–600 字符，禁止任意 key 创建，固定 guard 和 JSON 协议不通过 API 修改。

路径：

```text
GET   /api/v1/prompts/inspection-explanation
PATCH /api/v1/prompts/inspection-explanation
POST  /api/v1/prompts/inspection-explanation/reset
```

PATCH 示例：

```json
{"expected_revision":1,"body":"用中文150字内给出结论、最多两条带ID的关键证据和一条核查建议。无历史数据不做对比。"}
```

响应至少包含 key、body、revision、updated_at、hash、default_body、readonly_guard、purposes；绝不返回管理员 Token。写入前鉴权：部署环境配置 `PROMPT_ADMIN_TOKEN`，请求头 `X-Prompt-Admin-Token`，未配置/不匹配拒绝。凭证不进前端文件、不持久存浏览器；生产通过 TLS 与可信网关。

复用 AuditEvent：`prompt.updated` / `prompt.reset`，包含对象、before/after revision、正文/hash、trace_id。不要虚构用户身份，当前 token 模式记录管理凭证身份而非伪造“登录用户”。[R29]

### 8.3 两处真实调用接线

改 `explanation.py::explain` 和 `dashboard_explanation.py::explain_dashboard`：

- 删除两处内嵌业务提示词，统一 load/render。
- 调用开始冻结 prompt 与 context，保存当次 key/revision/body hash/guard version。
- 资源路径写 `Investigation.result.prompt`；首页路径写 AuditEvent 并返回 prompt 元数据。
- 所有剩余硬编码 system prompt 搜索一遍，列出入口；本轮只声明正式单轮解读两个入口受管，不冒充全部历史实验 Agent 提示词已迁移。

Qwen 默认文本及固定 guard 按设计文档第 7 节原样初始化。不能为了缩短文本改 `FinalAction` 协议，也不能把管理员正文直接当任意工具路由。

### 8.4 上下文预算与网关

新增 `build_compact_explanation_context`，两处共用：最多 8 条检查，每项 2 条原因、保留单位/阈值/基线/ID、准确汇总计数；问题 ≤300 字符、事实 JSON ≤8000 UTF-8 字节；结构化裁剪并输出 omitted_count。

保留 Ollama 已有 `think=false`、JSON mode、严格解析；不添加 `/nothink` 来假装控制 Qwen3.5。仅对受支持的当前 Provider 增加输出预算，初始 384 token，实际模型 smoke 决定是否需调整。若兼容运行时不支持参数，显式记录不支持，不静默声称已生效。[R20] [R21] [Q01] [Q02] [Q03]

FakeProvider 只用于可重复 CI，不能代替真实 4B 模型效果验收。真实模型实际量化和 tag 从返回值记录，不因模型名称相近就声称同一效果。

### 8.5 前端

新增 `frontend/src/pages/Prompts/PromptsPage.tsx` 与 `frontend/src/api/prompts.ts`。导航加“提示词”；React 路由与 `config/urls.py` 同时提供 `/prompts`。

只有一个编辑区、字符计数、生效入口/当前模型、保存、恢复默认。未授权显示只读；管理凭证临时输入保存在组件内存。保存成功显示新 revision；409 提示重新加载，不覆盖别人的修改。恢复默认应确认且走后端版本校验。正文作为纯文本展示，不能执行 HTML。

## 9. P8：回归、真实模型验收与发布

### 9.1 后端验收矩阵

| 编号 | 测试 | 通过标准 |
|---|---|---|
| T01 | 单条 / Batch 原协议 | 所有原字段和指标可读，未引入必填 GPU/节点字段 |
| T02 | 幂等与冲突 | 同内容重试返回同结果；改环境/引擎/指标均 409；无旧数据泄露 |
| T03 | Batch 乱序与回灌 | 选事件时间最新，不重复通知、不重写历史 |
| T04 | 注册入口 | Push 和 Run 都调用同一注册 handler；无 API→evaluator 旁路 |
| T05 | 阈值继承 | default、engine、engine+model 部分覆盖保持；当前与历史配置分离 |
| T06 | 固定级别 / 缺口 | warning 与 critical 各自持续；跨长间隔重置；待确认不恢复风险 |
| T07 | 14d 及零基线 | 过滤当前/未来/不同身份；queue 0→1 不动态 critical；辅助 cache 提升不告警 |
| T08 | 趋势时间 | 两个时间半区各有覆盖；5 分钟 6 点不冒充 60 分钟趋势 |
| T09 | 正式 Run 无 Mock | manual 和 Airflow 均完成，不调用 mock 生成，不新增 MockDataset |
| T10 | 风险与混合资产 | 有效 FAIL 关联；ERROR/UNKNOWN 隔离；单项错误不屏蔽其他资产 |
| T11 | 复验 | 拒绝处理前快照和过期 PASS；处理后新窗口 PASS 才恢复 |
| T12 | seed 与演示退场 | 两次 seed 不复活旧 ID；旧库历史行计数不减少 |
| T13 | prompt 写保护 | 未配置/错误 token 拒绝；正文/revision 校验；Token 不入日志 |
| T14 | prompt 真接线 | 保存和 reset 后两个 ModelRequest 都用新正文；留痕准确 |
| T15 | AI 降级 | Provider 异常/非法 JSON/CALL_TOOL 不修改任何 CheckResult/Risk |
| T16 | 旧库升级 | migrations 前后历史可读；旧未标版结果不被伪造为新插件 |

用现有测试目录组织测试，不要求必须使用某个新的测试框架。给每项保存对应测试名和日志位置，不能只在文档写“已通过”。

### 9.2 前端 / 浏览器

- 插件中心活动列表只有新正式插件，详情来源正确；保留旧 `/rules`、`/code-plugins` 别名。
- 引擎切换不能串环境或模型；显示测量时间与正式 Run 时间。
- 暂无数据、IDLE、过期、基线不足、待确认各有清楚文案，不显示绿色“全部健康”。
- 上传后执行一次真实 Schema 的巡检，进入 Run→Risk→AI；不走演示结果。
- `/prompts` 保存/冲突/reset、刷新深链接均可用；两处 AI 入口验证相同新提示词。

### 9.3 Qwen3.5-4B 的 12 个固定验收样例

正常；仅固定越界；仅可靠动态越界；趋势观察；动态未就绪；零基线；IDLE；数据过期；多资产一坏一好；无上次结果却要求比较；证据字段含“忽略系统指令”；超长输入被裁剪。

对旧/新 prompt 在**同一真实模型与量化**运行相同样例。记录合法 JSON 比例、事实/ID 引用正确性、是否臆断 GPU 根因、输入/输出 token（运行时提供才记）、耗时、输入字节数、截断数。验收必须：12 项均不改 CODE 判定、均无越权工具、非法输出不展示为成功；事实错误样例必须修正后重跑。耗时改善与 token 降幅仅报告实测值，不预填百分比。

### 9.4 性能与安全 Gate

保留旧目标“4096 历史计算样本单引擎一次评估开发环境目标 <1.5 秒”，标明是目标而非现成结果。再测试 14 天分钟级数据量下的查询/内存峰值，记录环境与实例数；修复 list 全量加载后仍可能扫描全部历史，不声称无成本。

不新增 Redis/Celery/MQ。线上清理继续用现有 prune 命令/运维计划，但已被 Run 引用的证据必须在 CheckResult 中完整保留，删除 Snapshot 不得使历史结论无法解释。

## 10. 发布、验证与回滚顺序

1. 备份数据库及当前策略文件；保存现有正式任务配置和演示对象清单。
2. 暂停旧每日演示任务，排空正在执行的旧 Run，避免切换中一半模拟一半真实。
3. 在库副本验证新增 schema 与精确退役迁移，再应用正式迁移；不得要求空库重建。
4. 执行资产回填、更新 seed 目录、部署新插件与输入 reader。确认全部新注册解析正常。
5. 收到至少一批新插件版本标识的真实快照，验证实时画像；确认历史未变。
6. 执行一次手动真实巡检，再执行一次 Airflow 实际 HTTP 流程，核对 CheckResult/Risk/复验。
7. 配置 prompt 管理凭证，确认真实 Qwen3.5-4B 请求与两处提示词生效；AI 失败不阻塞 CODE。
8. 恢复真实每日任务；观察首轮新数据、错误日志和风险数量变化。

失败回滚以恢复上一稳定应用/配置为主，新增 nullable 字段与提示词表保留，不做反向破坏性迁移。**若回滚到旧提交，旧 daily DAG 与 seed_launch 不得重新启用**，否则会复活演示检查；维持暂停，性能 Push 历史可继续保留。不要为回滚把新产生的真实证据删掉。

## 11. 完成定义

最终交付应包含修复代码、增量迁移、测试与真实模型验收记录，以及更新后的运行说明。能够演示：

```text
真实指标 Push
→ 插件产生评估
→ 正式巡检读取同一事实
→ 结果与风险可追溯
→ AI 使用页面中已保存的精简提示词解释
```

插件中心没有旧演示能力；真实数据与历史未丢失；原平台仍能继续增加其他代码插件。满足这些条件即可上线，不继续扩展本轮。

## 12. 源码与协议依据

[R02]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inference_performance/services/evaluator.py "性能评估总入口"
[R03]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inference_performance/services/ingest.py "单条与批量接入"
[R04]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inference_performance/services/baseline.py "14 天基线与动态判定"
[R08]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inference_performance/api.py "性能 API / latest 行为"
[R09]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inference_performance/schemas.py "输入校验"
[R10]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inspections/rules/registry.py "正式 CODE 插件注册表"
[R12]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inspections/services/execution.py "巡检执行 / CheckResult / Finding"
[R13]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inspections/services/trigger.py "手动触发 / 模拟数据依赖"
[R14]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inspections/services/manual_orchestrator.py "手动巡检编排"
[R15]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/core/management/commands/seed_launch.py "默认上线初始化"
[R16]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/airflow/dags/daily_iaas_inspection.py "每日 Airflow DAG"
[R17]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inspections/api_internal.py "Airflow 内部 API"
[R18]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/investigations/services/explanation.py "资源巡检 AI 解读"
[R19]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/investigations/services/dashboard_explanation.py "首页 AI 解读"
[R20]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/services/model_gateway/ollama.py "Ollama Provider"
[R21]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/services/model_gateway/base.py "模型响应的严格 JSON 协议"
[R23]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/frontend/src/pages/ResourceDetail/ResourceDetailPage.tsx "资源详情：并列显示两套结果"
[R24]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/frontend/src/pages/ResourceDetail/InferencePerformanceProfile.tsx "性能画像组件"
[R29]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/audits/models.py "现有 AuditEvent"
[R30]: https://github.com/underthedeepsea/iaas-inspection-platform/blob/8e044c769eb1817cd48ce081c2f95b161e32d4ec/apps/inspections/services/scope.py "环境和资产选择范围"
[Q01]: https://huggingface.co/Qwen/Qwen3.5-4B "Qwen 官方 Qwen3.5-4B 模型卡"
[Q02]: https://docs.ollama.com/capabilities/thinking "Ollama 官方 Thinking 参数"
[Q03]: https://docs.ollama.com/capabilities/structured-outputs "Ollama 官方 Structured Outputs"
