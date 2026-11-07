"""Presentation facts from frozen checks; no evaluation or model-generated values."""


PRIORITY = {"FAIL": 0, "ERROR": 1, "UNKNOWN": 2, "PASS": 3, "NOT_APPLICABLE": 4}
FIELDS = (
    "code", "metric", "key", "status", "current", "value", "unit", "threshold", "boundary",
    "baseline_median", "change_ratio", "warning", "critical", "quality_reason", "severity",
    "xid_code", "event_id", "occurred_at", "window_start", "window_end", "sample_count",
    "short_slope_bytes_per_second", "long_slope_bytes_per_second", "reserve_bytes", "seconds_to_reserve",
    "absolute_change", "first_half_median", "second_half_median", "contributes_to_status",
    "rule_id", "rule_version", "rule", "branches", "robust_scale", "direct_confirmation_points", "cusum_confirmation_points", "series_points", "recovery_points", "confirmation_points", "confirmation_required", "trigger_window_seconds", "recovery_required", "recovery_window_seconds", "reason", "action",
)


def mapping(value):
    return value if isinstance(value, dict) else {}


def select(value):
    return {key: value[key] for key in FIELDS if key in value and value[key] is not None}


def _layer(code):
    if "FIXED" in code or code in {"HOST_CPU_STATIC_LIMIT", "HOST_MEMORY_STATIC_LIMIT"}:
        return "FIXED"
    if "DYNAMIC" in code:
        return "DYNAMIC"
    if "TREND" in code:
        return "TREND"
    return "HARDWARE"


def _frozen_host_snapshot(row, frozen_input):
    """Match observations to this check's frozen asset and snapshot only."""
    if (row.get("check") or row.get("inspection_item_code")) != "hardware.host_health":
        return {}
    evidence = mapping(row.get("evidence"))
    snapshot_id = evidence.get("snapshot_id") or mapping(mapping(evidence.get("evaluation")).get("input")).get("snapshot_id")
    asset_id = str(row.get("asset_id") or "")
    snapshot = mapping(mapping(mapping(frozen_input).get("snapshots")).get(asset_id))
    if not snapshot_id or str(snapshot.get("asset_id") or "") != asset_id or snapshot.get("snapshot_id") != snapshot_id:
        return {}
    return snapshot if mapping(snapshot.get("payload")).get("kind") == "HOST" else {}


def _host_observations(snapshot, frozen_input):
    payload = mapping(snapshot.get("payload"))
    values = mapping(mapping(mapping(payload.get("metrics")).get("host")).get("values"))
    observations = []
    for metric, unit in (("cpu_busy_ratio", "ratio"), ("memory_available_bytes", "bytes"), ("memory_total_bytes", "bytes")):
        point = mapping(values.get(metric))
        if point.get("value") is None:
            continue
        item = {
            "metric": "host/" + metric, "current": point["value"], "unit": unit,
            "layer": "OBSERVATION", "value_semantics": "OBSERVATION", "contributes_to_status": False,
            "quality": point.get("quality"), "collected_at": point.get("collected_at"),
            "source": payload.get("source"), "config_id": payload.get("config_id"), "sample_id": payload.get("sample_id"),
            "asset_id": snapshot.get("asset_id"), "snapshot_id": snapshot.get("snapshot_id"),
            "window_start": snapshot.get("window_start"), "window_end": snapshot.get("window_end"),
            "frozen_at": snapshot.get("frozen_at"), "input_as_of": mapping(frozen_input).get("as_of"),
        }
        if "measurement_semantics" in point:
            item["measurement_semantics"] = point["measurement_semantics"]
        observations.append(item)
    return observations


