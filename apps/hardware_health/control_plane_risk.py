"""Pure presentation of retained v2 decisions; never evaluates a health rule."""

GROUPS = ('API_SERVER_ONLY', 'ETCD_ONLY', 'MIXED')


def group_id(node):
    roles = set(node['roles'])
    if {'API_SERVER', 'ETCD'} <= roles:
        return 'MIXED'
    if 'API_SERVER' in roles:
        return 'API_SERVER_ONLY'
    if 'ETCD' in roles:
        return 'ETCD_ONLY'
    return 'UNKNOWN' if 'UNKNOWN' in roles else 'OTHER'


def project_risk(node, now):
    from .performance_profile import timestamp, number, current_point, point_time, HOST_PLUGIN, LINUX_MEMORY
    row = node.get('_latest') or {}
    evaluation = row.get('evaluation') or {}
    payload = row.get('payload') or {}
    diagnostics = evaluation.get('diagnostics') or {}
    start, end = timestamp(row.get('start')), timestamp(row.get('end'))
    context = {k: payload.get(k) for k in ('source', 'config_id', 'host_id', 'identity', 'host_semantics')}
    base_gaps = []
    if evaluation.get('plugin') != HOST_PLUGIN:
        base_gaps.append('缺少冻结v2诊断')
    if not start or not end or not start < end or not 0 <= (now-end).total_seconds() <= 180:
        base_gaps.append('快照窗口缺失或已过期')
    if (not all(isinstance(context[k], str) and context[k].strip() for k in ('source', 'config_id', 'host_id'))
            or context['source'] != row.get('source') or not isinstance(context['identity'], dict)
            or context['host_semantics'] != LINUX_MEMORY):
        base_gaps.append('来源、身份、配置或Linux语义缺项')
    required = {'host/cpu_static', 'host/memory_static', 'host/cpu_busy_ratio', 'host/decline'}
    for component, body in payload.get('metrics', {}).items():
        required.update(component+'/'+key for key in body.get('values', {}))
    # Missing inventories stay unknown, as in the frozen evaluator's coverage.
    inventory_gaps = ['覆盖缺项：'+key for key, state in evaluation.get('coverage', {}).items() if state != 'READY']
    gaps, items = list(base_gaps)+inventory_gaps, []
    for key in sorted(required):
        d = diagnostics.get(key)
        if not isinstance(d, dict):
            gaps.append(key+'：无冻结诊断'); continue
        local = list(base_gaps)
        component, metric = key.split('/', 1)
        metric = 'cpu_busy_ratio' if key == 'host/cpu_static' else 'memory_available_bytes' if key in {'host/memory_static', 'host/decline'} else metric
        at = point_time(row, component, metric) if row else None
        value = current_point(row, component, metric, now) if row else None
        if value is None or at is None or not start or not start <= at <= end:
            local.append('缺少本窗口VALID新鲜原点')
        if key in {'host/memory_static', 'host/decline'}:
            total = current_point(row, 'host', 'memory_total_bytes', now)
            if not total or value is None or not 0 <= value <= total or point_time(row, 'host', 'memory_total_bytes') != at:
                local.append('内存容量或同采集时间缺项')
            elif key == 'host/memory_static': value /= total
        status = d.get('status')
        if status not in {'NORMAL', 'WARNING', 'CRITICAL'}:
            local.append('判定尚未就绪：'+str(status))
        static = key in {'host/cpu_static', 'host/memory_static'}
        policy = static or key == 'host/cpu_busy_ratio'
        if policy:
            if d.get('rule_id') != key or d.get('rule_version') != '2.0.0' or timestamp(d.get('last_collected_at')) != at:
                local.append('规则身份或诊断采集时间不匹配')
            if number(d.get('current')) != value:
                local.append('诊断值与有效原点不匹配')
            if static and (d.get('context') != context or timestamp(d.get('window_start')) != start or timestamp(d.get('window_end')) != end or not d.get('rule')):
                local.append('冻结规则、上下文或窗口不匹配')
        if status in {'WARNING', 'CRITICAL'}:
            confirmed = (number(d.get('confirmation_points')) is not None and number(d.get('confirmation_required')) is not None
                         and d['confirmation_required'] == 3 and d['confirmation_points'] >= d['confirmation_required'] and d.get('trigger_window_seconds') == 120)
            event = evaluation.get('host_rule_events', {}).get(d.get('event_id'), {})
            event_context = event.get('frozen_context') == context if static else all(event.get('reference_payload', {}).get(k) == payload.get(k) for k in ('source', 'identity', 'config_id', 'bindings', 'host_semantics'))
            event_valid = bool(d.get('event_id') and event.get('status') == 'ACTIVE' and event.get('rule_key') == key
                               and event.get('rule_version') == '2.0.0' and event.get('frozen_rule') == d.get('rule') and event_context)
            if d.get('event_id') and not event_valid:
                local.append('已有活动事件身份、规则或上下文不匹配')
            if static and d.get('frozen_context') != context:
                local.append('异常事件冻结上下文不匹配')
            if d.get('reason') not in {'CONFIRMED_STATIC_LIMIT', 'CONFIRMED_CONDITIONAL_DRIFT', 'RECOVERY_PENDING'}:
                local.append('冻结异常缺少有效确认原因')
            if not policy or not (confirmed or event_valid):
                local.append('缺少可信规则确认点或活动事件状态')
            if static and d.get('state') != status:
                local.append('冻结状态与等级不匹配')
        # Generic diagnostics have no independently frozen rule identity/confirmation.
        # Keep their missing evidence explicit instead of manufacturing a decision.
        if not policy and status in {'WARNING', 'CRITICAL'}:
            local.append('冻结诊断未保存可核验规则身份')
        if local:
            gaps.extend(key+'：'+gap for gap in local); continue
        items.append({'key': key, 'level': status, 'current': d.get('current', value), 'unit': d.get('unit', 'ratio' if 'ratio' in metric else 'bytes'),
                      'rule_id': d.get('rule_id', key), 'rule_version': d.get('rule_version', '2.0.0'),
                      'rule': d.get('rule'), 'reason': d.get('reason'), 'confirmation_points': d.get('confirmation_points'),
                      'confirmation_required': d.get('confirmation_required'), 'collected_at': at.isoformat() if at else None})
    triggers = [item for item in items if item['level'] in {'CRITICAL', 'WARNING'}]
    level = 'CRITICAL' if any(i['level'] == 'CRITICAL' for i in triggers) else 'WARNING' if triggers else 'UNKNOWN' if gaps else 'NORMAL'
    return {'level': level, 'incomplete': bool(gaps), 'complete': not gaps, 'triggers': triggers, 'items': items,
            'required_keys': sorted(required), 'missing': list(dict.fromkeys(gaps)), 'sample_time': end.isoformat() if end else None}


def summarize(nodes):
    counts = {level: sum(n['risk']['level'] == level for n in nodes) for level in ('CRITICAL', 'WARNING', 'UNKNOWN', 'NORMAL')}
    return {'counts': counts, 'risk_hosts': counts['CRITICAL']+counts['WARNING'],
            'incomplete': sum(n['risk']['incomplete'] for n in nodes),
            'coverage': {'covered': sum(n['risk']['complete'] for n in nodes), 'total': len(nodes)},
            'metric_coverage': {key: {'covered': sum(any(i['key'] == key for i in n['risk']['items']) for n in nodes), 'total': len(nodes)}
                                for key in sorted({key for n in nodes for key in n['risk']['required_keys']} | {'host/cpu_static', 'host/memory_static', 'host/cpu_busy_ratio', 'host/decline'})}}
