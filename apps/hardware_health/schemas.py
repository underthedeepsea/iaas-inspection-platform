"""Bounded explicit metric/quality contract. Unsupported values are never zero."""
from datetime import timedelta
from django.utils import timezone
from apps.inference_performance.schemas import _object, _text as _normalized_text, _number, _timestamp, _error, parse_engine

FIELDS = {
    'gpu': {'utilization_ratio', 'memory_used_bytes', 'memory_total_bytes', 'temperature_celsius', 'xid_events', 'ecc_sbe_delta', 'ecc_dbe_delta'},
    'host': {'cpu_busy_ratio', 'memory_available_bytes', 'memory_total_bytes'},
    'filesystem': {'available_bytes', 'size_bytes'},
    'disk': {'read_bytes_per_second', 'write_bytes_per_second', 'read_latency_avg_ms', 'write_latency_avg_ms', 'io_busy_ratio'},
}
IDENTITY = {'gpu': set(), 'host': set(), 'filesystem': {'filesystem', 'mountpoint', 'block_device'}, 'disk': {'block_device'}}
QUALITIES = {'VALID', 'MISSING', 'UNSUPPORTED', 'RESET'}


def _text(value, field, maximum):
    """Validate the retained identity, without changing existing idempotency keys."""
    _normalized_text(value, field, maximum)
    if len(value) > maximum:
        _error(f'{field} must be no longer than {maximum} characters as supplied', field)
    return value


def parse_request(payload):
    required = {'source', 'environment_id', 'sample_id', 'window_start', 'window_end', 'host_id', 'config_id', 'kind', 'identity', 'metrics', 'bindings'}
    raw = _object(payload, 'request')
    if not required <= raw.keys() or set(raw) - required - {'hardware_reverification'}:
        _error('request has missing or unsupported fields', 'request')
    for key, limit in [('source',64), ('environment_id',128), ('sample_id',192), ('host_id',192), ('config_id',192)]:
        _text(raw[key], key, limit)
    if not isinstance(raw['kind'],str) or raw['kind'] not in {'GPU','HOST'}:
        _error('kind must be GPU or HOST', 'kind')
    start, end = (_timestamp(raw[k], k) for k in ('window_start','window_end'))
    if start >= end or end > timezone.now() or (end-start).total_seconds() > 3600:
        _error('window must be past, positive and no longer than one hour', 'window_end')
    identity = _object(raw['identity'], 'identity', exact={'gpu_uuid','model'} if raw['kind']=='GPU' else set())
    for key, value in identity.items():
        _text(value, 'identity.'+key, 192)
    metrics = _object(raw['metrics'], 'metrics')
    if not 1 <= len(metrics) <= 128:
        _error('metrics requires 1..128 components', 'metrics')
    if raw['kind']=='GPU' and set(metrics) != {'gpu'} or raw['kind']=='HOST' and 'host' not in metrics:
        _error('required primary component is absent', 'metrics')
    for component, body in metrics.items():
        _text(component, 'component', 192)
        family = component.split(':')[0]
        if family not in FIELDS or (raw['kind']=='GPU') != (family=='gpu'):
            _error('invalid component family', component)
        if family in {'filesystem','disk'} and (':' not in component or not component.split(':',1)[1]):
            _error('component requires stable identity suffix', component)
        if family=='host' and component!='host':
            _error('host component key must be host', component)
        body = _object(body, component, exact={'identity','values'})
        ids = _object(body['identity'], component+'.identity', exact=IDENTITY[family])
        for k,v in ids.items(): _text(v, component+'.identity.'+k, 192)
        values = _object(body['values'], component+'.values', exact=FIELDS[family])
        for metric, point in values.items():
            path = component+'.'+metric
            ecc = metric in {'ecc_sbe_delta','ecc_dbe_delta'}
            point = _object(point, path, exact={'value','quality','collected_at'} | ({'source_metric','semantics','scope'} if ecc else set()))
            if not isinstance(point['quality'],str) or point['quality'] not in QUALITIES:
                _error('unsupported quality', path)
            collected = _timestamp(point['collected_at'], path+'.collected_at')
            if not start <= collected <= end + timedelta(minutes=5) or collected > timezone.now():
                _error('collection time outside observation boundary', path)
            if ecc:
                _text(point['source_metric'], path+'.source_metric', 192)
                if point['scope']!='DRAM' or point['semantics'] != ('SINGLE_BIT' if metric=='ecc_sbe_delta' else 'DOUBLE_BIT'):
                    _error('ECC must attest bit semantics and DRAM scope', path)
            value=point['value']
            if point['quality']!='VALID':
                if value is not None: _error('non-valid values must be null', path)
                continue
            if metric=='xid_events':
                if not isinstance(value,list) or len(value)>1000: _error('xid_events must be bounded event list',path)
                seen={}
                for event in value:
                    _object(event,path,exact={'event_id','code','occurred_at'})
                    _text(event['event_id'],path+'.event_id',192)
                    if type(event['code']) is not int or not 1<=event['code']<=999: _error('Xid code must be integer',path)
                    if not start <= _timestamp(event['occurred_at'],path) < end: _error('event outside window',path)
                    if event['event_id'] in seen: _error('duplicate event identity in window',path)
                    seen[event['event_id']]=event
                continue
            number = _number(value,path)
            if metric.endswith('_ratio') and number>1: _error('ratio outside 0..1',path)
            if ecc and type(value) is not int: _error('ECC delta must be integer',path)
        def valid(k): return values.get(k,{}).get('quality')=='VALID'
        for used,total in [('memory_used_bytes','memory_total_bytes'),('memory_available_bytes','memory_total_bytes'),('available_bytes','size_bytes')]:
            if valid(used) and valid(total) and (values[total]['value']<=0 or values[used]['value']>values[total]['value']):
                _error('invalid capacity pair',component)
    bindings=_object(raw['bindings'],'bindings',exact={'complete','engines'})
    if type(bindings['complete']) is not bool or not isinstance(bindings['engines'],list) or len(bindings['engines'])>64:
        _error('invalid engine bindings','bindings')
    engines=[parse_engine(engine) for engine in bindings['engines']]
    if len(set(engines))!=len(engines): _error('duplicate engine binding','bindings')
    if 'hardware_reverification' in raw:
        att=_object(raw['hardware_reverification'],'hardware_reverification',exact={'event_ids','performed_at','method','result'})
        if not isinstance(att['event_ids'],list) or not 1<=len(att['event_ids'])<=1000 or any(not isinstance(x,str) for x in att['event_ids']) or len(set(att['event_ids']))!=len(att['event_ids']):
            _error('invalid attestation event list','hardware_reverification')
        for value in att['event_ids']: _text(value,'event_id',256)
        _text(att['method'],'method',512)
        if att['result']!='PASSED' or not start <= _timestamp(att['performed_at'],'performed_at') <= end:
            _error('attestation must pass within current window','hardware_reverification')
    return raw, start, end