def _host_diagnostic_presentation(row, evaluation, snapshot):
    """Explain recorded HOST diagnostics without evaluating health or filling history."""
    if (row.get("check") or row.get("inspection_item_code")) != "hardware.host_health" or not evaluation.get("diagnostics"):
        return None
    evidence = mapping(row.get("evidence"))
    diagnostics = mapping(evaluation.get("diagnostics"))
    payload = mapping(snapshot.get("payload"))
    bindings = mapping(payload.get("bindings"))
    binding_context = {"recorded": bool(bindings)}
    if bindings:
        if "complete" in bindings:
            binding_context["complete"] = bindings["complete"]
        if isinstance(bindings.get("engines"), list):
            binding_context["engine_count"] = len(bindings["engines"])
        binding_context["note"] = ("同Run冻结绑定不完整，缺少可比LLM负载上下文；仅保留设备观测。"
                                   if bindings.get("complete") is False else "同Run冻结绑定已记录；负载是否可比仍以原诊断为准。")
    else:
        binding_context["note"] = "未记录同Run匹配的冻结绑定上下文；不推断绑定是否完整。"
    rules = [
        ("host/cpu_busy_ratio", "CPU条件漂移",
         "14天内同设备/配置、可比LLM负载至少8个历史点；近期样本留出基线。以median/MAD及最小效应判断，短确认至少2/3或双侧CUSUM；无固定CPU占用健康阈值。",
         "核对同Run服务绑定、QPS、输入/输出吞吐、运行请求及缓存负载，积累满足原要求的可比历史后复查。"),
        ("host/decline", "主机内存持续下降",
         "至少6个按时间顺序的点，跨度至少300秒；Theil–Sen长短斜率一致为负，仅报告持续下降，不按容量余量设置健康阈值。",
         "核对进程内存及同期分配、回收变化，按原要求保留时序；持续下降不等于已确认内存泄漏根因。"),
    ]
    new_host = mapping(evaluation.get('plugin')).get('version') == '2.0.0'
    if new_host:
        rules = [
            ('host/cpu_static', 'CPU固定阈值', 'Linux显式语义；>=80%警告、>=90%严重，各连续3个60秒有效点（120秒）；严重退出<85%、警告解除<75%，各连续5点（240秒）。', '核对CPU负载、进程及采集时间；缺测不解除已确认异常。'),
            ('host/memory_static', 'Linux可用内存固定阈值', 'MemAvailable/MemTotal <=20%警告、<=10%严重，各连续3点；严重退出>15%、警告解除>25%，各连续5个60秒有效点。', '核对MemAvailable、回收和交换压力，保留同事件恢复证据。'),
            ('host/cpu_busy_ratio', 'CPU条件漂移', '14天30可比点；单点最低效应>=max(0.20,基线15%)且严格越过3倍尺度，或CUSUM同方向得分>=5且逐点达到最低效应；各连续3点。最多12近期点，分支门槛冻结后70%连续5点恢复。', '核对同来源、配置及可比LLM负载；保留冻结分支基线、尺度和门槛以复查恢复。'),
            ('host/decline', '主机内存持续下降', '60秒连续点，至少600秒11点，最多1800秒31点；双Theil–Sen负斜率比例[0.25,4]；下降严格超过max(1MiB,首值3%)。', '核对进程内存及分配回收；下降现象不等于泄漏根因。'),
        ]
    known = {rule[0] for rule in rules}
    for key, diagnostic in diagnostics.items():
        if key not in known and mapping(diagnostic).get("status") in {"WARNING", "CRITICAL"}:
            rules.append((key, key, "仅呈现该项已冻结诊断，不增加判断规则。", "核对该维度的原始证据及关联风险；其他维度缺项不能证明该异常已恢复。"))
    items = []
    for metric, name, requirements, advice in rules:
        diagnostic = mapping(diagnostics.get(metric))
        reason = diagnostic.get("reason")
        item = {
            "metric": metric, "name": name, "recorded": bool(diagnostic), "status": diagnostic.get("status"),
            "statistics": {key: value for key, value in diagnostic.items() if key not in {"status", "reason"}},
            "reason": reason,
            "reason_note": ("可比历史不足；实际样本数见原记录。" if reason == "INSUFFICIENT_COMPARABLE_HISTORY"
                            else str(reason) if reason else "原诊断未记录独立原因；不补造原因或历史统计。"),
            "requirements": requirements, "advice": advice,
        }
        if metric == "host/cpu_busy_ratio":
            item["binding_context"] = binding_context
        items.append(item)
    impacts = {"host": "影响CPU及内存原始点的采集覆盖；VALID仅表示采集有效。",
               "filesystem": "影响文件系统空间及空间下降诊断，不能据此确认存储健康。",
               "disk": "影响磁盘吞吐、忙碌度及延迟诊断，不能据此确认I/O健康。"}
    return {
        "rule_reference": "gpu-host-health v2.0.0：本Run已冻结静态及分支漂移规则" if new_host else "已批准gpu-host-health v1.0.0规则说明（代码展示说明，非本Run新增冻结参数）",
        "recorded_plugin_version": mapping(evaluation.get("plugin")).get("version"),
        "evaluation_status": evaluation.get("status"),
        "window_start": snapshot.get("window_start") or evidence.get("window_start"),
        "window_end": snapshot.get("window_end") or evidence.get("window_end"),
        "execution_note": "巡检执行状态与HOST综合结论分开；执行完成不代表各诊断已就绪或整体健康。",
        "observation_note": "原始值、静态项、漂移项与采集质量分别呈现；静态事件按冻结规则确认，VALID不等于健康。" if new_host else "CPU及内存容量仅为观测；逐点VALID与容量初始化NORMAL均不生成健康PASS。",
        "items": items,
        "coverage": [{"component": key, "status": value, "impact": impacts.get(key.split(":")[0], "仅反映该组件的采集及判定覆盖。")}
                     for key, value in mapping(evaluation.get("coverage")).items()],
    }


