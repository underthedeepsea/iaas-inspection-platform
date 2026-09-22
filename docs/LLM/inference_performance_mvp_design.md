# IaaS 智能巡检平台：推理引擎性能画像与动态异常判断设计文档（MVP）

> 目标：基于现有 `underthedeepsea/iaas-inspection-platform`，以最小改动上线一个可接收外部推理性能快照、能够进行固定阈值判断、14 天动态基线判断和趋势判断的 V1 功能。
>
> 本文档刻意删除复杂瓶颈分类、在线模板管理、GPU/Kubernetes 根因分析、多 Agent、机器学习预测等非首发必需能力。

---

## 1. 背景与现状

当前仓库已经存在：

- `LLM_RUNTIME` 资源类型；
- `LLM_INSTANCE` 资产类型；
- `llm.ttft_slo`、`llm.queue_backlog` 两条确定性规则；
- Django REST/API 基础结构；
- React 资源详情页面；
- `CheckResult / Finding / Risk / Evidence` 等风险闭环模型。

当前推理巡检仍主要建立在 `MockMetric` 和巡检 Run 上。新需求已经改变为：

> 监控指标由另一套程序负责采集和聚合，IaaS 智能巡检平台只接收标准化的性能快照并完成性能判断。

因此 V1 不再直接采集 vLLM/SGLang `/metrics`，也不接 Prometheus。

---

## 2. V1 目标

V1 必须回答三个问题：

1. **当前推理引擎的基本性能参数是什么？**
2. **当前是否正常？**
3. **如果异常，具体是哪几个性能指标导致的？它相对固定阈值和过去 14 天表现分别发生了什么变化？**

V1 支持两套判断能力：

- 固定阈值异常判断；
- 基于过去 14 天历史性能的动态异常判断，并提供近期趋势判断。

阈值必须根据：

- 推理引擎类型：`vllm` / `sglang`
- 模型名称：例如 `Qwen/Qwen3-32B`

自动选择。

若没有专属配置，则逐级回退：

```text
ENGINE_MODEL
    ↓ 未配置
ENGINE
    ↓ 未配置
DEFAULT
```

---

## 3. 明确不属于 V1 的内容

以下能力全部延期，不能阻塞首版上线：

- 直接采集 vLLM/SGLang 指标；
- Prometheus、DCGM、Kubernetes、GPU 指标采集；
- GPU/CPU/网络/显存硬件根因分析；
- 自动扩缩容；
- 自动调参；
- 性能预测；
- 机器学习异常检测；
- 多 Agent；
- 复杂瓶颈分类树；
- Alertmanager、短信、邮件、IM 等外部告警平台直连；
- 告警模板管理 UI；
- 告警模板在线 CRUD；
- GLOB/Regex 模型名称匹配；
- 模板优先级冲突解析；
- 自定义父模板 DAG；
- 将每条实时 Snapshot 强制转换成现有 `InspectionRun`；
- 自动创建现有 Risk 生命周期对象。

V1 输出标准化状态、严重度和原因，后续可无侵入接入现有 Risk/告警系统。

---

## 4. 外部输入指标

V1 接受以下指标，统一单位如下。

### 4.1 延迟指标

| 字段 | 单位 | 说明 |
|---|---:|---|
| `ttft.avg_ms` | ms | TTFT 平均值 |
| `ttft.p90_ms` | ms | TTFT P90 |
| `ttft.p95_ms` | ms | TTFT P95 |
| `ttft.p99_ms` | ms | TTFT P99 |
| `ttft.e2e_ratio` | 0~1 | TTFT 在 E2E 总延迟中的比例 |
| `tpot.avg_ms` | ms/token | TPOT 平均值 |
| `tpot.p90_ms` | ms/token | TPOT P90 |
| `tpot.p95_ms` | ms/token | TPOT P95 |
| `tpot.p99_ms` | ms/token | TPOT P99 |
| `e2e.avg_ms` | ms | E2E 平均延迟 |
| `e2e.p90_ms` | ms | E2E P90 |
| `e2e.p95_ms` | ms | E2E P95 |
| `e2e.p99_ms` | ms | E2E P99 |

### 4.2 流量、吞吐与队列指标

