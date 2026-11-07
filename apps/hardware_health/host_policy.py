"""Approved Linux HOST rules on external observations; no collector or scheduler."""
from copy import deepcopy
from datetime import datetime, timedelta
from math import isclose

HOST_PLUGIN = {'id': 'gpu-host-health', 'version': '2.0.0'}
HOST_SEMANTICS = {'os': 'LINUX', 'memory_available': 'MemAvailable', 'memory_total': 'MemTotal', 'unit': 'bytes'}
POLICY = {'collection_seconds': 60, 'evaluation_seconds': 60, 'freshness_seconds': 180,
          'retention_days': 30, 'trigger_points': 3, 'recovery_points': 5,
          'decline_max_seconds': 1800, 'decline_max_points': 31,
          'decline_min_seconds': 600, 'decline_min_points': 11,
          'cpu_drift': {'absolute_effect': .20, 'relative_effect': .15, 'history_days': 14,
                        'history_points': 30, 'robust_multiplier': 3, 'cusum_k': .5, 'cusum_h': 5,
                        'confirmation_points': 3, 'recovery_ratio': .70, 'recovery_points': 5,
                        'semantics': 'BRANCH_SPECIFIC_FROZEN_THRESHOLD', 'maximum_series_points': 12}}
RULES = {'host/cpu_static': {'warning': .80, 'critical': .90, 'critical_exit': .85, 'warning_exit': .75, 'direction': 'HIGH'},
         'host/memory_static': {'warning': .20, 'critical': .10, 'critical_exit': .15, 'warning_exit': .25, 'direction': 'LOW'}}


def retained_before(as_of):
    """Only a cutoff; callers must preserve referenced snapshots and frozen evidence."""
    return as_of - timedelta(days=POLICY['retention_days'])


def retention_candidates(rows, *, as_of):
    """Dry-run IDs only. No writes, deletion, or claim of an installed retention job."""
    cutoff = retained_before(as_of)
    return [str(row.pk) for row in rows if row.window_end < cutoff]


def freshness_seconds(evaluation):
    return 180 if evaluation.get('plugin') == HOST_PLUGIN else 300


def observed(row, metric):
    point = row.payload['metrics'].get('host', {}).get('values', {}).get(metric, {})
    try:
        collected = datetime.fromisoformat(point['collected_at'])
        fresh = 0 <= (row.window_end-collected).total_seconds() <= POLICY['freshness_seconds']
    except (KeyError, TypeError, ValueError):
        return None, None
    if point.get('quality') != 'VALID' or not fresh:
        return None, collected
    return point.get('value'), collected


def _valid_static_context(context):
    return bool(isinstance(context, dict) and all(isinstance(context.get(key), str) and context[key].strip()
                for key in ('source', 'config_id', 'host_id')) and isinstance(context.get('identity'), dict)
                and context.get('host_semantics') == HOST_SEMANTICS)