def project_check(row, *, frozen_input=None):
    evidence = mapping(row.get("evidence"))
    evaluation = mapping(evidence.get("evaluation"))
    quality = mapping(evaluation.get("quality"))
    quality_state = quality.get("state") or evidence.get("status")
    inactive = row.get("status") in {"UNKNOWN", "ERROR", "NOT_APPLICABLE"} or quality_state in {"IDLE", "STALE", "INCOMPLETE", "NOT_READY"}
    reasons = evaluation.get("reasons") or evidence.get("reasons") or []
    measurements = []
    diagnostics = mapping(evaluation.get("diagnostics"))
    # Inactive evidence may contain old evaluated layers. Do not promote them to current abnormalities.
    confirmed_host = mapping(evaluation.get('plugin')).get('version') == '2.0.0' and row.get('status') == 'FAIL'
    # FAIL was validated by the handler; allow only its matching GPU snapshot,
    # never stale/invalid UNKNOWN layers or unrelated profile evaluations.
    confirmed_gpu = (
        (row.get('check') or row.get('inspection_item_code')) == 'hardware.gpu_health'
        and row.get('status') == 'FAIL' and evaluation.get('status') in {'WARNING', 'CRITICAL'}
        and mapping(evaluation.get('plugin')) == {'id': 'gpu-host-health', 'version': '1.0.0'}
        and quality_state == 'INCOMPLETE' and bool(evidence.get('snapshot_id'))
        and evidence.get('snapshot_id') == mapping(evaluation.get('input')).get('snapshot_id')
    )
    if not inactive or confirmed_host or confirmed_gpu:
        for reason in reasons if isinstance(reasons, list) else []:
            if not isinstance(reason, dict):
                continue
            item = select(reason)
            item["layer"] = _layer(str(reason.get("code") or ""))
            key = reason.get("key") or reason.get("metric")
            if key and str(key).endswith("/decline"):
                current_key = "host/memory_available_bytes" if key == "host/decline" else str(key).rsplit("/", 1)[0] + "/available_bytes"
                current = mapping(diagnostics.get(current_key)).get("current")
                if current is not None:
                    item["current"] = current
                    item["current_metric"] = current_key
            if reason.get("event_id") and not reason.get("rule_id"):
                item["value_semantics"] = "EVENT"  # value at occurred_at, not a newest aggregate
            measurements.append(item)
        for layer in ("fixed", "dynamic", "trend"):
            metrics = mapping(mapping(evaluation.get(layer)).get("metrics"))
            for key, value in metrics.items():
                value = mapping(value)
                status = value.get("effective_status") if layer == "fixed" else value.get("status")
                if status not in {"WARNING", "CRITICAL", "WATCH", "DEGRADING"} or value.get("contributes_to_status") is False:
                    continue
                if any(item.get("metric") == key and item["layer"] == layer.upper() for item in measurements):
                    continue
                item = select(value)
                item.update(metric=key, status=status, layer=layer.upper())
                if layer == 'trend':
                    policy = mapping(mapping(evaluation.get('resolved_policy')).get('trend'))
                    ratio_key = 'degrading_change_ratio' if status == 'DEGRADING' else 'watch_change_ratio'
                    if policy.get(ratio_key) is not None:
                        item['change_boundary'] = policy[ratio_key]
                measurements.append(item)
    snapshot = _frozen_host_snapshot(row, frozen_input)
    observations = _host_observations(snapshot, frozen_input)
    measurements.extend(observations)
    measurements.sort(key=lambda item: 0 if item.get("status") == "CRITICAL" or item.get("severity") == "P1" else 1)
    dynamic = mapping(evaluation.get("dynamic"))
    gaps = []
    if inactive:
        gaps.append(str(quality_state or evidence.get("error_code") or "EVIDENCE_INSUFFICIENT"))
    if dynamic.get("baseline_state") == "NOT_READY" or dynamic.get("status") == "NOT_READY":
        gaps.append("DYNAMIC_BASELINE_NOT_READY")
    for value in mapping(dynamic.get("metrics")).values():
        reason = mapping(value).get("quality_reason")
        if reason and reason not in gaps:
            gaps.append(str(reason))
    host_diagnostics = _host_diagnostic_presentation(row, evaluation, snapshot)
    return {
        **({"host_diagnostics": host_diagnostics} if host_diagnostics is not None else {}),
        "id": row.get("id"), "check": row.get("check") or row.get("inspection_item_code"),
        "check_name": row.get("inspection_item_name") or row.get("check") or row.get("inspection_item_code"),
        "asset_id": row.get("asset_id"), "asset_name": row.get("asset_name") or evidence.get("asset_name") or row.get("asset_id"),
        "status": row.get("status"), "summary": row.get("summary") or "", "source": "CODE",
        "checked_at": row.get("checked_at"), "window_start": snapshot.get("window_start") if observations else evidence.get("window_start") or mapping(evaluation.get("input")).get("window_start"),
        "window_end": snapshot.get("window_end") if observations else evidence.get("window_end") or mapping(evaluation.get("input")).get("window_end"),
        "snapshot_id": evidence.get("snapshot_id") or mapping(evaluation.get("input")).get("snapshot_id"),
        "quality": quality, "evidence_gaps": gaps, "measurements": measurements,
        "risks": row.get("risk_references") or [],
    }


