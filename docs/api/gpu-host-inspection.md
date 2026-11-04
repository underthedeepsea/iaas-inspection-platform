# GPU / 宿主机巡检接入

外部采集系统负责聚合，服务端不直连驱动或 SSH。POST `/api/v1/hardware-health/snapshots`，GET `/api/v1/hardware-health/profiles?environment_id=<id或slug>&resource_type=GPU_POOL|HOST`。接入后执行 `python manage.py migrate`、`python manage.py seed_launch`，即可在 GPU 资源、主机基础环境页面发起正式巡检。混合选择 LLM/GPU/HOST 使用同一 Run，保留各插件独立输入。

请求顶层：`source`、`environment_id`、`sample_id`、`window_start`、`window_end`、`host_id`、`config_id`、`kind`（GPU/HOST）、`identity`、`metrics`、`bindings`。时间均带时区，窗口左闭右开，采集时间必须落在窗口内或结束后最多 5 分钟。服务端拒绝未来窗口。source/sample_id 在环境内幂等，内容改变返回 409；重叠但不相同窗口拒绝，避免重复计数和趋势污染。

GPU identity 为 `{gpu_uuid, model}`，HOST identity 为 `{}`。metrics 为以组件键为索引的对象；GPU 仅 `gpu`，HOST 包含 `host`，以及 `filesystem:<稳定ID>` / `disk:<稳定ID>`。每组件有 `identity` 和 `values`。文件系统 identity 是 `{filesystem,mountpoint,block_device}`；磁盘为 `{block_device}`；GPU/host组件 identity 为空对象。值结构为 `{value,quality,collected_at}`，quality 为 VALID/MISSING/UNSUPPORTED/RESET；非 VALID 的 value 必须为 null。不可缺测填零。每种组件要求所有对应指标键，unsupported可显式填写。

| 组件 | 指标键 |
| --- | --- |
| gpu | utilization_ratio, memory_used_bytes, memory_total_bytes, temperature_celsius, xid_events, ecc_sbe_delta, ecc_dbe_delta |
| host | cpu_busy_ratio, memory_available_bytes, memory_total_bytes |
| filesystem | available_bytes, size_bytes |
| disk | read_bytes_per_second, write_bytes_per_second, read_latency_avg_ms, write_latency_avg_ms, io_busy_ratio |

## Linux HOST 外部来源与内存单位

巡检目标为 Linux 服务器；接入方负责从可信的目标服务器来源采集和聚合，再经现有快照 API 推送。服务端接收已换算为 bytes 的数值，本仓库不新增 proc、SSH 或 Prometheus 采集器，也不根据开发宿主操作系统推断服务器语义。

- `metrics.host.values.memory_available_bytes` 对应 Linux `/proc/meminfo` 的 `MemAvailable`；该字段按 kB 输出时，外部采集方乘 **1024** 转为 bytes。
- `metrics.host.values.memory_total_bytes` 对应同一来源的 `MemTotal`；kB 输出同样乘 **1024**。
- 上游监控已经输出 bytes 时直接使用，**不得再次乘 1024**。受控单位示例：`MemAvailable: 4096 kB` 对应 `4194304 bytes`，`MemTotal: 16384 kB` 对应 `16777216 bytes`；这些示例不是服务器实测。
- `MemAvailable` 是内核对无需交换即可供新应用使用内存的估计，考虑 MemFree、可回收 slab、LRU 及水位；它不是 `MemFree + Inactive`，也不保证立即可分配。缺测或不支持时，按原契约使用 `quality=MISSING` / `UNSUPPORTED`、`value=null`，不使用 `MemFree + Inactive` 或 `free + inactive` 兜底，不补零。
- `source`、`config_id` 应标识实际外部来源及采集配置，保留该来源的窗口和 `collected_at`。报告通用显示冻结来源，不把旧历史值或来源重标为 Linux。数据如自带语义说明则原文展示；来源未核实的历史数据不作为 Linux 服务器验收。