def static_rules(snapshot, previous):
    prior = (previous[-1].evaluation or {}) if previous else {}
    states = deepcopy(prior.get('host_rule_states', {}))
    events = deepcopy(prior.get('host_rule_events', {}))
    diagnostics, issues = {}, []
    payload = snapshot.payload
    context = {key: deepcopy(payload.get(key)) for key in ('source', 'config_id', 'host_id', 'identity', 'host_semantics')}
    for key, approved in RULES.items():
        old = states.get(key, {})
        rule = deepcopy(events.get(old.get('event_id'), {}).get('frozen_rule', approved))
        metric = 'cpu_busy_ratio' if key.endswith('cpu_static') else 'memory_available_bytes'
        current, collected = observed(snapshot, metric)
        if metric == 'memory_available_bytes':
            total, total_at = observed(snapshot, 'memory_total_bytes')
            current = current/total if current is not None and total and total_at == collected and 0 <= current <= total else None
        reason = None
        if payload.get('host_semantics') != HOST_SEMANTICS:
            current = None; reason = 'LINUX_SOURCE_SEMANTICS_NOT_ATTESTED'
        elif current is None:
            reason = 'INVALID_OR_STALE_POINT'
        connected = bool(collected and old.get('last_collected_at') and old.get('context') == context
                         and (collected-datetime.fromisoformat(old['last_collected_at'])).total_seconds() == 60)
        counters = {name: old.get(name, 0) if connected else 0 for name in ('warning_points', 'critical_points', 'critical_recovery_points', 'warning_recovery_points')}
        level = old.get('state', 'NORMAL')
        event_id = old.get('event_id')
        event = events.get(event_id, {})
        frozen_context = event.get('frozen_context')
        same_event_context = not event_id or (_valid_static_context(frozen_context) and frozen_context == context)
        if not same_event_context:
            reason = 'EVENT_CONTEXT_MISMATCH' if _valid_static_context(frozen_context) else 'EVENT_CONTEXT_MISSING'
        elif not _valid_static_context(context):
            current = None; reason = 'INVALID_SOURCE_CONTEXT'
        high = rule['direction'] == 'HIGH'
        trigger = lambda limit: current >= limit if high else current <= limit
        recover = lambda limit: current < limit if high else current > limit
        if current is None or not same_event_context:
            counters = {name: 0 for name in counters}
        else:
            conditions = {'warning_points': trigger(rule['warning']), 'critical_points': trigger(rule['critical']),
                          'critical_recovery_points': recover(rule['critical_exit']), 'warning_recovery_points': recover(rule['warning_exit'])}
            counters = {name: counters[name]+1 if condition else 0 for name, condition in conditions.items()}
            if counters['critical_points'] >= 3:
                level = 'CRITICAL'
            elif level == 'CRITICAL' and counters['critical_recovery_points'] >= 5:
                level = 'NORMAL' if counters['warning_recovery_points'] >= 5 else 'WARNING'
            elif level == 'WARNING' and counters['warning_recovery_points'] >= 5:
                level = 'NORMAL'
            elif level == 'NORMAL' and counters['warning_points'] >= 3:
                level = 'WARNING'
            if level in {'WARNING', 'CRITICAL'} and not event_id:
                event_id = key+':'+str(snapshot.pk)
                events[event_id] = {'event_id': event_id, 'rule_key': key, 'rule_version': '2.0.0', 'frozen_rule': deepcopy(rule),
                                    'triggered_at': collected.isoformat(), 'trigger_value': current, 'status': 'ACTIVE',
                                    'frozen_context': deepcopy(context)}
            if event_id and level == 'NORMAL':
                events[event_id].update(status='RECOVERED', recovered_at=collected.isoformat(),
                                        recovery_window_start=(collected-timedelta(seconds=240)).isoformat(), recovery_points=5,
                                        recovery_context=deepcopy(context))
                event_id = None
        if level in {'WARNING', 'CRITICAL'}:
            status = level
            reason = reason or ('RECOVERY_PENDING' if counters['warning_recovery_points'] or counters['critical_recovery_points'] else 'CONFIRMED_STATIC_LIMIT')
        elif current is None:
            status = 'NOT_READY'
        elif counters['warning_points']:
            status = 'PENDING'; reason = 'TRIGGER_CONFIRMATION_PENDING'
        else:
            status = 'NORMAL'; reason = 'STATIC_LIMIT_NOT_REACHED'
        count = counters['critical_points'] if current is not None and trigger(rule['critical']) else counters['warning_points']
        result = {'status': status, 'state': level, 'reason': reason, 'current': current, 'unit': 'ratio',
                  'rule_id': key, 'rule_version': '2.0.0', 'rule': rule, 'event_id': event_id,
                  'frozen_context': deepcopy(events[event_id].get('frozen_context')) if event_id else None,
                  'confirmation_points': min(3, count), 'confirmation_required': 3, 'trigger_window_seconds': 120,
                  'recovery_required': 5, 'recovery_window_seconds': 240, **counters,
                  'last_collected_at': collected.isoformat() if collected else None, 'context': context,
                  'window_start': snapshot.window_start.isoformat(), 'window_end': snapshot.window_end.isoformat(),
                  'action': '核对该主机CPU负载及进程，持续采集以确认恢复。' if high else '核对MemAvailable、回收及交换压力，持续采集以确认恢复。'}
        states[key] = result; diagnostics[key] = deepcopy(result)
        if level in {'WARNING', 'CRITICAL'}:
            issues.append({'key': key, 'code': 'HOST_CPU_STATIC_LIMIT' if high else 'HOST_MEMORY_STATIC_LIMIT',
                           'severity': 'P1' if level == 'CRITICAL' else 'P2', **deepcopy(result)})
    return diagnostics, issues, states, events