def project_report(rows, *, run_id, frozen_input=None):
    facts = sorted((project_check(row, frozen_input=frozen_input) for row in rows), key=lambda row: (PRIORITY.get(row["status"], 5), str(row["asset_name"]), str(row["id"])))
    return {"source": "CODE", "inspection_run_id": str(run_id), "check_count": len(facts),
            "status_counts": {status: sum(row["status"] == status for row in facts) for status in PRIORITY},
            "checks": facts, "omitted_count": 0, "risk_state_note": "风险状态与等级为当前处置状态；检查事实为本次巡检的历史记录。"}


# Wording is owned by CODE. The model may select scoped qualitative checks only.
INTERPRETATIONS = {
    'latency_load': ('负载、排队或请求规模可能影响推理等待。', '核对该服务请求并发、排队、输入长度与异常时段的负载。'),
    'latency_config': ('服务配置或模型执行路径可能影响延迟；原因尚未确认。', '核对该服务模型配置、批处理与资源分配，并对照延迟指标复查。'),
    'baseline_review': ('当前负载与基线差异可能影响动态边界判断。', '核对该服务基线样本、请求分布及配置变更，保留原始边界后再复查。'),
    'trend_review': ('窗口内表现变化可能影响后续推理体验。', '核对该服务窗口前后负载和配置变化，追加采样确认趋势。'),
    'gpu_event_review': ('硬件事件可能影响该 GPU 的执行可靠性；根因与服务关联尚未确认。', '按事件发生时间核对该 GPU 驱动日志、设备状态及相关服务记录。'),
    'gpu_link_review': ('设备链路或供电状态值得核查；当前不能确认根因。', '核对该 GPU 对应设备链路、供电与驱动记录，确认事件是否复现。'),
    'memory_process': ('进程内存增长可能影响该机器可用内存；原因尚未确认。', '核对该机器进程内存、分配行为与同期负载，定位持续消耗来源。'),
    'memory_pressure': ('可用内存下降可能影响该机器承载能力。', '核对该机器内存余量、回收与交换活动，并持续观测下降趋势。'),
    'storage_review': ('可用存储余量下降可能影响该文件系统承载能力。', '核对对应文件系统写入增长、空间回收和保留水位；到水位时间不等于写满时间。'),
    'metric_review': ('该指标异常的业务影响仍需核查。', '核对该资源的原始指标、规则配置与同期运行日志。'),
    'evidence_review': ('现有证据不能确认该资源当前故障或整体健康。', '核对该资源采集时间、样本覆盖与数据质量，补齐证据后复查。'),
    'baseline_collect': ('动态基线未就绪，当前不能据此评价动态异常。', '核对该资源基线样本数量和质量，积累有效样本后复查。'),
    'passed_review': ('本次代码检查通过，未证明未来运行状态。', '按该资源观测窗口核对通过项证据，持续按既定规则观测。'),
}


