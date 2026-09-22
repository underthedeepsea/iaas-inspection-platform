# IaaS 智能巡检平台：推理引擎性能画像 MVP 实施文档

> 本实施计划对应《推理引擎性能画像与动态异常判断设计文档（MVP）》。
>
> 开发目标：优先实现可上线闭环，不扩展到复杂 AIOps、GPU 根因分析或在线模板系统。

---

# 1. 开发原则

本轮只开发：

```text
Snapshot 接入
→ 历史保存
→ 模板解析
→ 固定阈值
→ 14d 动态基线
→ 趋势
→ 状态/原因
→ LLM_RUNTIME 页面展示
```

以下任务一律不插入本轮：

- GPU/Kubernetes 数据接入；
- 外部 Alertmanager；
- 自动 Risk 生命周期；
- 复杂瓶颈分类；
- 模型预测；
- 模板 UI；
- 模板 CRUD；
- GLOB/Regex 匹配；
- Redis/Celery/MQ；
- 新时序数据库。

---

# 2. 推荐开发顺序

```text
P0-1 数据模型与 Schema
P0-2 Policy Resolver
P0-3 Fixed Evaluator
P0-4 14d Baseline + Dynamic Evaluator
P0-5 Trend Evaluator
P0-6 Snapshot API
P0-7 Profile API
P0-8 LLM_RUNTIME 最小页面
P0-9 测试与 Release Gate
```

必须按顺序实施。

---

# 3. P0-1：新增 inference_performance App

创建：

```text
apps/inference_performance/
    __init__.py
    apps.py
    models.py
    urls.py
    api.py
    schemas.py

    services/
        __init__.py
        ingest.py
        policy.py
        fixed.py
        baseline.py
        trend.py
        evaluator.py
```

在：

```text
config/settings/base.py
```

加入 App。

在：

```text
apps/api/urls.py
```

加入：

```python
path("", include("apps.inference_performance.urls"))
```

---

# 4. P0-1：数据库模型

新增：

```python
class InferencePerformanceSnapshot(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    environment = models.ForeignKey(
        "core.Environment",
        on_delete=models.CASCADE,
    )

    source = models.CharField(max_length=64)
    sample_id = models.CharField(max_length=192)

    engine_id = models.CharField(max_length=192)
    engine_type = models.CharField(max_length=32)
    model_name = models.CharField(max_length=256)

    window_start = models.DateTimeField()
    window_end = models.DateTimeField(db_index=True)

    metrics = models.JSONField(default=dict)
    evaluation = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "sample_id"],
                name="uq_inference_perf_source_sample",
            )
        ]

        indexes = [
            models.Index(
                fields=["environment", "engine_id", "window_end"],
                name="idx_inf_perf_engine_time",
            ),
            models.Index(
                fields=["engine_type", "model_name", "window_end"],
                name="idx_inf_perf_model_time",
            ),
        ]
```

不要在 V1 拆成 20+ 指标列。

---

# 5. P0-1：输入 Schema

`schemas.py` 负责：

- JSON 结构检查；
- 类型检查；
- 单位边界检查；
- percentile 顺序检查；
- timestamp 检查。

建议使用 Python dataclass，不额外引入 Pydantic。

核心结构：

```python
@dataclass(frozen=True)
class EngineIdentity:
    engine_id: str
    engine_type: str
    model_name: str


@dataclass(frozen=True)
class PerformanceSample:
    sample_id: str
    window_start: datetime
    window_end: datetime
    metrics: dict
```

必须验证：

```text
engine_type = vllm | sglang
latency >= 0
qps/qpm >= 0
throughput >= 0
requests >= 0
0 <= cache_hit <= 1
0 <= ttft_e2e_ratio <= 1
p90 <= p95 <= p99
window_start < window_end
```

复用现有：

```text
apps/api/http.py
```

中的：

- `parse_json_object`
- `APIRequestError`
- `api_error`

保持 API 错误格式一致。

---

# 6. P0-2：Policy 配置

新增：

```text
config/inference_performance_policies.json
```

首版结构：

```json
{
  "default": {},
  "engines": {
    "vllm": {},
    "sglang": {}
  },
  "models": {
    "vllm": {},
    "sglang": {}
  }
}
```