def static_event_recovered(evaluation, issue, handled_at):
    """The original event and its frozen rule remain the recovery obligation."""
    event = evaluation.get('host_rule_events', {}).get(issue.get('event_id'), {})
    if issue.get('rule_id') in RULES:
        frozen_context = event.get('frozen_context')
        state = evaluation.get('host_rule_states', {}).get(issue['rule_id'], {})
        if (not _valid_static_context(frozen_context) or issue.get('frozen_context') != frozen_context
                or event.get('recovery_context') != frozen_context or state.get('context') != frozen_context
                or state.get('state') != 'NORMAL' or state.get('status') != 'NORMAL' or state.get('current') is None):
            return False
    try:
        start = datetime.fromisoformat(event['recovery_window_start'])
        return bool(event.get('status') == 'RECOVERED' and event.get('rule_key') == issue['rule_id']
                    and event.get('rule_version') == issue['rule_version'] and event.get('frozen_rule') == issue.get('rule')
                    and event.get('recovery_points', 0) >= 5 and start.tzinfo is not None and start > handled_at)
    except (KeyError, TypeError, ValueError):
        return False


def cpu_deviation(series, baseline):
    """Bounded 12-point two-path confirmation; strict legacy 3-scale comparison."""
    from statistics import median
    if len(baseline)<30 or not series:
        return {'status':'NOT_READY','sample_count':len(baseline),'reason':'INSUFFICIENT_COMPARABLE_HISTORY'}
    base=median(baseline);mad=median(abs(x-base) for x in baseline)
    scale=max(1.4826*mad,.20/3,abs(base)*.15/3,1e-9)
    minimum=max(.20,abs(base)*.15)
    positive=negative=0.;direct=cumulative=0;last_direction=0
    for current in series[-12:]:
        delta=current-base;direction=1 if delta>0 else -1 if delta<0 else 0
        z=delta/scale;positive=max(0.,positive+z-.5);negative=min(0.,negative+z+.5)
        if direction!=last_direction:direct=cumulative=0
        reached=abs(delta)>=minimum or isclose(abs(delta),minimum,rel_tol=1e-15,abs_tol=1e-15)
        direct=direct+1 if reached and abs(delta)>3*scale else 0
        score=positive if direction==1 else -negative if direction==-1 else 0.
        cumulative=cumulative+1 if reached and score>=5 else 0
        last_direction=direction
    branches={}
    if direct>=3:branches['DIRECT']={'threshold':max(minimum,3*scale),'base':base,'scale':scale}
    if cumulative>=3:branches['CUSUM']={'threshold':minimum,'base':base,'scale':scale}
    return {'status':'WARNING' if branches else 'PENDING' if direct or cumulative else 'NORMAL',
            'sample_count':len(baseline),'current':series[-1],'unit':'ratio','baseline_median':base,'mad':mad,
            'robust_scale':scale,'minimum_effect':minimum,'cusum_positive':positive,'cusum_negative':negative,
            'direction':'UP' if last_direction==1 else 'DOWN' if last_direction==-1 else 'FLAT',
            'direct_confirmation_points':min(3,direct),'cusum_confirmation_points':min(3,cumulative),
            'confirmation_points':min(3,max(direct,cumulative)),'branches':branches,'series_points':min(12,len(series))}