def allowed_interpretations(row):
    """Bind possible hypotheses/actions to actual resource and metric evidence."""
    if row.get('status') in {'UNKNOWN', 'ERROR', 'NOT_APPLICABLE'}:
        return ['evidence_review']
    choices = []
    metrics = row.get('measurements') or []
    check = str(row.get('check') or '')
    for item in metrics:
        key = str(item.get('metric') or item.get('current_metric') or item.get('key') or '')
        if check == 'llm.performance_profile':
            if key.startswith(('ttft.', 'tpot.', 'e2e.', 'requests.')):
                choices.extend(['latency_load', 'latency_config'])
            if item.get('layer') == 'DYNAMIC':
                choices.append('baseline_review')
            if item.get('layer') == 'TREND':
                choices.append('trend_review')
        elif check == 'hardware.gpu_health' and key.startswith('gpu/'):
            choices.append('gpu_event_review')
            if item.get('xid_code') == 79:
                choices.append('gpu_link_review')
        elif check == 'hardware.host_health':
            if key.startswith('host/') and ('memory' in key or key == 'host/decline'):
                choices.extend(['memory_process', 'memory_pressure'])
            elif key.startswith('filesystem:'):
                choices.append('storage_review')
    if 'DYNAMIC_BASELINE_NOT_READY' in (row.get('evidence_gaps') or []):
        choices.append('baseline_collect')
    return list(dict.fromkeys(choices)) or ['passed_review' if row.get('status') == 'PASS' else 'metric_review']


def interpretation_choices(report, compact):
    facts = {str(row['id']): row for row in report.get('checks') or []}
    return {str(row['id']): allowed_interpretations(facts.get(str(row['id']), row))
            for row in compact.get('check_results') or []}


def _display(value):
    # Preserve original numbers: no inferred unit conversion, rounding or ETA.
    import math
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value) if math.isfinite(value) else '未提供'
    if isinstance(value, str):
        return value
    return '未提供'


