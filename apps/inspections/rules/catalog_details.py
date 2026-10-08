"""Read-only rule explanations, bound to the accepted schemas and live policies.

This catalog describes evaluation; it never collects data or evaluates a snapshot.
"""
from copy import deepcopy

from apps.hardware_health.evaluator import LOAD_FIELDS, MIN_EFFECT
from apps.hardware_health.schemas import FIELDS, QUALITIES
from apps.inference_performance.schemas import METRIC_FIELDS
from apps.inference_performance.services.baseline import SUPPORT_METRICS
from apps.inference_performance.services.fixed import PRIMARY_METRICS
from apps.inference_performance.services.policy import deep_merge, load_policy_config, validate_policy


def _section(title, *items):
    return {'title': title, 'items': list(items)}


def _llm_metrics():
    rows = []
    groups = {'ttft': '首 Token 延迟（TTFT）', 'tpot': '每个输出 Token 延迟（TPOT）', 'e2e': '端到端延迟'}
    percentiles = {'avg_ms': '平均值', 'p90_ms': 'P90', 'p95_ms': 'P95', 'p99_ms': 'P99'}
    other = {
        'ttft.e2e_ratio': ('首 Token 延迟占端到端延迟比例', '比例', '0–1', '辅助观察响应阶段占比'),
        'traffic.qps': ('每秒请求数', '请求/秒', '≥ 0', '动态基线的相似负载筛选及空闲识别'),
        'traffic.qpm': ('每分钟请求数', '请求/分钟', '≥ 0', '流量背景观察'),
        'throughput.generation_tps': ('输出 Token 吞吐', 'Token/秒', '≥ 0', '辅助观察输出吞吐及空闲识别'),
        'throughput.prompt_tps': ('输入 Token 吞吐', 'Token/秒', '≥ 0', '辅助观察输入负载及空闲识别'),
        'cache.kv_cache_hit_rate': ('KV Cache 命中率', '比例', '0–1', '辅助观察缓存与负载'),
        'requests.running': ('正在执行的请求数', '请求', '≥ 0', '辅助观察并发及空闲识别'),
        'requests.waiting': ('正在排队的请求数', '请求', '≥ 0', '主要指标：固定阈值、动态基线、趋势及空闲识别'),
    }
    for group, fields in METRIC_FIELDS.items():
        for field in fields:
            key = f'{group}.{field}'
            if group in groups and field in percentiles:
                name = f'{groups[group]} {percentiles[field]}'
                unit, value_range = 'ms/token' if group == 'tpot' else 'ms', '≥ 0；P90 ≤ P95 ≤ P99'
                purpose = '主要指标：固定阈值、动态基线与趋势判定' if key in PRIMARY_METRICS else '分布背景观察，不直接提升 overall'
            else:
                name, unit, value_range, purpose = other[key]
                if key in SUPPORT_METRICS:
                    purpose += '；动态基线仅 OBSERVED，不直接提升 overall'
            rows.append({'field': key, 'input_path': f'sample.{key}', 'name': name,
                         'unit': unit, 'range': value_range, 'purpose': purpose})
    return rows


def _policy_profiles(config):
    profiles = []

    def add(label, level, policy, overrides, engine=None, model=None):
        validate_policy(policy)
        profiles.append({'label': label, 'level': level, 'engine_type': engine, 'model_name': model,
                         'overrides': deepcopy(overrides), 'policy': policy,
                         'fixed_thresholds': [{'field': key, 'unit': '请求' if key == 'requests.waiting' else 'ms/token' if key.startswith('tpot.') else 'ms',
                                               **policy['fixed'][key]} for key in PRIMARY_METRICS]})

    add('DEFAULT · 默认策略', 'DEFAULT', deepcopy(config['default']), {})
    for engine, override in sorted(config.get('engines', {}).items()):
        if isinstance(override, dict):
            add(f'ENGINE · {engine}', 'ENGINE', deep_merge(config['default'], override), override, engine)
    for engine, models in sorted(config.get('models', {}).items()):
        engine_policy = deep_merge(config['default'], config.get('engines', {}).get(engine, {}))
        for model, override in sorted(models.items()):
            if isinstance(override, dict) and override:
                add(f'ENGINE_MODEL · {engine} / {model}', 'ENGINE_MODEL', deep_merge(engine_policy, override), override, engine, model)
    return profiles