不要建数据库表。

不要建 CRUD API。

不要建模板管理页面。

---

# 7. P0-2：Policy Resolver

`services/policy.py`

接口：

```python
@dataclass(frozen=True)
class ResolvedPolicy:
    policy: dict
    level: str
    config_hash: str


def resolve_policy(
    *,
    engine_type: str,
    model_name: str,
) -> ResolvedPolicy:
    ...
```

算法：

```python
result = deepcopy(config["default"])
level = "DEFAULT"

if engine_type in config["engines"]:
    result = deep_merge(result, config["engines"][engine_type])
    level = "ENGINE"

model_config = (
    config.get("models", {})
          .get(engine_type, {})
          .get(model_name)
)

if model_config:
    result = deep_merge(result, model_config)
    level = "ENGINE_MODEL"
```

`deep_merge` 规则：

- dict 递归覆盖；
- 标量直接覆盖；
- 不支持删除父字段；
- 不支持 list 合并。

计算：

```python
config_hash = sha256(
    json.dumps(result, sort_keys=True).encode()
).hexdigest()
```

测试必须覆盖：

1. Default；
2. Engine；
3. Engine + Model；
4. 部分字段继承。

---

# 8. P0-3：Fixed Evaluator

文件：

```text
services/fixed.py
```

接口：

```python
def evaluate_fixed(
    *,
    current_metrics: dict,
    policy: dict,
    previous_evaluations: list[dict],
) -> dict:
    ...
```

只判断：

```text
ttft.p95_ms
ttft.p99_ms
tpot.p95_ms
tpot.p99_ms
e2e.p95_ms
e2e.p99_ms
requests.waiting
```

每项返回：

```json
{
  "metric": "ttft.p95_ms",
  "current": 486.7,
  "warning": 500,
  "critical": 900,
  "raw_status": "NORMAL",
  "effective_status": "NORMAL"
}
```

防抖：

```text
连续 2 个 Snapshot 命中后才 effective。
```

实现时只查询最近两个相同 Engine Snapshot 的 `evaluation.fixed.metrics`。

不要实现复杂 M/N。

---

# 9. P0-4：14 天 Baseline

文件：

```text
services/baseline.py
```

接口：

```python
@dataclass(frozen=True)
class MetricBaseline:
    median: float
    mad: float
    robust_sigma: float
    sample_count: int


@dataclass(frozen=True)
class HistoricalBaseline:
    state: str
    days_covered: int
    sample_count: int
    metrics: dict[str, MetricBaseline]


def build_baseline(
    *,
    snapshot,
    max_samples: int = 4096,
) -> HistoricalBaseline:
    ...
```

查询条件：

```python
environment=snapshot.environment
engine_id=snapshot.engine_id
engine_type=snapshot.engine_type
model_name=snapshot.model_name
window_end__gte=snapshot.window_end - timedelta(days=14)
window_end__lt=snapshot.window_end
```

---

# 10. Baseline Downsample

若：

```text
len(history) <= 4096
```

直接使用。

否则：

```python
step = len(history) / 4096
selected = [
    history[int(i * step)]
    for i in range(4096)
]
```

不要引入 NumPy/Pandas 依赖。

使用 Python `statistics.median`。

---

# 11. QPS 相似负载筛选

读取：

```text
current_qps
```

若：

```text
current_qps > 0
```

筛选：

```python
low = current_qps * 0.5
high = current_qps * 1.5

comparable = [
    item
    for item in history
    if low <= item.metrics["traffic"]["qps"] <= high
]
```

如果：

```text
len(comparable) >= 50
```

使用 comparable。

否则：

```text
fallback full 14d history
```

在结果中标记：

```json
{
  "load_filter": "QPS_COMPARABLE"
}
```

或：

```json
{
  "load_filter": "FULL_HISTORY_FALLBACK"
}
```

---

# 12. Baseline Ready

条件：

```text
sample_count >= 100
AND
distinct_days >= 3
```

不满足：

```text
state = NOT_READY
```

满足：

```text
state = READY
```

不要加入 LOW/MATURE 等更多状态。