def _measurement_text(item):
    key = str(item.get('metric') or item.get('current_metric') or item.get('key') or item.get('code') or '证据')
    unit = item.get('unit') or ('ms' if key.endswith('_ms') else 'bytes' if key.endswith('_bytes') or key.endswith('/decline') else '')
    layer = {'FIXED': '固定阈值', 'DYNAMIC': '动态边界', 'TREND': '窗口趋势', 'HARDWARE': '硬件证据', 'OBSERVATION': '原始观测'}.get(item.get('layer'), '证据')
    names = {'ttft.p95_ms': '首 Token 等待时间 P95', 'ttft.p99_ms': '首 Token 等待时间 P99', 'tpot.p95_ms': '逐 Token 生成耗时 P95', 'tpot.p99_ms': '逐 Token 生成耗时 P99', 'e2e.p95_ms': '完整请求耗时 P95', 'e2e.p99_ms': '完整请求耗时 P99', 'requests.waiting': '排队请求数', 'requests.running': '运行中请求数', 'host/memory_available_bytes': '可用内存', 'host/decline': '可用内存下降趋势', 'gpu/xid_events': 'GPU Xid 事件', 'gpu/ecc_dbe_delta': 'GPU 新增双比特 ECC 错误'}
    name = names.get(key, '文件系统可用空间' if key.startswith('filesystem:') else key)
    parts = [f"{layer} · {name}（{key}）" + (f" · {item['code']}" if item.get('code') else '')]
    labels = {'current': '事件时数值' if item.get('value_semantics') == 'EVENT' else '当前值', 'value': '记录值',
              'threshold': '触发阈值', 'boundary': '触发边界', 'baseline_median': '基线中位数',
              'change_ratio': '变化比例', 'change_boundary': '趋势变化比例边界',
              'first_half_median': '前半窗口中位数', 'second_half_median': '后半窗口中位数',
              'short_slope_bytes_per_second': '短期斜率', 'long_slope_bytes_per_second': '长期斜率',
              'reserve_bytes': '保留水位', 'seconds_to_reserve': '到保留水位时间', 'xid_code': 'Xid'}
    for field, label in labels.items():
        if item.get(field) is not None:
            suffix = ' bytes/s' if field.endswith('slope_bytes_per_second') else ' bytes' if field == 'reserve_bytes' else ' s（不是写满时间）' if field == 'seconds_to_reserve' else f' {unit}' if field in {'current', 'value', 'threshold', 'boundary', 'baseline_median', 'first_half_median', 'second_half_median'} and unit else ''
            parts.append(f'{label} {_display(item[field])}{suffix}')
    if item.get('measurement_semantics'):
        parts.append(str(item['measurement_semantics']))
    if item.get('occurred_at'):
        parts.append(f"事件发生时间 {item['occurred_at']}（独立于观测窗口）")
    if item.get('code') == 'XID_UNCLASSIFIED':
        parts.append('未分类事件，根因未确认')
    return '；'.join(parts)


def _fact_text(row):
    parts = [f"{row.get('check_name') or row.get('check')} · {row.get('status')}"]
    parts.extend(_measurement_text(item) for item in row.get('measurements') or [])
    if not row.get('measurements'):
        parts.append('未提供可确认异常的测量值')
    gaps = row.get('evidence_gaps') or []
    if gaps:
        parts.append('证据缺口：' + '、'.join(gaps) + '；不据此认定故障或整体健康')
    parts.append(f"历史观测窗口：{row.get('window_start') or '未提供'} — {row.get('window_end') or '未提供'}；检查时间：{row.get('checked_at') or '未提供'}")
    if (row.get('quality') or {}).get('state'):
        parts.append(f"当时数据状态：{row['quality']['state']}")
    for risk in row.get('risks') or []:
        parts.append(f"关联风险 {risk.get('id')} · {risk.get('title') or ''} · 当前 {risk.get('severity')} / {risk.get('status')}")
    parts.append(f"证据检查 ID：{row.get('id')} · {row.get('check')}")
    return '\n'.join(parts)