def _llm_details():
    config = load_policy_config()
    profiles = _policy_profiles(config)
    policy = profiles[0]['policy']
    dynamic, trend = policy['dynamic'], policy['trend']
    quality = policy.get('quality') or {}
    rules = [
        _section('策略选择与固定阈值',
                 '优先选择 ENGINE_MODEL → ENGINE → DEFAULT；逐层深度合并，未覆盖的字段继承父级。下方表格展示当前配置的完整有效策略和模型覆盖。默认阈值属于平台当前策略，不是所有模型通用的 SLO。历史巡检以冻结的 resolved_policy 为准。',
                 '仅 7 个主要指标参与固定阈值：当前值 ≥ critical 为 CRITICAL；否则 ≥ warning 为 WARNING；低于 warning 为 NORMAL。固定和动态取最高严重度作为 overall，趋势独立展示。',
                 f"固定阈值默认连续 {policy['persistence']['consecutive_hits']} 个异常窗口才确认。严重级需连续 critical；若仅连续 warning 则最多 WARNING。窗口时长须一致、不得重叠，间隔不得超过 {quality.get('max_gap_seconds', 300)} 秒；否则中断连续计数。首次越界可能仍为内部 NORMAL，但 pending_confirmation=true；无其他已确认 WARNING / CRITICAL 时，巡检结论为 UNKNOWN。已确认异常优先于待确认状态，仍映射 FAIL。"),
        _section('14 天动态基线与正常边界',
                 '同环境、engine_id、engine_type、model_name 的当前窗口之前 14 天历史；只保留相同窗口时长并排除空闲点。最多下采样 4096 点；至少 100 点且覆盖 3 个不同日期才 READY，否则 NOT_READY。',
                 '当当前 QPS > 0，优先保留历史 QPS 为当前的 0.5–1.5 倍且满足 100 点/3 日期的样本。相似负载不足则 FULL_HISTORY_FALLBACK；此时仅提供基线观察，不提升 overall。',
                 f"中心 M=median，MAD=median(|x−M|)，σ=1.4826×MAD。当前默认 warning=max(M×(1+{dynamic['warning_change_ratio']}), M+{dynamic['warning_z']}×σ)，critical=max(M×(1+{dynamic['critical_change_ratio']}), M+{dynamic['critical_z']}×σ)。当前值 ≥ 边界即越界；此动态判定不应用固定阈值的连续确认。仅相似 QPS、非零 M 的主要指标可提升 overall。",
                 'M=0 时 NOT_EVALUABLE；辅助指标仅 OBSERVED。NOT_READY / NOT_EVALUABLE 表示这一诊断无法判定，不能据此确认健康；即使固定阈值通过、overall 为 NORMAL，也不代表动态和趋势覆盖已就绪。'),
        _section('趋势（独立观察）',
                 f"默认最近 {trend['window_minutes']} 分钟分为前后两半，各至少 3 点。比较主要指标两半中位数，变化率=(后半−前半)/前半；默认 ≥ {trend['degrading_change_ratio']} 为 DEGRADING，≥ {trend['watch_change_ratio']} 为 WATCH，否则 STABLE。前半为零则 NOT_EVALUABLE；点数不足则 NOT_READY。趋势不抬高 overall。"),
        _section('质量、时效与最终巡检结论',
                 f"所有指标必须为有限非负数，比例为 0–1，P90 ≤ P95 ≤ P99。QPS、running、waiting、generation_tps、prompt_tps 全为 0 视为 IDLE；空闲无法确认性能，巡检为 UNKNOWN。默认快照超过 {quality.get('max_age_seconds', 300)} 秒为 STALE；缺失、身份/版本不符或冻结数据无效也为 UNKNOWN。",
                 '非空闲的有效快照 WARNING / CRITICAL 映射 FAIL（P2 / P1），优先于其他指标的 pending_confirmation；READY 且无待确认、overall NORMAL 映射 PASS。规则详情描述当前配置，具体资源是否正常还需查看其当前值、质量、诊断就绪状态和冻结策略。'),
    ]
    return {'supported_metrics': _llm_metrics(), 'judgment_rules': rules, 'policy_profiles': profiles,
            'input_contract': '外部采集系统计算并推送聚合快照（INFERENCE_SNAPSHOT）；平台接收、校验并评估，不直接采集引擎指标。20 个字段必须完整提供，不以 0 代替缺失数据。'}