---

# 13. P0-4：Dynamic Evaluator

文件：

```text
services/baseline.py
```

或单独：

```text
services/dynamic.py
```

为减少文件数量，建议放在 `baseline.py`。

接口：

```python
def evaluate_dynamic(
    *,
    current_metrics: dict,
    baseline: HistoricalBaseline,
    policy: dict,
) -> dict:
    ...
```

公式：

```python
sigma = 1.4826 * MAD

warning_boundary = max(
    median * (1 + warning_change_ratio),
    median + warning_z * sigma,
)

critical_boundary = max(
    median * (1 + critical_change_ratio),
    median + critical_z * sigma,
)
```

如果：

```text
baseline.state == NOT_READY
```

返回：

```json
{
  "status": "NOT_READY"
}
```

主判定指标与 Fixed 相同。

辅助指标：

- generation_tps
- prompt_tps
- kv_cache_hit_rate
- running requests
- ttft.e2e_ratio

只计算偏离并作为 evidence，不直接改变 Overall Status。

---

# 14. MAD=0 处理

历史数据可能完全相同。

如果：

```text
MAD == 0
```

则：

```text
RobustSigma = 0
```

动态边界仍由：

```text
median × (1 + change_ratio)
```

提供最低变化门槛。

禁止用极小 epsilon 造成“微小变化被判巨大 Z-score”。

---

# 15. P0-5：Trend Evaluator

文件：

```text
services/trend.py
```

接口：

```python
def evaluate_trend(
    *,
    snapshot,
    policy: dict,
) -> dict:
    ...
```

查询最近：

```text
60 minutes
```

至少需要：

```text
6 samples
```

不足：

```text
NOT_READY
```

否则按时间排序，均分两组：

```python
first_half
second_half
```

分别取 Median。

对主判定指标：

```python
change = (
    second_median - first_median
) / max(first_median, 1e-9)
```

规则：

```text
< 10%      STABLE
10%-20%    WATCH
>= 20%     DEGRADING
```

Trend 不改变 Overall Status。

---

# 16. P0-6：Overall Evaluator

文件：

```text
services/evaluator.py
```

接口：

```python
def evaluate_snapshot(snapshot) -> dict:
    policy = resolve_policy(...)
    fixed = evaluate_fixed(...)
    baseline = build_baseline(...)
    dynamic = evaluate_dynamic(...)
    trend = evaluate_trend(...)

    result = combine(...)
    return result
```

组合规则：

```text
Fixed CRITICAL   → CRITICAL
Dynamic CRITICAL → CRITICAL

Fixed WARNING    → WARNING
Dynamic WARNING  → WARNING

其他             → NORMAL
```

`Trend=DEGRADING` 不改变 Overall。

输出：

```json
{
  "status": "WARNING",
  "fixed": {},
  "dynamic": {},
  "trend": {},
  "policy_source": {},
  "reasons": []
}
```

---

# 17. Reasons 生成

不要做复杂瓶颈分类。

根据触发项直接生成 Reason。

例如：

```python
{
    "code": "TTFT_P95_DYNAMIC_HIGH",
    "metric": "ttft.p95_ms",
    "current": 486.7,
    "baseline_median": 272.1,
    "boundary": 351.4,
}
```

固定阈值：

```python
{
    "code": "WAITING_REQUESTS_FIXED_HIGH",
    "metric": "requests.waiting",
    "current": 24,
    "threshold": 10,
}
```

前端按 `code` 显示中文。

这比首版加入 Root Cause Classifier 更可靠。

---

# 18. P0-6：Single Snapshot API

路径：

```text
POST /api/v1/inference-performance/snapshots
```

步骤：

```text
1. parse JSON
2. validate schema
3. resolve environment
4. check idempotency
5. save snapshot
6. evaluate
7. save evaluation JSON
8. return response
```

事务：

```python
@transaction.atomic
```

幂等：

```text
(source, sample_id)
```

已存在时直接返回已存在 Snapshot 与 Evaluation。

---

# 19. P0-6：Batch API

路径：

```text
POST /api/v1/inference-performance/snapshots/batch
```

约束：

```text
1 <= samples <= 500
```