| 字段 | 单位 |
|---|---:|
| `traffic.qps` | request/s |
| `traffic.qpm` | request/min |
| `throughput.generation_tps` | token/s |
| `throughput.prompt_tps` | token/s |
| `cache.kv_cache_hit_rate` | 0~1 |
| `requests.running` | count |
| `requests.waiting` | count |

### 4.3 指标角色

不是所有指标都直接触发异常。

**V1 主判定指标：**

- TTFT P95 / P99
- TPOT P95 / P99
- E2E P95 / P99
- Waiting Requests

**辅助证据指标：**

- Generation TPS
- Prompt TPS
- KV Cache Hit Rate
- TTFT/E2E Ratio
- Running Requests

**负载上下文：**

- QPS
- QPM

原因：

- QPS 高不等于异常；
- Running 高不等于异常；
- Token Throughput 低可能只是没有请求；
- KV Cache Hit Rate 与业务 Prompt 重复度高度相关，不应单独作为首版硬告警。

---

## 5. 输入 API

### 5.1 单条实时 Snapshot

```http
POST /api/v1/inference-performance/snapshots
Content-Type: application/json
```

示例：

```json
{
  "source": "inference-monitor",
  "environment_id": "prod-a",
  "engine": {
    "engine_id": "qwen3-prod-01",
    "engine_type": "vllm",
    "model_name": "Qwen/Qwen3-32B"
  },
  "sample": {
    "sample_id": "qwen3-prod-01-20260922T160000",
    "window_start": "2026-09-22T15:59:00+08:00",
    "window_end": "2026-09-22T16:00:00+08:00",
    "ttft": {
      "avg_ms": 260.1,
      "p90_ms": 380.2,
      "p95_ms": 486.7,
      "p99_ms": 820.4,
      "e2e_ratio": 0.31
    },
    "tpot": {
      "avg_ms": 24.8,
      "p90_ms": 28.7,
      "p95_ms": 31.4,
      "p99_ms": 43.2
    },
    "e2e": {
      "avg_ms": 3210.5,
      "p90_ms": 4200.0,
      "p95_ms": 5100.0,
      "p99_ms": 7800.0
    },
    "traffic": {
      "qps": 8.6,
      "qpm": 516
    },
    "throughput": {
      "generation_tps": 1840.2,
      "prompt_tps": 4230.7
    },
    "cache": {
      "kv_cache_hit_rate": 0.68
    },
    "requests": {
      "running": 42,
      "waiting": 24
    }
  }
}
```

### 5.2 历史批量回灌

14 天动态判断要求历史数据，因此保留一个最小批量接口：

```http
POST /api/v1/inference-performance/snapshots/batch
```

约束：

- 单批最多 500 条；
- 使用与单条接口相同的 Snapshot Schema；
- 历史数据写入后默认不逐条执行实时告警；
- 最后一条可通过 `evaluate_latest=true` 执行一次当前评估。

### 5.3 查询当前画像

```http
GET /api/v1/inference-performance/engines/{engine_id}/profile?environment_id=prod-a
```

返回：

- 当前性能参数；
- 当前状态；
- 固定阈值结果；
- 14 天动态结果；
- 趋势；
- 异常原因；
- 实际生效的阈值模板来源。

---

## 6. 数据校验

V1 直接拒绝错误数据，避免错误输入污染 14 天历史。

必须满足：

- `engine_type ∈ {vllm, sglang}`；
- 所有数值必须为有限数；
- 延迟、吞吐、QPS、QPM、请求数不能为负；
- `0 <= kv_cache_hit_rate <= 1`；
- `0 <= ttft.e2e_ratio <= 1`；
- `p90 <= p95 <= p99`；
- `window_start < window_end`；
- 时间必须包含 timezone；
- `source + sample_id` 幂等唯一。

重复提交同一个 `source + sample_id` 返回原结果，不重复写入。

---

## 7. 数据模型

为了减少首版迁移复杂度，V1 不为每个指标创建单独数据库列，而使用一个 JSON 指标字段。

```python
class InferencePerformanceSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)

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
```

关键约束：

```text
UNIQUE(source, sample_id)

INDEX(environment, engine_id, window_end)
INDEX(engine_type, model_name, window_end)
```

理由：