_HARDWARE_METADATA = {
    'gpu': {
        'utilization_ratio': ('GPU 利用率', '比例', '0–1', '同负载双向漂移；高利用率输出下降、排队但低利用率关联'),
        'memory_used_bytes': ('GPU 已用显存', 'bytes', '≥ 0，且 ≤ memory_total_bytes', '容量证据；预分配不直接视为异常'),
        'memory_total_bytes': ('GPU 总显存', 'bytes', '> 0（容量对有效时）', '容量与显存使用背景'),
        'temperature_celsius': ('GPU 温度', '°C', '≥ 0', '同负载温度双向漂移；无通用固定高温阈值'),
        'ecc_sbe_delta': ('DRAM 单比特 ECC 增量', '事件数/窗口', '非负整数', '偶发、复发、加速增长事件；需要处置复验'),
        'ecc_dbe_delta': ('DRAM 双比特 ECC 增量', '事件数/窗口', '非负整数', '新增不可纠正错误 P1；需要处置复验'),
        'xid_events': ('GPU Xid 事件', '事件列表', '≤ 1000 条；code 为 1–999 整数', '按 Xid 类别判定 P1/P2；稳定 event_id 去重与复验'),
    },
    'host': {
        'cpu_busy_ratio': ('主机 CPU 忙碌率', '比例', '0–1', '同负载双向漂移；无通用固定 CPU 阈值'),
        'memory_available_bytes': ('主机可用内存', 'bytes', '≥ 0，且 ≤ memory_total_bytes', '持续下降趋势；当前容量不直接判异常'),
        'memory_total_bytes': ('主机总内存', 'bytes', '> 0（容量对有效时）', '容量背景与容量对校验'),
    },
    'filesystem': {
        'available_bytes': ('文件系统可用空间', 'bytes', '≥ 0，且 ≤ size_bytes', '持续下降趋势与到达 10% 保留空间的时间估计'),
        'size_bytes': ('文件系统总空间', 'bytes', '> 0（容量对有效时）', '计算 10% 保留空间；本身不设固定低空间告警'),
    },
    'disk': {
        'read_bytes_per_second': ('磁盘读取吞吐', 'bytes/秒', '≥ 0', '同负载双向漂移；结合 I/O 背景观察'),
        'write_bytes_per_second': ('磁盘写入吞吐', 'bytes/秒', '≥ 0', '同负载双向漂移；结合 I/O 背景观察'),
        'read_latency_avg_ms': ('磁盘平均读延迟', 'ms', '≥ 0', '同负载双向漂移；上升生成疑似 I/O 延迟退化关联'),
        'write_latency_avg_ms': ('磁盘平均写延迟', 'ms', '≥ 0', '同负载双向漂移；上升生成疑似 I/O 延迟退化关联'),
        'io_busy_ratio': ('磁盘 I/O 忙碌率', '比例', '0–1', '同负载双向漂移'),
    },
}