def _decode_interpretations(answer, choices):
    import json
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        data = json.loads(answer, object_pairs_hook=unique)
        if not isinstance(data, dict) or set(data) != set(choices):
            return None
        for check_id, keys in data.items():
            if not isinstance(keys, list) or not 1 <= len(keys) <= 2 or len(set(keys)) != len(keys):
                return None
            if any(not isinstance(key, str) or key not in choices[check_id] for key in keys):
                return None
        return data
    except (TypeError, ValueError):
        return None


def compose_grounded_explanation(report, compact, answer):
    """No unrestricted model text crosses either explanation display sink."""
    from .compact_context import validate_explanation_answer
    validate_explanation_answer(answer, compact)
    choices = interpretation_choices(report, compact)
    selections = _decode_interpretations(answer, choices)
    accepted = selections is not None
    counts = ' · '.join(f'{key} {value}' for key, value in report.get('status_counts', {}).items())
    coverage = (f"CODE 完整事实：{report['check_count']} 条检查（{counts}）。"
                f"AI 输入：{compact['selected_count']} / {compact['summary']['check_count']} 条检查，因输入预算省略 {compact['omitted_count']} 条；输入省略不代表证据不足。")
    previous = compact.get('previous_run')
    comparison = '缺少前次巡检摘要，无法比较；历史运行次数未知。'
    if isinstance(previous, dict):
        prior = previous.get('summary') or {}
        fields = ('check_count', 'fail_count', 'pass_count', 'unknown_count', 'error_count', 'risk_count')
        values = [f'{key} {_display(prior[key])}' for key in fields if isinstance(prior.get(key), (int, float)) and not isinstance(prior[key], bool)]
        if prior.get('status') in {'PASS', 'FAIL', 'UNKNOWN', 'ERROR', 'SUCCEEDED', 'PARTIAL'}:
            values.append(f"status {prior['status']}")
        comparison = f"提供的前次 Run {(previous.get('run') or {}).get('id') or '未提供'} 摘要：" + (' · '.join(values) or '未提供可比较的计数；不能推断逐资源变化。')
        if values:
            comparison += '；仅比较提供的摘要，不能推断逐资源指标变化。'
    rows = []
    for row in report.get('checks') or []:
        if row.get('status') == 'PASS' and not row.get('evidence_gaps') and not row.get('measurements'):
            continue
        check_id = str(row['id'])
        ai = None
        if accepted and check_id in selections:
            ai = {'source': 'AI', 'check_id': check_id, 'keys': selections[check_id],
                  'impact': '；'.join(INTERPRETATIONS[key][0] for key in selections[check_id]),
                  'next_check': '；'.join(INTERPRETATIONS[key][1] for key in selections[check_id])}
        reason = '未纳入本次 AI 输入；完整 CODE 事实已保留。' if check_id not in choices else 'AI 输出未满足逐资源受约束协议，未采纳其解读。' if not accepted else ''
        rows.append({'id': check_id, 'asset_name': row.get('asset_name'), 'source': 'CODE',
                     'facts_text': _fact_text(row), 'ai': ai, 'ai_note': reason})
    status = 'ACCEPTED' if accepted else 'INVALID_PROTOCOL'
    texts = ['[CODE] ' + coverage, '[CODE] ' + comparison]
    if not accepted:
        texts.append('AI 解读未通过受约束协议；以下仅为 CODE 事实，未发布模型自由文本。')
    for row in rows:
        texts.append(f"[CODE] {row['asset_name']}\n{row['facts_text']}")
        if row['ai']:
            texts.append(f"[AI 潜在影响，原因未确认] {row['ai']['impact']}\n[AI 核查建议] {row['ai']['next_check']}")
        elif row['ai_note']:
            texts.append(row['ai_note'])
    return {'source': 'CODE', 'coverage_text': coverage, 'comparison_text': comparison, 'checks': rows,
            'ai_status': status, 'accepted_count': len(selections or {}), 'text': '\n\n'.join(texts)}
