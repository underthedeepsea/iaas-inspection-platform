"""Fixed synthetic API contract; no network address, query language or algorithm engine."""
import math,hashlib,json
from time import monotonic
from datetime import datetime,timezone
from .mapping_services import MappingInputError,FIELD_SPECS,CAPACITY_PAIRS,COUNTER_FIELDS,MOCK_FILESYSTEM_IDENTITY
FIXTURES={'complete','missing','wrong-unit','no-data','zero','capacity-overflow','counter-reset-middle','counter-reset-end','counter-missing-start','counter-missing-end','counter-single-point'}
FIXTURE_VERSION='demo-hardware-inference-contract-v8'


class AmbiguousSeries(MappingInputError):
    """The fixed scoped source returned multiple competing series."""


class MissingSeries(MappingInputError):
    """No observation series; never a numeric zero."""


def window(start,end,step):
    if type(start)is not int or type(end)is not int or type(step)is not int or not 1<=step<=end-start<=3600 or len(range(start,end,step))>61:
        raise MappingInputError('Use integer seconds, an exact bounded [start,end) grid and <=61 points.')
    if end>int(datetime.now(timezone.utc).timestamp()):raise MappingInputError('Future observation window.')
    return list(range(start,end,step))


class SimulatedTimeout(MappingInputError):
    """Retryable timeout from the bounded synthetic transport."""


class SimulatedRateLimited(MappingInputError):
    """Retryable synthetic 429 with optional internal seconds-only RetryAfter."""

    def __init__(self, message, *, retry_after=None):
        self.retry_after = retry_after
        super().__init__(message)


class AttemptFixture:
    """Internal deterministic transport faults; not part of the query schema."""
    MODES = {'timeout-once', 'timeout-always', '429-once', '429-always'}

    def __init__(self, mode):
        if mode not in self.MODES:
            raise MappingInputError('Unknown attempt fixture.')
        self.mode = mode
        self.calls = 0

    def enter(self):
        self.calls += 1
        if self.mode.endswith('-always') or self.calls == 1:
            error = SimulatedTimeout if self.mode.startswith('timeout') else SimulatedRateLimited
            raise error('Synthetic timeout.' if error is SimulatedTimeout else 'Synthetic 429.')


def _deadline(deadline, clock):
    if deadline is not None and clock() >= deadline:
        raise SimulatedTimeout('Synthetic query deadline reached.')