def _hardware_details(kind):
    families = ('gpu',) if kind == 'gpu' else ('host', 'filesystem', 'disk')
    metrics = []
    for family in families:
        # Metadata has a stable presentation order; the schema owns membership.
        for field, (name, unit, value_range, purpose) in _HARDWARE_METADATA[family].items():
            if field not in FIELDS[family]:
                continue
            component = family if family in {'gpu', 'host'} else f'{family}:<稳定标识>'
            metrics.append({'field': f'{family}.{field}', 'input_path': f'metrics.{component}.values.{field}.value',
                            'name': name, 'unit': unit, 'range': value_range, 'purpose': purpose})
    effects = '；'.join(f'{field}={effect:g}' for field, effect in MIN_EFFECT.items()
                       if field in {key for family in families for key in FIELDS[family]})
    load_fields = '、'.join(f'{group}.{field}' for group, field in LOAD_FIELDS)
    output_comparison = '输出退化比较排除 generation_tps 本身。' if kind == 'gpu' else ''
    effect_details = ('GPU 输出吞吐 floor=1 Token/秒。相对最小效应 r 为温度 0.05，其他指标 0.15。'
                      if kind == 'gpu' else '读/写吞吐 floor=1048576 bytes/秒；这些主机指标的相对最小效应 r=0.15。')
    drift_limits = ('GPU 温度、利用率均按条件基线判断；当前实现没有通用固定高温告警阈值。显存预分配或单点容量不作为漂移异常。'
                    if kind == 'gpu' else 'CPU、I/O 忙碌率及磁盘吞吐/延迟均按条件基线判断；当前实现没有通用固定高 CPU 告警阈值。单点容量不作为漂移异常。')
    rules = [
        _section('数据质量、身份与条件基线',
                 '使用过去 14 天相同 identity、config_id、bindings 及组件 identity 的历史。缺失/替换过的组件不会视为已恢复。外部引擎绑定必须完整，并带齐已冻结的推理快照，才可比较同负载。',
                 f'相似负载维度：{load_fields}。缓存命中率绝对差 ≤ 0.15；其他维度与当前差 ≤ max(1, |当前值|×0.3)。{output_comparison}',
                 '条件基线至少 8 点，8 点只代表最低计算门槛。最近最多 6 点留出作为观察序列，不立刻吸收进基线；历史/推理绑定不足则 NOT_READY。窗口间断超过 max(300秒, 前一窗口时长×2) 会截断连续序列。'),
        _section('双向条件漂移与确认',
                 f'最小绝对效应 floor：{effects}。{effect_details}',
                 'M=median，MAD=median(|x−M|)，scale=max(1.4826×MAD, floor/3, |M|×r/3, 1e−9)，minimum=max(floor, |M|×r)。当 |x−M| > max(3×scale, minimum) 判定向上/向下越界。最近 3 点至少 2 点同方向且最后一点仍越界才 WARNING；最后一点越界但未确认为 PENDING。',
                 'CUSUM 同时累积双向标准化偏差 z=(x−M)/scale：positive=max(0, positive+z−0.5)，negative=min(0, negative+z+0.5)。序列至少 3 点，|最后值−M| ≥ minimum 且 max(positive, −negative) ≥ 5，可确认慢漂移 WARNING。',
                 drift_limits),
    ]
    if kind == 'gpu':
        rules += [
            _section('GPU 与推理表现的关联',
                     '输出吞吐确认向下漂移且 GPU 利用率 ≥ 0.7：SUSPECT_GPU_BUSY_OUTPUT_DOWN，产生 P2 问题。waiting > 0 且利用率 < 0.2，最近 3 点至少 2 点满足条件：SUSPECT_QUEUE_WITH_IDLE_GPU，产生 P2；仅 1 点为 PENDING。',
                     '同负载温度向上漂移可给出疑似温度关联；硬件事件与推理 WARNING/CRITICAL 并存可给出疑似共同退化。疑似相关性不等同根因，无频率/功耗数据不能诊断热降频。'),
            _section('ECC / Xid 严重度与处置复验',
                     'DRAM DOUBLE_BIT 增量 > 0 为 ECC_DBE_NEW（P1）。DRAM SINGLE_BIT 增量 > 0 默认 ECC_SBE_OCCASIONAL（P2）；最近最多 3 个有效窗口出现正增量为 RECURRENT；当前每秒增量率 > 前一率 > 再前一率 > 0 为 ACCELERATING，仍为 P2。',
                     'Xid 48/63/64/92/94/95 为 MEMORY_ERROR，79 为 DEVICE_LOST，119/120 为 GSP_ERROR，13/31/43 为 APPLICATION_OR_DRIVER，其他 UNCLASSIFIED。48/79/94/95/119/120 为 P1，其余 P2。',
                     '事件状态跨 14 天基线和配置变化保留。后续没有新事件不等于恢复；必须外部处置后推送 hardware_reverification，列出待清除的事件 ID、当前窗口内 performed_at、method 与 PASSED。有效复验才清除所列事件；诊断提示 HARDWARE_REVERIFICATION_REQUIRED。'),
        ]
    else:
        rules += [
            _section('内存/文件系统持续下降与保留空间',
                     '组件连续历史至少 6 点；取最多 12 点，跨度至少 300 秒且可用容量全部有效。全段与最近 4 点使用成对斜率中位数。长短斜率均 < 0、短/长斜率比在 0.25–4 之间，且首尾下降量 > max(1048576 bytes, 首值×0.03)，才产生 P2 的 MEMORY_SUSTAINED_DECLINE / SPACE_DECLINE。',
                     '确认文件系统下降后 reserve=总容量×0.1，seconds_to_reserve=max(0, (当前可用−reserve)/−长斜率)。10% 是保留空间时间估计基准；当前实现不单凭空间低于 10% 触发告警。',
                     '读/写延迟确认向上漂移时，生成疑似 I/O 延迟退化关联；没有 IOPS/IO 大小不能确诊存储退化。'),
        ]
    rules += [
        _section('overall 与诊断覆盖边界',
                 f"逐指标 quality 支持 {' / '.join(sorted(QUALITIES))}。非 VALID 必须 value=null，不用 0 替代；缺失或不支持不是健康。主机缺 filesystem/disk 组件会产生覆盖 MISSING。",
                 'overall 顺序：有 P1 问题 → CRITICAL；其他已确认问题 → WARNING；无问题但覆盖不完整或有 PENDING → UNKNOWN；否则 NORMAL。NOT_READY 诊断本身不会自动将 overall 改为 UNKNOWN，所以基础检查 PASS / NORMAL 时仍可能有高级诊断未就绪，必须逐项查看 coverage 与 diagnostics。',
                 '硬件快照时效当前实现固定 300 秒；超过该时效、缺失或冻结身份/版本/时效无效 → UNKNOWN。有效 CRITICAL / WARNING 映射 FAIL（P1 / P2），NORMAL 映射 PASS，其余 UNKNOWN。共享设备或归属不完整时仅报告设备级现象。'),
    ]
    return {'supported_metrics': metrics, 'judgment_rules': rules, 'policy_profiles': [],
            'input_contract': '外部采集系统推送 HARDWARE_SNAPSHOT；平台接收、校验和评估，不直接采集硬件指标。GPU 必须包含 gpu；HOST 必须包含 host，可同时推送 filesystem:<稳定标识>、disk:<稳定标识>。每个组件必须提供其全部指标和逐指标 value / quality / collected_at；ECC 另需 source_metric / semantics / scope=DRAM。'}


def get_catalog_details(rule_code):
    if rule_code == 'llm.performance_profile':
        return _llm_details()
    if rule_code in {'hardware.gpu_health', 'hardware.host_health'}:
        return _hardware_details('gpu' if rule_code == 'hardware.gpu_health' else 'host')
    return {'supported_metrics': [], 'judgment_rules': [], 'policy_profiles': [], 'input_contract': ''}