参数：

```json
{
  "source": "inference-monitor",
  "environment_id": "prod-a",
  "engine": {},
  "evaluate_latest": true,
  "samples": []
}
```

实现：

- 批量 validate；
- `bulk_create(ignore_conflicts=True)`；
- 默认仅最后一个 Snapshot evaluate；
- 不逐条跑 14 天算法。

这是用于首次 14 天历史回灌的最小实现。

---

# 20. P0-7：Profile API

路径：

```text
GET /api/v1/inference-performance/engines/{engine_id}/profile
```

query：

```text
environment_id
```

返回最新 Snapshot：

```json
{
  "engine": {},
  "window": {},
  "status": "WARNING",
  "current_metrics": {},
  "fixed": {},
  "dynamic": {},
  "trend": {},
  "policy_source": {},
  "reasons": []
}
```

如果不存在数据：

```text
404 ENGINE_PERFORMANCE_NOT_FOUND
```

---

# 21. P0-8：最小前端

修改：

```text
frontend/src/pages/ResourceDetail/ResourceDetailPage.tsx
```

当：

```text
resourceCode == LLM_RUNTIME
```

在 Overview 增加：

```text
推理性能画像
```

首版只需要：

```text
Engine ID
Model
Engine Type
Status

TTFT P95
TPOT P95
E2E P95

QPS
Generation TPS
Prompt TPS

KV Hit
Running
Waiting

Fixed
Dynamic 14d
Trend

异常原因
```

不要在 V1 开发：

- 大量图表；
- 模板配置页面；
- 高级筛选；
- 复杂 Drill Down；
- 图形化 Root Cause。

---

# 22. 前端 API

新增：

```text
frontend/src/api/inferencePerformance.ts
```

接口：

```typescript
export async function getInferenceProfile(
  environmentId: string,
  engineId: string,
): Promise<InferenceProfile>
```

如果当前产品没有 engine 选择入口，可先允许通过最新 engine 展示；多 engine 列表页作为下一小版本补充，不阻塞后端上线。

---

# 23. 单元测试

## Policy

```text
test_default_policy
test_engine_override
test_engine_model_override
test_partial_model_override_inherits_parent
test_policy_hash_stable
```

## Schema

```text
test_reject_negative_latency
test_reject_invalid_ratio
test_reject_invalid_percentile_order
test_reject_unknown_engine
test_reject_naive_timestamp
```

## Fixed

```text
test_fixed_normal
test_fixed_warning
test_fixed_critical
test_fixed_requires_two_consecutive_hits
```

## Baseline

```text
test_baseline_14_day_window
test_baseline_qps_comparable_filter
test_baseline_qps_fallback
test_baseline_not_ready
test_mad_robust_to_outlier
test_mad_zero_uses_change_ratio
```

## Dynamic

```text
test_dynamic_normal
test_dynamic_warning
test_dynamic_critical
test_dynamic_not_ready
```

## Trend

```text
test_trend_stable
test_trend_watch
test_trend_degrading
test_trend_not_ready
```

---

# 24. API 测试

```text
test_snapshot_ingest
test_snapshot_idempotency
test_snapshot_validation_error
test_batch_ingest
test_batch_limit
test_batch_evaluate_latest
test_profile_latest
test_profile_not_found
```

