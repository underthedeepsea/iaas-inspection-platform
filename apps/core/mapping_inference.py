"""Fixed MOCK request-window summaries and exact-batch inference identity."""
import hashlib
import json
import math
from datetime import datetime, timezone
from . import mapping_services as store


def check_scope(scope):
    if any(scope.get(key) != value for key, value in store.MOCK_INFERENCE_SCOPE.items()):
        raise store.MappingScopeError('Unregistered MOCK inference source/cluster/monitor.')
    if type(scope.get('environment_id')) is not str or not scope['environment_id']:
        raise store.MappingScopeError('Inference requires the bound environment namespace.')


def query_summary(spec, unit, version):
    check_scope(spec)
    field = next((f for f, definition in store.INFERENCE_FIELD_SPECS.items() if definition[0] == spec['counter']), None)
    if field is None: raise store.MappingInputError('Unknown inference source metric.')
    _, group, name = field.split('.')
    values = {'avg_ms': 100., 'p90_ms': 200., 'p95_ms': 250., 'p99_ms': 300., 'e2e_ratio': .1,
              'qps': 2., 'qpm': 120., 'generation_tps': 64., 'prompt_tps': 128.,
              'kv_cache_hit_rate': .8, 'running': 2., 'waiting': 0.}
    value = values[name] * (10 if group == 'e2e' and name.endswith('_ms') else .1 if group == 'tpot' else 1)
    row = {'endpoint': spec['monitor_cluster_id'],
           'labels': {'cluster_uid': spec['cluster_uid'], 'engine_id': store.MOCK_INFERENCE_ENGINE['engine_id']},
           'replica_id': store.MOCK_INFERENCE_ENGINE['engine_id'],
           'semantics': 'request_window_quantile' if name.startswith(('p90_', 'p95_', 'p99_')) else 'request_window_summary',
           'window_start': spec['start'], 'window_end': spec['end'], 'quality': 'VALID',
           'value': 0. if spec['fixture'] == 'zero' else value}
    if spec['fixture'] == 'missing': row['quality'] = 'MISSING'; row['value'] = None
    return {**spec, 'synthetic': True, 'fixture_version': version, 'unit': 'bytes' if spec['fixture'] == 'wrong-unit' else unit,
            'dstype': 'REQUEST_WINDOW', 'engine': dict(store.MOCK_INFERENCE_ENGINE),
            'series': [] if spec['fixture'] == 'no-data' else [row]}


def normalize_summary(raw, spec, metric, version):
    check_scope(spec)
    field = metric['standard_field']
    if field not in store.INFERENCE_FIELD_SPECS:
        raise store.MappingInputError('Unknown inference field.')
    definition = store.INFERENCE_FIELD_SPECS[field]
    if (tuple(metric[k] for k in ('source_metric', 'source_unit', 'output_unit', 'conversion')) != definition
            or metric['source_type'] != 'REQUEST_WINDOW'
            or metric['labels'] != {'engine_id': store.MOCK_INFERENCE_ENGINE['engine_id']}
            or spec['counter'] != definition[0]):
        raise store.MappingInputError('Inference mapping contract mismatch.')
    expected = set(spec) | {'synthetic', 'fixture_version', 'unit', 'dstype', 'engine', 'series'}
    if (type(raw) is not dict or set(raw) != expected or raw['synthetic'] is not True
            or raw['fixture_version'] != version or raw['unit'] != definition[1]
            or raw['dstype'] != 'REQUEST_WINDOW' or raw['engine'] != store.MOCK_INFERENCE_ENGINE
            or any(raw[key] != spec[key] for key in spec)):
        raise store.MappingInputError('Inference response scope/window/unit/engine mismatch.')
    rows = raw['series']
    if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
        raise store.MappingInputError('One complete inference request-window series required; never merge replicas.')
    row = rows[0]; name = field.split('.')[2]
    if (set(row) != {'endpoint', 'labels', 'replica_id', 'semantics', 'window_start', 'window_end', 'quality', 'value'}
            or row['endpoint'] != spec['monitor_cluster_id']
            or row['labels'] != {'cluster_uid': spec['cluster_uid'], 'engine_id': store.MOCK_INFERENCE_ENGINE['engine_id']}
            or row['replica_id'] != store.MOCK_INFERENCE_ENGINE['engine_id']
            or row['semantics'] != ('request_window_quantile' if name.startswith(('p90_', 'p95_', 'p99_')) else 'request_window_summary')
            or type(row['window_start']) is not int or type(row['window_end']) is not int
            or row['window_start'] != spec['start'] or row['window_end'] != spec['end']
            or row['quality'] != 'VALID' or type(row['value']) not in (int, float)
            or not math.isfinite(row['value']) or row['value'] < 0
            or definition[2] == 'ratio' and row['value'] > 1):
        raise store.MappingInputError('Invalid inference request-window summary proof/value.')
    return row['value']


def sample_id(provenance):
    identity = [str(provenance[k]) for k in ('batch_id', 'revision_id', 'content_hash', 'cluster_uid', 'monitor_cluster_id')]
    encoded = json.dumps(identity, separators=(',', ':')).encode()
    return 'mapping:' + str(provenance['batch_id']) + ':LLM:' + hashlib.sha256(encoded).hexdigest()


def request_for_values(bound, values, *, batch_id, revision_id, content_hash):
    from apps.inference_performance.schemas import parse_snapshot_request
    selected = {field: value for field, value in values.items() if field.startswith('llm.')}
    if not selected: return None
    check_scope(bound)
    if set(selected) != set(store.INFERENCE_FIELD_SPECS):
        raise store.MappingInputError('All20 inference fields required; no defaults or partial snapshot.')
    sample = {group: {} for group in store.INFERENCE_METRICS}
    for field, value in selected.items():
        _, group, name = field.split('.'); sample[group][name] = value
    provenance = {**bound, 'batch_id': batch_id, 'revision_id': revision_id, 'content_hash': content_hash}
    sample.update(sample_id=sample_id(provenance),
                  window_start=datetime.fromtimestamp(bound['start'], timezone.utc).isoformat(),
                  window_end=datetime.fromtimestamp(bound['end'], timezone.utc).isoformat())
    try:
        return parse_snapshot_request({'source': store.SOURCE_REF, 'environment_id': bound['environment_id'],
                                       'engine': dict(store.MOCK_INFERENCE_ENGINE), 'sample': sample})
    except ValueError as exc:
        raise store.MappingInputError(str(exc)) from exc