def cpu_rules(snapshot, previous, states, events, *, comparable):
    """Freeze the triggering branch obligations; recovery never uses a moving base."""
    from types import SimpleNamespace
    key='host/cpu_busy_ratio';old=states.get(key,{})
    event_id=old.get('event_id');active=events.get(event_id)
    current,collected=observed(snapshot,'cpu_busy_ratio')
    def context(payload):return {k:payload.get(k) for k in ('source','identity','config_id','bindings','host_semantics')}
    valid=current is not None and snapshot.payload.get('host_semantics')==HOST_SEMANTICS
    if active:
        reference=SimpleNamespace(payload=active['reference_payload'])
        valid=valid and context(snapshot.payload)==context(reference.payload) and comparable(snapshot,reference)
        connected=bool(collected and old.get('last_collected_at') and (collected-datetime.fromisoformat(old['last_collected_at'])).total_seconds()==60)
        within=valid and all(abs(current-b['base'])<=b['threshold']*.70 or isclose(abs(current-b['base']),b['threshold']*.70,rel_tol=1e-15,abs_tol=1e-15) for b in active['branches'].values())
        recovery=(old.get('recovery_points',0) if connected else 0)+1 if within else 0
        result={'status':'WARNING','current':current,'baseline_median':next(iter(active['branches'].values()))['base'],
                'branches':deepcopy(active['branches']),'reason':'RECOVERY_PENDING' if valid else 'INVALID_OR_INCOMPARABLE_POINT',
                'recovery_points':recovery,'confirmation_points':3,'series_points':active['series_points']}
        if recovery>=5:
            active.update(status='RECOVERED',recovery_points=5,recovered_at=collected.isoformat(),recovery_window_start=(collected-timedelta(seconds=240)).isoformat())
            event_id=None;result.update(status='NORMAL',reason='FROZEN_BRANCH_RECOVERY_CONFIRMED')
    else:
        recent=[]
        for item in reversed(list(previous)+[snapshot]):
            value,at=observed(item,'cpu_busy_ratio')
            if (value is None or item.payload.get('host_semantics')!=HOST_SEMANTICS or context(item.payload)!=context(snapshot.payload)
                    or not comparable(snapshot,item) or recent and (recent[-1][1]-at).total_seconds()!=60):break
            recent.append((value,at,item))
            if len(recent)==12:break
        recent.reverse()
        # Hold out the full bounded observation window even when invalid points
        # shorten the comparable suffix; a gap must not move recent drift into baseline.
        observation_window=(list(previous)+[snapshot])[-12:]
        cutoff=observation_window[0].window_start
        baseline=[]
        for item in previous:
            value,_=observed(item,'cpu_busy_ratio')
            if (value is not None and snapshot.window_start-timedelta(days=14)<=item.window_end<=cutoff
                    and context(item.payload)==context(snapshot.payload) and comparable(snapshot,item)):
                baseline.append(value)
        result=cpu_deviation([x[0] for x in recent],baseline)
        result['current']=current
        if not valid or not recent:result.update(status='NOT_READY',reason='INVALID_OR_INCOMPARABLE_POINT')
        if result['status']=='WARNING':
            event_id=key+':'+str(snapshot.pk)
            branches=deepcopy(result['branches'])
            events[event_id]={'event_id':event_id,'rule_key':key,'rule_version':'2.0.0','status':'ACTIVE',
                              'branches':branches,'series_points':result['series_points'],'frozen_rule':{'branches':deepcopy(branches)},'triggered_at':collected.isoformat(),
                              'reference_payload':{k:deepcopy(snapshot.payload.get(k)) for k in ('source','identity','config_id','bindings','host_semantics','_inference')}}
        result.setdefault('reason','CONFIRMED_CONDITIONAL_DRIFT' if event_id else 'DRIFT_CONFIRMATION_PENDING' if result['status']=='PENDING' else 'DRIFT_BOUNDARY_NOT_REACHED')
    result.update(rule_id=key,rule_version='2.0.0',unit='ratio',event_id=event_id,
                  rule=deepcopy(events[event_id]['frozen_rule']) if event_id else {},
                  confirmation_required=3,trigger_window_seconds=120,recovery_required=5,recovery_window_seconds=240,
                  last_collected_at=collected.isoformat() if collected else None,
                  action='核对同来源、配置与可比负载；按冻结分支门槛连续五点验证恢复。')
    states[key]=deepcopy(result)
    issue={'key':key,'code':'CONDITIONAL_DRIFT','severity':'P2',**deepcopy(result)} if event_id else None
    return result,issue