- V1 的查询核心是“某个 Engine 最近 14 天 Snapshot”；
- 指标只需读取，不需要数据库内复杂聚合；
- JSONField 可避免 20+ 指标字段导致首版迁移与 API 映射过重；
- 动态计算在 Python 中完成；
- 若未来数据量达到必须数据库聚合的规模，再拆列或使用时序数据库，不在 V1 解决。

---

# 8. 告警模板设计

## 8.1 V1 只做三层

```text
DEFAULT
  ↓
ENGINE
  ↓
ENGINE_MODEL
```

匹配顺序：

```text
1. engine_type + model_name EXACT
2. engine_type
3. DEFAULT
```

只支持 **EXACT 模型名**。

V1 不支持：

- GLOB；
- Regex；
- priority；
- 任意 parent；
- 在线 CRUD。

这是主动删减，而不是缺失。

---

## 8.2 配置文件

建议新增：

```text
config/inference_performance_policies.json
```

结构：

```json
{
  "default": {
    "fixed": {
      "ttft.p95_ms": {"warning": 800, "critical": 1500},
      "ttft.p99_ms": {"warning": 1500, "critical": 3000},
      "tpot.p95_ms": {"warning": 50, "critical": 80},
      "tpot.p99_ms": {"warning": 80, "critical": 120},
      "e2e.p95_ms": {"warning": 10000, "critical": 20000},
      "e2e.p99_ms": {"warning": 20000, "critical": 30000},
      "requests.waiting": {"warning": 10, "critical": 30}
    },
    "dynamic": {
      "warning_z": 3.0,
      "critical_z": 5.0,
      "warning_change_ratio": 0.20,
      "critical_change_ratio": 0.40
    },
    "trend": {
      "window_minutes": 60,
      "watch_change_ratio": 0.10,
      "degrading_change_ratio": 0.20
    },
    "persistence": {
      "consecutive_hits": 2
    }
  },

  "engines": {
    "vllm": {},
    "sglang": {}
  },

  "models": {
    "vllm": {
      "Qwen/Qwen3-32B": {
        "fixed": {
          "ttft.p95_ms": {"warning": 500, "critical": 900}
        }
      }
    }
  }
}
```

注意：

> 文档中的数值是初始示例值，不代表所有模型的通用生产 SLO。上线前应由运维根据现网目标调整父模板。

---

## 8.3 继承算法

```python
resolved = deep_merge(DEFAULT, ENGINE[engine_type])
resolved = deep_merge(resolved, MODEL[engine_type][model_name])
```

模型模板只写差异项。

例如模型只覆盖 TTFT：

```json
{
  "fixed": {
    "ttft.p95_ms": {
      "warning": 400,
      "critical": 700
    }
  }
}
```

TPOT、E2E、Waiting 等继续继承父模板。

每次 Evaluation 保存：

```json
{
  "policy_source": {
    "default": true,
    "engine": "vllm",
    "model": "Qwen/Qwen3-32B",
    "config_hash": "sha256:..."
  }
}
```

这样配置变化后仍能解释历史结果。

---

# 9. 固定阈值算法

主判定指标按“越高越差”处理。

```python
if current >= critical:
    raw_status = "CRITICAL"
elif current >= warning:
    raw_status = "WARNING"
else:
    raw_status = "NORMAL"
```

## 9.1 防抖

V1 统一使用：

```text
consecutive_hits = 2
```

即同一指标连续两个 Snapshot 达到 WARNING/CRITICAL 才产生有效异常。

目的：

- 减少单点尖峰误报；
- 不引入复杂 M/N 窗口策略。

结果同时保存：

- `raw_status`
- `effective_status`

---

# 10. 14 天动态基线

## 10.1 历史范围

基线只使用：

```text
environment
+ engine_id
+ engine_type
+ model_name
```

完全相同的历史 Snapshot。

时间：

```text
current.window_end - 14 days
~
current.window_end
```

V1 不额外引入 GPU 型号、TP 数、部署配置 hash 等 profile 维度。

如果部署配置发生大改，建议更换 `engine_id`，从而自然建立新基线。

---

## 10.2 样本上限

避免每次实时请求处理无限历史数据：

```text
max_baseline_samples = 4096
```

若 14 天内样本超过 4096：

- 按时间等间距采样；
- 保留完整 14 天时间跨度。

---

## 10.3 相似负载过滤

