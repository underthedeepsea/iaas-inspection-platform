# 当前支持的推理引擎性能指标

核对日期：2026-10-08。范围：推理引擎性能画像插件 `llm.performance_profile`，支持 `vllm` 和 `sglang`。

当前接入 **20 个指标值**。指标由外部监控程序采集、按时间窗口聚合后推送，平台负责保存、展示和评估。

## 指标清单

字段路径相对于单条请求的 `sample`，或批量请求中每个 `samples[]` 元素。

| 分类 | 字段 | 指标含义 | 单位 / 范围 | 当前用途 |
| --- | --- | --- | --- | --- |
| 首 Token 延迟 | `ttft.avg_ms` | TTFT 平均值 | ms | 展示 |
| 首 Token 延迟 | `ttft.p90_ms` | TTFT P90 | ms | 展示 |
| 首 Token 延迟 | `ttft.p95_ms` | TTFT P95 | ms | 主判定 |
| 首 Token 延迟 | `ttft.p99_ms` | TTFT P99 | ms | 主判定 |
| 首 Token 延迟 | `ttft.e2e_ratio` | TTFT 占端到端延迟的比例 | 0–1 | 辅助证据 |
| 每 Token 延迟 | `tpot.avg_ms` | TPOT 平均值 | ms/token | 展示 |
| 每 Token 延迟 | `tpot.p90_ms` | TPOT P90 | ms/token | 展示 |
| 每 Token 延迟 | `tpot.p95_ms` | TPOT P95 | ms/token | 主判定 |
| 每 Token 延迟 | `tpot.p99_ms` | TPOT P99 | ms/token | 主判定 |
| 端到端延迟 | `e2e.avg_ms` | E2E 平均值 | ms | 展示 |
| 端到端延迟 | `e2e.p90_ms` | E2E P90 | ms | 展示 |
| 端到端延迟 | `e2e.p95_ms` | E2E P95 | ms | 主判定 |
| 端到端延迟 | `e2e.p99_ms` | E2E P99 | ms | 主判定 |
| 请求流量 | `traffic.qps` | 每秒请求数 | request/s | 负载上下文、相似负载筛选 |
| 请求流量 | `traffic.qpm` | 每分钟请求数 | request/min | 负载上下文、展示 |
| Token 吞吐 | `throughput.generation_tps` | 输出 Token 吞吐率 | token/s | 辅助证据 |
| Token 吞吐 | `throughput.prompt_tps` | 输入 Token 吞吐率 | token/s | 辅助证据 |
| KV Cache | `cache.kv_cache_hit_rate` | KV Cache 命中率 | 0–1 | 辅助证据 |
| 请求状态 | `requests.running` | 正在运行的请求数 | count | 辅助证据 |
| 请求状态 | `requests.waiting` | 正在排队的请求数 | count | 主判定 |

TPOT 字段沿用 `_ms` 命名，但其业务单位为 **毫秒/Token**。

## 当前评估能力

| 能力 | 覆盖范围 | 当前行为 |
| --- | --- | --- |
| 固定阈值 | 7 个主判定指标 | 根据 warning / critical 阈值判断；默认需连续 2 个有效采样命中 |
| 14 天动态基线 | 7 个主判定指标及 5 个辅助证据指标 | 计算中位数、MAD、变化幅度及动态边界；辅助指标记录为 `OBSERVED`，不单独抬高总体异常等级 |
| 相似负载筛选 | `traffic.qps` | 优先选择当前 QPS 的 0.5–1.5 倍范围内的历史样本 |
| 趋势判断 | 7 个主判定指标 | 默认比较最近 60 分钟前后两个时间段的中位数，输出 `STABLE` / `WATCH` / `DEGRADING` |
| 数据质量与时效 | 当前快照 | 区分空闲、待连续确认、数据过期和基线未就绪等状态 |

动态基线至少需要 100 个有效历史样本、覆盖 3 个日期。同等采样窗口、非空闲样本参与基线；只有满足相似 QPS 条件的主判定结果可以贡献总体动态异常等级。基线为零时返回 `NOT_EVALUABLE`。

趋势窗口前后两段各至少需要 3 个样本；趋势结果单独返回，不直接参与总体 `NORMAL` / `WARNING` / `CRITICAL` 等级计算。

阈值按 `ENGINE_MODEL → ENGINE → DEFAULT` 查找，支持引擎类型和精确模型名称覆盖。

## 接入约束

- 每个快照必须完整包含上述 20 个指标值及规定的分组；当前接口拒绝缺少或额外的指标字段。
- 指标值必须为有限、非负的数值，不接受布尔值或 `null`。
- `ttft.e2e_ratio` 和 `cache.kv_cache_hit_rate` 必须处于 0–1。
- TTFT、TPOT、E2E 各自满足 `P90 ≤ P95 ≤ P99`。
- 采样时间必须包含时区，且 `window_start < window_end`。
- 快照还需要来源、环境、引擎 ID、引擎类型、模型名称和样本 ID；这些是身份及时间信息，不计入 20 个指标值。

## API

| 操作 | 方法 | 路径 |
| --- | --- | --- |
| 推送单条快照 | POST | `/api/v1/inference-performance/snapshots` |
| 批量推送 / 历史回灌 | POST | `/api/v1/inference-performance/snapshots/batch` |
| 查询引擎列表 | GET | `/api/v1/inference-performance/engines?environment_id=...` |
| 查询当前性能画像 | GET | `/api/v1/inference-performance/engines/{engine_id}/profile?environment_id=...&engine_type=...&model_name=...` |

## 源码依据

- [快照字段与校验](../../apps/inference_performance/schemas.py)
- [主判定指标与固定阈值](../../apps/inference_performance/services/fixed.py)
- [动态基线与辅助指标](../../apps/inference_performance/services/baseline.py)
- [趋势算法](../../apps/inference_performance/services/trend.py)
- [总体状态与异常原因](../../apps/inference_performance/services/evaluator.py)
- [当前阈值配置](../../config/inference_performance_policies.json)
