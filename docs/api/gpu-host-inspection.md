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

两组 used/total、available/total分别属于已批准的配对指标；Xid窗口事件替代旧last值，不新增指标。比例0到1，字节/延迟/速率非负，ECC为整数delta。ECC值额外要求 `source_metric`、`semantics`（SINGLE_BIT/DOUBLE_BIT）和 `scope`（DRAM）；采集方必须证实来源等价，不能将通用 corrected/uncorrected 直接更名。重置窗口 quality=RESET，不比较为增长或恢复。

Xid value 是 `[{event_id,code,occurred_at}]`，event_id 应来自持久日志标识；相同事件跨投递去重，标识相同但内容冲突拒绝。事件时间必须在本窗口内。ECC的事件证据键由快照身份、GPU和指标组成。

bindings为 `{complete:boolean,engines:[{engine_id,engine_type,model_name}]}`；多个引擎可共用设备。引擎必须已有同环境推理快照。complete仅表示采集方声明覆盖所有使用者，不能把共享设备异常强行归因某个引擎。相关性使用相同绑定和重叠窗口，只输出疑似原因。模型、配置、身份或绑定变化会重新积累基线。

可选 `hardware_reverification` 为 `{event_ids:[...],performed_at,method,result}`，result必须PASSED，method必须为非空处置后验证说明；事件ID必须来自本资源既有硬件异常，performed_at必须晚于异常，且验证窗口不得早于处置。该字段是外部系统的处置验证证据，不等同服务端独立硬件检测；仍需用户在风险流程标记已处理，并由处理后的新巡检完成复验。零新增事件不能直接恢复硬件风险。

算法输出 `diagnostics`、`quality`、`coverage`、`issues`、`correlations` 和 `limitations`。8个历史点仅是最低计算门槛，sample_count会显示，不能视为已验证生产基线。温度/利用率等使用模型/config与QPS、输入/输出token、running、cache匹配；检查产出下降时生成吞吐是目标变量，不能作为匹配条件。MAD双向偏离与最小效应过滤后进行短窗口确认，CUSUM捕捉持续小幅变化。基线不足为NOT_READY，缺少引擎输入为NOT_READY；都不会伪造诊断通过。显存预分配本身不是异常。

文件系统预估采用Theil–Sen短长趋势一致，预测到10%保留空间，不是精确写满时间；主机内存只报告持续下降。没有频率/功耗不诊断热降频，没有IOPS/IO大小不确诊存储设备退化。

每个GPU与HOST分别产出一个CheckResult，HOST内部有逐组件诊断；同一个HOST的风险聚合。恢复要求原异常组件及诊断均有有效覆盖，组件消失、重命名、替换或缺测保持待复验。DBE新增立即严重，即使别的组件缺测也保留FAIL。历史Run冻结评估，不因后续导入或策略变化重算。

批量导入：POST `/api/v1/hardware-health/snapshots/batch`，`{samples:[完整请求,...]}`，最多500条，按设备时间升序，整个批次事务原子提交，重复样本只返回原快照、不重评估。定时API `/api/internal/v1/batch/inspection-runs` 可传 source_type=HARDWARE_SNAPSHOT（GPU/HOST）或EXTERNAL_SNAPSHOTS（混合）及resource_types；默认INFERENCE_SNAPSHOT仍兼容旧LLM调度。

Xid分类依据 [NVIDIA Xid Catalog](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html) 与 [GPU Node Triage](https://docs.nvidia.com/deploy/gpu-debug-guidelines/gpu-node-triage.html)。48/63/64/92/94/95为内存相关，79为设备掉总线，119/120为GSP通信/执行错误；未知代码保留原值并标记UNCLASSIFIED。严重级别是本产品保守运营策略，不等于根因确诊或厂商RMA结论。单次SBE为偶发告警、复发/加速另有代码；硬件事件均需处置复验，模型不自动执行设备操作。