必须验证 API 错误格式继续符合：

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "details": {},
    "trace_id": "..."
  }
}
```

与当前 `apps/api/http.py` 一致。

---

# 25. 前端测试

至少覆盖：

```text
LLM_RUNTIME 有数据 → 展示 Profile
NORMAL → 正常状态
WARNING → 展示原因
Dynamic NOT_READY → 显示“历史基线建立中”
API 无数据 → 显示“暂无性能数据”
```

不要求本轮新增复杂 E2E 图表测试。

---

# 26. 性能约束

为了防止动态算法拖慢接口：

```text
14d baseline max samples = 4096
Batch max = 500
Trend window = 60m
```

Release Gate 建议：

```text
单 Engine、4096 历史样本情况下，
一次实时 Snapshot 保存 + Evaluate
开发环境目标 < 1.5s
```

如果超过：

1. 先检查重复数据库查询；
2. 不立即引入 Redis；
3. 不立即引入异步 MQ；
4. 优先减少 queryset 与 Python 重复解析。

---

# 27. 数据保留

V1 默认：

```text
保留 30 天 Snapshot
```

但 V1 不开发自动清理任务。

可以先通过运维 cron 定期执行 Django management command。

如果已有统一数据库清理机制，则接入现有机制。

---

# 28. 建议新增管理命令

只增加一个简单命令：

```text
python manage.py prune_inference_performance --days 30
```

这是唯一推荐的运维辅助命令。

不要为首版引入 Celery Beat / Airflow 清理 DAG。

---

# 29. 与现有 llm.ttft_slo / llm.queue_backlog 的关系

首版：

```text
保留现有规则
不删除
不重写
```

新模块独立上线。

原因：

- 现有规则属于 InspectionRun；
- 新模块属于 Streaming Snapshot；
- 在 V1 合并两条生命周期风险较大。

后续验证稳定后再新增：

```text
llm.performance_profile
```

读取最新 Performance Evaluation，统一代替旧两条规则。

本轮不做这个迁移。

---

# 30. 告警联动实施边界

V1 只输出：

```text
status
reason_codes
metric
current
fixed_threshold
dynamic_boundary
baseline_median
engine_id
engine_type
model_name
```

这些字段后续可直接映射到：

```text
Alertmanager
企业告警平台
Finding
Risk
```

本轮不实现任何外部发送。

---

# 31. Release Gate

## 后端

必须全部通过：

```text
python manage.py check
python manage.py makemigrations --check
pytest
```

重点新增测试必须 100% 通过。

## 前端

```text
npm test
npm run build
```

## 手工验收

### Case A：默认模板

发送未知模型：

```text
engine=vllm
model=unknown-model
```

验证：

```text
policy level = ENGINE 或 DEFAULT
```

### Case B：模型覆盖

发送：

```text
engine=vllm
model=Qwen/Qwen3-32B
```

验证使用模型级 TTFT 阈值。

### Case C：固定异常

连续两次 TTFT P95 超 Warning。

期望：

```text
WARNING
reason=TTFT_P95_FIXED_HIGH
```

### Case D：动态异常

固定阈值未超，但当前 TTFT 明显偏离 14d。

期望：

```text
WARNING
reason=TTFT_P95_DYNAMIC_HIGH
```

### Case E：趋势恶化

当前仍 NORMAL，但最近 60m 后半段比前半段恶化 >20%。

期望：

```text
status=NORMAL
trend=DEGRADING
```

### Case F：历史不足

历史 <100 点。

期望：

```text
dynamic=NOT_READY
fixed 正常工作
```

---

# 32. 开发任务清单

建议 Codex 按以下顺序逐项完成，不并行扩范围。

```text
[ ] 1. 创建 inference_performance app
[ ] 2. 新增 Snapshot model + migration
[ ] 3. 完成 input schema validation
[ ] 4. 新增 policies JSON
[ ] 5. 完成 policy resolver
[ ] 6. 完成 fixed evaluator
[ ] 7. 完成 baseline builder
[ ] 8. 完成 dynamic evaluator
[ ] 9. 完成 trend evaluator
[ ] 10. 完成 overall evaluator
[ ] 11. 完成 single ingest API
[ ] 12. 完成 batch ingest API
[ ] 13. 完成 profile API
[ ] 14. 后端测试
[ ] 15. LLM_RUNTIME 最小前端
[ ] 16. 前端测试
[ ] 17. Release Gate
```

任何以下需求在本清单完成前不得插入：

```text
Root Cause AI
GPU 指标
模板 UI
外部告警
自动扩缩容
图表大屏
模型预测
```

---

# 33. 完成定义

本轮完成的标准不是“功能很多”，而是：

> 外部程序能够稳定推送 vLLM/SGLang 性能快照；平台能根据模型和引擎自动选择阈值；能够判断固定阈值异常；能够基于 14 天历史判断动态异常；能够判断近期趋势；能够明确告诉用户哪一项指标导致异常；LLM_RUNTIME 页面能够展示结果。

达到以上标准即可上线。