def query(spec, *, deadline=None, clock=monotonic, attempt_fixture=None):
    _deadline(deadline, clock)
    expected={'source_ref','environment_id','cluster_uid','monitor_cluster_id','counter','fixture','seed','start','end','step'}
    disk=type(spec)is dict and type(spec.get('counter'))is str and spec['counter'].startswith(('demo.disk.','demo.filesystem.'))
    filesystem=disk and spec['counter'].startswith('demo.filesystem.')
    if disk:expected=expected|{'resource_labels'}
    if type(spec)is not dict or set(spec)!=expected or spec['source_ref']!='demo-monitor' or spec['fixture']not in FIXTURES or type(spec['seed'])is not int or not 0<=spec['seed']<=9999:
        raise MappingInputError('Unknown synthetic query scope/fixture/seed.')
    counters={value[0]:value[1]for value in FIELD_SPECS.values()}
    if spec['counter']not in counters:raise MappingInputError('Unknown synthetic counter.')
    if disk and spec['resource_labels']!=(MOCK_FILESYSTEM_IDENTITY if filesystem else {'block_device':'nvme0n1'}):raise MappingInputError('Unknown synthetic resource identity.')
    grid=window(spec['start'],spec['end'],spec['step'])
    if attempt_fixture is not None:
        if type(attempt_fixture) is not AttemptFixture:
            raise MappingInputError('Unknown internal attempt fixture.')
        attempt_fixture.enter()
    _deadline(deadline, clock)
    if spec['counter'].startswith('demo.llm.'):
        from .mapping_inference import query_summary
        raw = query_summary(spec, counters[spec['counter']], FIXTURE_VERSION)
        _deadline(deadline, clock)
        return raw
    points=[{'timestamp':stamp,'value':0.0 if spec['fixture']=='zero' else 40.0+(spec['seed']%10),'quality':'VALID'}for stamp in grid]
    byte_values={'demo.filesystem.available_bytes':50*1024**3,'demo.filesystem.size_bytes':100*1024**3,'demo.gpu.memory_used':8*1024**3,'demo.gpu.memory_total':16*1024**3,'demo.host.memory_available':32*1024**3,'demo.host.memory_total':64*1024**3}
    if spec['counter']in byte_values:
        for point in points:point['value']=0 if spec['fixture']=='zero'and not spec['counter'].endswith(('.memory_total','.size_bytes'))else byte_values[spec['counter']]
    if spec['fixture']=='capacity-overflow'and spec['counter']in {'demo.gpu.memory_used','demo.host.memory_available','demo.filesystem.available_bytes'}:
        for point in points:point['value']=0
        points[0]['value']=24*1024**3 if spec['counter']=='demo.gpu.memory_used'else 96*1024**3 if spec['counter']=='demo.host.memory_available' else 150*1024**3
    if spec['counter']=='demo.disk.io_busy_ratio':
        for point in points:point['value']=0.0 if spec['fixture']=='zero' else (40.0+spec['seed']%10)/100
    if spec['counter']in {'demo.disk.read_latency_avg_seconds','demo.disk.write_latency_avg_seconds'}:
        for point in points:point['value']=0.0 if spec['fixture']=='zero'else 0.002 if spec['counter']=='demo.disk.read_latency_avg_seconds'else 0.003
    if spec['fixture']=='missing':points=points[:-1]
    if spec['fixture']=='no-data':points=[]
    raw={'synthetic':True,'source_ref':spec['source_ref'],'environment_id':spec['environment_id'],'cluster_uid':spec['cluster_uid'],'monitor_cluster_id':spec['monitor_cluster_id'],'fixture':spec['fixture'],'fixture_version':FIXTURE_VERSION,'seed':spec['seed'],'counter':spec['counter'],'unit':'bytes'if spec['fixture']=='wrong-unit'else counters[spec['counter']],'dstype':'GAUGE','start':spec['start'],'end':spec['end'],'step':spec['step'],'series':[{'endpoint':spec['monitor_cluster_id'],'labels':{'cluster_uid':spec['cluster_uid']},'points':points}]}

    counter_field=next((field for field,(source,_) in COUNTER_FIELDS.items() if source==spec['counter']),None)
    if counter_field is not None:
        # The end observation is a real boundary, outside the ordinary grid.
        # It still consumes one of the existing total 61 source points.
        if len(grid)+1>61:raise MappingInputError('Counter grid plus end boundary exceeds 61 points.')
        stamps=grid+[spec['end']]
        points=[{'timestamp':stamp,'value':0 if spec['fixture']=='zero' else index+spec['seed'],'quality':'VALID'} for index,stamp in enumerate(stamps)]
        if spec['fixture']=='counter-reset-middle':points[len(points)//2]['value']=0
        if spec['fixture']=='counter-reset-end':points[-1]['value']=0
        if spec['fixture'] in {'missing','counter-missing-end'}:points=points[:-1]
        if spec['fixture']=='counter-missing-start':points=points[1:]
        if spec['fixture']=='counter-single-point':points=points[:1]
        if spec['fixture']=='no-data':points=[]
        raw['dstype']='COUNTER'
        raw['series'][0].update(points=points,source_metric=spec['counter'],semantics=COUNTER_FIELDS[counter_field][1],scope='DRAM')

    if spec['counter']=='demo.gpu.xid_events':
        identity={key:spec[key]for key in ['environment_id','cluster_uid','monitor_cluster_id','start','end','seed']}
        event_id='demo-xid-'+hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        quality='MISSING'if spec['fixture']=='missing'else'UNSUPPORTED'if spec['fixture']=='no-data'else'VALID'
        events=[]if spec['fixture']=='zero'else[{'event_id':event_id,'code':79,'timestamp':spec['start']}]
        raw['dstype']='EVENTS';raw['series']=[{'endpoint':spec['monitor_cluster_id'],'labels':{'cluster_uid':spec['cluster_uid']},'quality':quality,'events':events if quality=='VALID'else None}]
    if disk:
        raw['resource_labels']=dict(spec['resource_labels']);raw['series'][0]['labels'].update(spec['resource_labels'])
    _deadline(deadline, clock)
    return raw


def normalize(raw,spec,metric):
    if metric['standard_field'].startswith('llm.'):
        from .mapping_inference import normalize_summary
        return normalize_summary(raw, spec, metric, FIXTURE_VERSION)
    expected_keys={'synthetic','source_ref','environment_id','cluster_uid','monitor_cluster_id','fixture','fixture_version','seed','counter','unit','dstype','start','end','step','series'}
    disk=metric['standard_field'].startswith(('disk.','filesystem.'))
    resource_identity=MOCK_FILESYSTEM_IDENTITY if metric['standard_field'].startswith('filesystem.') else {'block_device':'nvme0n1'}
    if disk:expected_keys=expected_keys|{'resource_labels'}
    if type(raw)is not dict or set(raw)!=expected_keys or raw['synthetic']is not True or raw['fixture_version']!=FIXTURE_VERSION or raw['unit']!=metric['source_unit'] or raw['dstype']!=metric['source_type']:
        raise MappingInputError('Synthetic response contract/unit mismatch.')
    if disk and (spec.get('resource_labels')!=resource_identity or metric['labels']!=spec['resource_labels']):raise MappingInputError('Disk source/mapping identity mismatch.')
    if any(raw[key]!=spec[key]for key in spec):raise MappingInputError('Synthetic response scope/window mismatch.')
    series=raw['series']
    if type(series)is list and not series:raise MissingSeries('No series returned; coverage is missing, not zero.')
    if type(series)is list and len(series)>1:raise AmbiguousSeries('Multiple series for one scoped field; no first/merge/aggregate selection.')
    if metric['standard_field']=='gpu.xid_events':
        return normalize_events(raw,spec,metric)
    if metric['standard_field'] in COUNTER_FIELDS:
        return normalize_counter(raw,spec,metric)
    series=raw['series'];expected_labels={'cluster_uid':spec['cluster_uid'],**(spec['resource_labels']if disk else{})}
    if type(series)is not list or len(series)!=1 or set(series[0])!={'endpoint','labels','points'} or series[0]['endpoint']!=spec['monitor_cluster_id'] or series[0]['labels']!=expected_labels:
        raise MappingInputError('Ambiguous synthetic series.')
    points=series[0]['points'];grid=window(spec['start'],spec['end'],spec['step'])
    if type(points)is not list or len(points)!=len(grid):raise MappingInputError('Synthetic coverage must be100%; missing data is never zero.')
    values=[]
    for point,stamp in zip(points,grid):
        if type(point)is not dict or set(point)!={'timestamp','value','quality'} or type(point['timestamp'])is not int or point['timestamp']!=stamp or point['quality']!='VALID' or type(point['value'])not in(int,float) or not math.isfinite(point['value']) or point['value']<0:
            raise MappingInputError('Invalid/duplicate/out-of-order/nonfinite synthetic point.')
        values.append(point['value'])
    mean=sum(values)/len(values)
    if metric['conversion']=='DIVIDE_100':
        if any(value>100 for value in values):raise MappingInputError('Percent outside0..100.')
        return mean/100
    if metric['conversion']=='MULTIPLY_1000':
        if metric['source_unit']!='seconds'or metric['output_unit']!='ms':raise MappingInputError('Seconds/ms unit contract required.')
        converted=mean*1000
        if not math.isfinite(converted):raise MappingInputError('Converted latency must be finite.')
        return converted
    if metric['conversion']=='IDENTITY':
        if metric['output_unit']=='ratio' and any(value>1 for value in values):raise MappingInputError('Ratio outside0..1.')
        return mean
    raise MappingInputError('Unsupported conversion.')


def normalize_counter(raw,spec,metric):
    """Same-series full-window ECC delta; never infer missing boundary values."""
    field=metric['standard_field'];source,bits=COUNTER_FIELDS[field]
    if (tuple(metric[key] for key in ('source_metric','source_unit','output_unit','conversion'))!=FIELD_SPECS[field]
            or metric['source_type']!='COUNTER' or metric['labels']!={} or spec['counter']!=source):
        raise MappingInputError('Invalid ECC counter mapping contract.')
    series=raw['series']
    if (type(series)is not list or len(series)!=1 or type(series[0])is not dict
            or set(series[0])!={'endpoint','labels','points','source_metric','semantics','scope'}):
        raise MappingInputError('Expected one explicitly attested ECC counter series.')
    row=series[0]
    if (row['endpoint']!=spec['monitor_cluster_id'] or row['labels']!={'cluster_uid':spec['cluster_uid']}
            or row['source_metric']!=source or row['semantics']!=bits or row['scope']!='DRAM'):
        raise MappingInputError('ECC counter source identity/DRAM/bit semantics mismatch.')
    stamps=window(spec['start'],spec['end'],spec['step'])+[spec['end']]
    points=row['points']
    if len(stamps)>61 or type(points)is not list or len(points)!=len(stamps) or len(points)<2:
        raise MappingInputError('Counter requires full grid plus both boundaries, 2..61 total points; never zero fill.')
    reset=False;previous=None
    for point,stamp in zip(points,stamps):
        if (type(point)is not dict or set(point)!={'timestamp','value','quality'}
                or type(point['timestamp'])is not int or point['timestamp']!=stamp):
            raise MappingInputError('Invalid/duplicate/out-of-order counter timestamp.')
        value=point['value']
        if point['quality']=='RESET' and value is None:
            reset=True;previous=None;continue
        if type(point['quality'])is not str or point['quality'] not in {'VALID','RESET'} or type(value)is not int or value<0:
            raise MappingInputError('ECC counter observations must be nonnegative integer counts or explicit RESET/null.')
        if point['quality']=='RESET' or previous is not None and value<previous:reset=True
        previous=value
    return {'value':None if reset else points[-1]['value']-points[0]['value'],
            'quality':'RESET' if reset else 'VALID',
            'collected_at':datetime.fromtimestamp(spec['end'],timezone.utc).isoformat(),
            'source_metric':source,'semantics':bits,'scope':'DRAM'}


def normalize_events(raw,spec,metric):
    """Window events, never a count/counter; preserve source identity and time."""
    if metric['source_type']!='EVENTS' or metric['source_unit']!='events' or metric['output_unit']!='events' or metric['conversion']!='EVENT_LIST':
        raise MappingInputError('Invalid event mapping contract.')
    window(spec['start'],spec['end'],spec['step'])
    series=raw['series']
    if type(series)is not list or len(series)!=1 or type(series[0])is not dict or set(series[0])!={'endpoint','labels','quality','events'}:
        raise MappingInputError('Expected one bounded event series.')
    row=series[0]
    if row['endpoint']!=spec['monitor_cluster_id'] or row['labels']!={'cluster_uid':spec['cluster_uid']}:
        raise MappingInputError('Invalid event series scope.')
    if row['quality'] in ('MISSING','UNSUPPORTED'):
        if row['events'] is not None:raise MappingInputError('Nonvalid events must be null; never invent event evidence.')
        return {'value':None,'quality':row['quality'],'collected_at':datetime.fromtimestamp(spec['end']-spec['step'],timezone.utc).isoformat()}
    if row['quality']!='VALID' or type(row['events'])is not list or len(row['events'])>1000:
        raise MappingInputError('Invalid/missing/unsupported event series or scope.')
    result=[];seen=set()
    for event in row['events']:
        if type(event)is not dict or set(event)!={'event_id','code','timestamp'}:
            raise MappingInputError('Invalid event shape.')
        identity=event['event_id'];code=event['code'];stamp=event['timestamp']
        if type(identity)is not str or not 1<=len(identity)<=192 or not all(c.isalnum()or c in '_.:-'for c in identity) or identity in seen or type(code)is not int or not 1<=code<=999 or type(stamp)is not int or not spec['start']<=stamp<spec['end']:
            raise MappingInputError('Invalid duplicate/event identity, code or window.')
        seen.add(identity);result.append({'event_id':identity,'code':code,'occurred_at':datetime.fromtimestamp(stamp,timezone.utc).isoformat()})
    return result


def validate_capacities(raws_by_field):
    """Check paired original points before averaging can hide capacity violations."""
    for left,right in CAPACITY_PAIRS:
        if left not in raws_by_field and right not in raws_by_field:continue
        if left not in raws_by_field or right not in raws_by_field:raise MappingInputError('Capacity pair missing.')
        values=raws_by_field[left]['series'][0]['points'];totals=raws_by_field[right]['series'][0]['points']
        if len(values)!=len(totals)or not values:raise MappingInputError('Capacity pair coverage mismatch.')
        for point,total in zip(values,totals):
            a,b=point['value'],total['value']
            if point['timestamp']!=total['timestamp']or type(a)not in(int,float)or type(b)not in(int,float)or not math.isfinite(a)or not math.isfinite(b)or a<0 or b<=0 or a>b:
                raise MappingInputError('Invalid raw capacity pair; averaging cannot repair it.')