为了避免低负载和高负载混在一起，V1 只做非常简单的 QPS 筛选。

若当前 `qps > 0`：

```text
0.5 × current_qps
<= historical_qps <=
1.5 × current_qps
```

若满足条件的样本数 >= 50：

> 使用相似 QPS 历史。

否则：

> 回退到完整 14 天历史。

V1 不做最近邻、不做多维负载距离、不做聚类。

---

## 10.4 Robust Baseline

对主判定指标计算：

```text
Median = median(X)

MAD = median(|Xi - Median|)

RobustSigma = 1.4826 × MAD
```

对于延迟、Waiting 这种“越高越差”的指标：

```text
WarningBoundary =
max(
    Median × (1 + warning_change_ratio),
    Median + warning_z × RobustSigma
)

CriticalBoundary =
max(
    Median × (1 + critical_change_ratio),
    Median + critical_z × RobustSigma
)
```

默认：

```text
warning_z = 3
critical_z = 5

warning_change_ratio = 20%
critical_change_ratio = 40%
```

同时满足“明显偏离历史分布”和“业务变化幅度足够大”，降低过度敏感。

---

## 10.5 动态基线 Ready 条件

V1 只保留两种状态：

```text
READY
NOT_READY
```

满足：

```text
sample_count >= 100
AND
distinct_days >= 3
```

才执行动态异常判断。

不足时：

```json
{
  "dynamic_status": "NOT_READY"
}
```

固定阈值仍然正常工作。

---

# 11. 趋势判断

V1 不使用 Theil-Sen、线性回归或时间序列模型。

只使用最近 60 分钟：

```text
前半窗口 Median
vs
后半窗口 Median
```

例如对 TTFT P95：

```text
change_ratio =
(second_half_median - first_half_median)
/
max(first_half_median, epsilon)
```

对“越高越差”的主判定指标：

```text
change < 10%      → STABLE
10% ~ 20%         → WATCH
>= 20%            → DEGRADING
```

趋势 **不直接提升 Overall Status**。

因此允许：

```text
Overall: NORMAL
Trend: DEGRADING
```

含义：

> 当前尚未违反固定或动态异常边界，但近期表现正在恶化。

这是 V1 用于提前观察的能力，不作为告警触发器。

---

# 12. 总体状态

V1 状态：

```text
NORMAL
WARNING
CRITICAL
UNKNOWN
```

规则：

1. 核心指标缺失或非法 → `UNKNOWN` / API 拒绝；
2. 任一有效固定阈值 CRITICAL → `CRITICAL`；
3. 任一有效动态异常 CRITICAL → `CRITICAL`；
4. 任一有效固定/动态 WARNING → `WARNING`；
5. 其余 → `NORMAL`。

不使用加权总分决定异常。

原因：

> 严重 TTFT 异常不能被其他正常指标“平均掉”。

可额外展示一个非决策性的 Health Score，但 V1 不要求实现。

---

# 13. 异常原因输出

V1 不实现复杂根因分类器。

只输出**确定性原因列表**。

例如：

```json
{
  "status": "WARNING",
  "reasons": [
    {
      "code": "TTFT_P95_DYNAMIC_HIGH",
      "metric": "ttft.p95_ms",
      "current": 486.7,
      "baseline_median": 272.1,
      "dynamic_warning": 351.4,
      "change_ratio": 0.789
    },
    {
      "code": "WAITING_REQUESTS_FIXED_HIGH",
      "metric": "requests.waiting",
      "current": 24,
      "fixed_warning": 10
    }
  ]
}
```

再由前端或现有 AI 解释模块生成：

> TTFT 未达到模型固定 Critical 阈值，但相较 14 天同类负载基线显著恶化，同时排队请求超过固定 Warning 阈值。

V1 不输出：

> GPU 饱和、显存瓶颈、Prefill 根因、Decode 根因

因为现有输入证据无法可靠证明这些结论。

---

# 14. 性能画像返回结构