依据：[Linux proc meminfo 文档](https://docs.kernel.org/filesystems/proc.html#meminfo) 定义 `MemAvailable`；[Linux meminfo 实现](https://raw.githubusercontent.com/torvalds/linux/master/fs/proc/meminfo.c) 中 `show_val_kb` 使用 `PAGE_SHIFT - 10` 输出 kB，`MemAvailable` 来自 `si_mem_available`，即这里的 kB 为 1024 bytes。接入方须核对其实际上游单位，不因名称相近重复换算。

旧开发宿主机采样、Run 和报告作为历史记录原样保留，不作为 Linux 默认入口或服务器验收依据。当前只有输入契约和受控离线验证；真实 Linux 服务器端到端验证为 **NOT_RUN**。旧冻结 Run 保持原规则和来源，不因新规则重算；新 HOST v2 契约与历史记录分开。

两组 used/total、available/total分别属于已批准的配对指标；Xid窗口事件替代旧last值，不新增指标。比例0到1，字节/延迟/速率非负，ECC为整数delta。ECC值额外要求 `source_metric`、`semantics`（SINGLE_BIT/DOUBLE_BIT）和 `scope`（DRAM）；采集方必须证实来源等价，不能将通用 corrected/uncorrected 直接更名。重置窗口 quality=RESET，不比较为增长或恢复。

Xid value 是 `[{event_id,code,occurred_at}]`，event_id 应来自持久日志标识；相同事件跨投递去重，标识相同但内容冲突拒绝。事件时间必须在本窗口内。ECC的事件证据键由快照身份、GPU和指标组成。

bindings为 `{complete:boolean,engines:[{engine_id,engine_type,model_name}]}`；多个引擎可共用设备。引擎必须已有同环境推理快照。complete仅表示采集方声明覆盖所有使用者，不能把共享设备异常强行归因某个引擎。相关性使用相同绑定和重叠窗口，只输出疑似原因。模型、配置、身份或绑定变化会重新积累基线。

可选 `hardware_reverification` 为 `{event_ids:[...],performed_at,method,result}`，result必须PASSED，method必须为非空处置后验证说明；事件ID必须来自本资源既有硬件异常，performed_at必须晚于异常，且验证窗口不得早于处置。该字段是外部系统的处置验证证据，不等同服务端独立硬件检测；仍需用户在风险流程标记已处理，并由处理后的新巡检完成复验。零新增事件不能直接恢复硬件风险。

算法输出 `diagnostics`、`quality`、`coverage`、`issues`、`correlations` 和 `limitations`。8个历史点仅是最低计算门槛，sample_count会显示，不能视为已验证生产基线。温度/利用率等使用模型/config与QPS、输入/输出token、running、cache匹配；检查产出下降时生成吞吐是目标变量，不能作为匹配条件。MAD双向偏离与最小效应过滤后进行短窗口确认，CUSUM捕捉持续小幅变化。基线不足为NOT_READY，缺少引擎输入为NOT_READY；都不会伪造诊断通过。显存预分配本身不是异常。

文件系统预估采用Theil–Sen短长趋势一致，预测到10%保留空间，不是精确写满时间；主机内存只报告持续下降。没有频率/功耗不诊断热降频，没有IOPS/IO大小不确诊存储设备退化。

每个GPU与HOST分别产出一个CheckResult，HOST内部有逐组件诊断；同一个HOST的风险聚合。恢复要求原异常组件及诊断均有有效覆盖，组件消失、重命名、替换或缺测保持待复验。DBE新增立即严重，即使别的组件缺测也保留FAIL。历史Run冻结评估，不因后续导入或策略变化重算。

批量导入：POST `/api/v1/hardware-health/snapshots/batch`，`{samples:[完整请求,...]}`，最多500条，按设备时间升序，整个批次事务原子提交，重复样本只返回原快照、不重评估。定时API `/api/internal/v1/batch/inspection-runs` 可传 source_type=HARDWARE_SNAPSHOT（GPU/HOST）或EXTERNAL_SNAPSHOTS（混合）及resource_types；默认INFERENCE_SNAPSHOT仍兼容旧LLM调度。

Xid分类依据 [NVIDIA Xid Catalog](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html) 与 [GPU Node Triage](https://docs.nvidia.com/deploy/gpu-debug-guidelines/gpu-node-triage.html)。48/63/64/92/94/95为内存相关，79为设备掉总线，119/120为GSP通信/执行错误；未知代码保留原值并标记UNCLASSIFIED。严重级别是本产品保守运营策略，不等于根因确诊或厂商RMA结论。单次SBE为偶发告警、复发/加速另有代码；硬件事件均需处置复验，模型不自动执行设备操作。


## HOST v2 已批准静态规则与当前边界

新HOST快照评估冻结 `gpu-host-health/2.0.0`；GPU及旧Run的1.0.0不重算。新请求可加 `host_semantics={"os":"LINUX","memory_available":"MemAvailable","memory_total":"MemTotal","unit":"bytes"}`。这是外部接入方语义声明，不是服务端已经验证Linux来源的证明；无声明仍可接收旧payload，CPU/内存静态项为NOT_READY，不根据source名字或开发宿主OS推断Linux。

CPU >=80%警告、>=90%严重；MemAvailable/MemTotal <=20%警告、<=10%严重；各连续3有效点，60秒相邻，首末120秒。CPU严重退出<85%、警告解除<75%；内存严重退出>15%、警告解除>25%；各连续5有效点，首末240秒。严重可降警告。缺测、同点、断点、来源/配置变化打断确认；已确认事件保持，缺测不恢复。静态项独立于LLM绑定、漂移样本和磁盘覆盖。事件与阈值冻结于现有evaluation；风险复验必须满足同规则、同事件的五点恢复证据及原处置后时间/组件要求，删除规则或事件不构成恢复。

外部采集合同为60秒采集一次、每次入库评估一次；严格按原collected_at验证60秒连续性。仓库没有新增采集器或60秒调度服务，配置值不是实际节拍运行证明。显式Linux输入入库新鲜度和v2 Run读取均为180秒（包含180秒）；旧冻结1.0.0保留300秒读取边界。内存容量配对要求有效、同采集时刻，字节值不再换算。

HOST/文件系统下降窗口最多1800秒31点、最少600秒11点；保持Theil–Sen双负斜率及[0.25,4]比例，下降量严格>max(1MiB,首值3%)，文件系统保留水位10%。

CPU新漂移使用14天30可比点、最低效应>=max(0.20,基线绝对值15%)、稳健倍数3、CUSUM k0.5/h5。单点路径逐点满足最低效应且严格越过3倍尺度；CUSUM逐点满足最低效应及同方向累计得分>=5，不再套单点波动门槛；每路径各连续3个有效可比同方向点。近期序列从原调用6点提升至原函数已有的有界12点，使慢漂移有机会在第10至12点累计满足连续确认；没有无限累计。每事件冻结实际命中分支的threshold/base/scale；同时命中保留所有分支义务，恢复要求偏离<=各分支threshold×70%连续5有效可比点，不使用尖峰实际偏离或新基线。必要的原绑定和CPU/IO负载可比性保留。

固定30天当前仅落实无副作用候选界限：`apps.hardware_health.host_policy.retention_candidates(rows, as_of=...)` 返回window_end严格早于as_of−30天的ID。它不查询/删除数据库，不启动清理或调度，调用方仍须保护引用及冻结证据；真实保留清理为PARTIAL/NOT_RUN。本批没有删除任何真实Run、快照或历史证据。所有验证为受控纯函数/投影/前端测试；真实Linux及HTTP/DOM端到端为NOT_RUN。