```json
{
  "engine": {
    "engine_id": "qwen3-prod-01",
    "engine_type": "vllm",
    "model_name": "Qwen/Qwen3-32B"
  },

  "status": "WARNING",

  "fixed": {
    "status": "WARNING"
  },

  "dynamic": {
    "status": "WARNING",
    "baseline_state": "READY",
    "baseline_days": 14,
    "sample_count": 2831
  },

  "trend": {
    "status": "DEGRADING",
    "window_minutes": 60
  },

  "policy_source": {
    "level": "ENGINE_MODEL",
    "config_hash": "sha256:..."
  },

  "current_metrics": {},

  "reasons": []
}
```

---

# 15. 与当前仓库的集成方式

新增独立 app：

```text
apps/inference_performance/
    __init__.py
    apps.py
    models.py
    urls.py
    api.py
    schemas.py

    services/
        ingest.py
        policy.py
        fixed.py
        baseline.py
        trend.py
        evaluator.py
```

并在：

```text
apps/api/urls.py
```

增加：

```python
path("", include("apps.inference_performance.urls"))
```

## 为什么不直接扩展 `llm_ttft_slo.py`

现有规则是“巡检 Run + MockMetric”模型。

新功能是“实时外部 Snapshot + 14 天历史状态”。

两者生命周期不同。

强行复用会导致：

- 每个 Snapshot 都需要造 InspectionRun；
- 需要构造 Dataset；
- 使实时性能判断和批量巡检耦合；
- 首版工作量和错误面明显增加。

因此 V1 独立实现是最小上线方案。

后续可新增一个轻量 Inspection Rule：

```text
llm.performance_profile
```

只读取最新 Evaluation，再映射为现有 CheckResult / Finding / Risk。

---

# 16. 最小前端

只修改 `LLM_RUNTIME` 页面。

新增一个“性能画像”区域，展示：

1. Engine / Model；
2. Overall Status；
3. TTFT / TPOT / E2E；
4. QPS / Token TPS；
5. KV Hit；
6. Running / Waiting；
7. Fixed 状态；
8. 14d Dynamic 状态；
9. Trend；
10. Reasons。

V1 不做复杂性能 Dashboard，不做可拖拽图表，不做模板编辑页面。

---

# 17. 告警联动边界

V1 不直接调用外部告警系统。

Evaluation 已输出：

```text
status
severity
reason_codes
engine_id
model_name
current_value
threshold/baseline
```

这些字段已经满足后续告警联动。

未来可以：

```text
Evaluation
   ↓
Alert Adapter
   ↓
Alertmanager / 企业告警平台
```

也可以：

```text
Evaluation
   ↓
llm.performance_profile Inspection Rule
   ↓
CheckResult
   ↓
Finding / Risk
```

但均不作为 V1 Release Gate。

---

# 18. V1 Release Gate

满足以下条件才算完成：

### 输入
- 单条 Snapshot 接口可用；
- Batch 历史回灌可用；
- 幂等生效；
- 非法指标拒绝。

### 模板
- DEFAULT 生效；
- ENGINE 覆盖 DEFAULT；
- ENGINE_MODEL 精确覆盖 ENGINE；
- 未配置字段正确继承；
- 返回生效配置 hash。

### 固定判断
- Warning / Critical 正确；
- 连续两次命中才生效；
- QPS、Running 不会单独触发异常。

### 动态判断
- 使用 14 天窗口；
- Median/MAD 正确；
- QPS 相似负载过滤正确；
- 样本不足返回 NOT_READY；
- 异常偏离能够产生 Warning/Critical。

### 趋势
- 60 分钟前后半窗口比较；
- STABLE/WATCH/DEGRADING 正确；
- 趋势不直接触发 Overall Alert。

### 页面
- LLM_RUNTIME 能展示最新性能画像；
- 异常时明确展示具体原因。

---

# 19. 最终 V1 数据流

```text
外部监控程序
      │
      │ POST Snapshot
      ↓
Inference Performance API
      │
      ├── 校验 + 幂等
      │
      ├── 保存 Snapshot
      │
      ↓
Policy Resolver
DEFAULT → ENGINE → ENGINE_MODEL
      │
      ├───────────────┐
      ↓               ↓
Fixed Evaluator   14d Baseline
                      │
                      ↓
                Dynamic Evaluator
                      │
                      ↓
                Trend Evaluator
      │               │
      └───────┬───────┘
              ↓
       Overall Evaluation
              │
      status + reasons
              │
              ↓
      LLM_RUNTIME 性能画像
```

这就是 V1 的完整闭环。
