"""Freeze the real inference facts selected at run creation time."""

from copy import deepcopy

from django.utils import timezone

from apps.inference_performance.models import InferencePerformanceSnapshot


SOURCE = "INFERENCE_SNAPSHOT"


def freeze_inference_inputs(asset_ids, *, as_of=None):
    as_of = as_of or timezone.now()
    frozen = {}
    for asset_id in asset_ids:
        snapshot = (
            InferencePerformanceSnapshot.objects.filter(
                asset_id=asset_id,
                window_end__lte=as_of,
                created_at__lte=as_of,
            )
            .order_by("-window_end", "-created_at", "-pk")
            .first()
        )
        if snapshot is None:
            frozen[str(asset_id)] = None
            continue
        frozen[str(asset_id)] = {
            "snapshot_id": str(snapshot.pk),
            "environment_id": str(snapshot.environment_id),
            "asset_id": str(asset_id),
            "identity": {"environment_id": str(snapshot.environment_id), "asset_id": str(asset_id)},
            "engine_id": snapshot.engine_id,
            "engine_type": snapshot.engine_type,
            "model_name": snapshot.model_name,
            "window_start": snapshot.window_start.isoformat(),
            "window_end": snapshot.window_end.isoformat(),
            "created_at": snapshot.created_at.isoformat(),
            "frozen_at": as_of.isoformat(),
            "evaluation": deepcopy(snapshot.evaluation),
        }
    return {"source_type": SOURCE, "as_of": as_of.isoformat(), "snapshots": frozen}


def freeze_external_inputs(asset_ids, *, sources, as_of=None):
    """All plugins see one as-of boundary; old single-source runs stay readable."""
    from apps.hardware_health.services import freeze_hardware_inputs
    as_of = as_of or timezone.now()
    readers = {'INFERENCE_SNAPSHOT': freeze_inference_inputs, 'HARDWARE_SNAPSHOT': freeze_hardware_inputs}
    inputs = {source: readers[source](asset_ids, as_of=as_of) for source in sorted(sources)}
    if len(inputs) == 1:
        return next(iter(inputs.values()))
    return {'source_type': 'EXTERNAL_SNAPSHOTS', 'as_of': as_of.isoformat(), 'sources': inputs}


def input_for_plugin(run_input, source):
    if run_input.get('source_type') == 'EXTERNAL_SNAPSHOTS':
        return (run_input.get('sources') or {}).get(source) or {}
    return run_input if run_input.get('source_type') == source else {}


def freeze_exact_hardware_inputs(snapshot_ids, *, environment_id, provenance, as_of):
    """Explicit mapping-owned IDs; no latest-snapshot query or cross-batch fallback."""
    from apps.hardware_health.models import HardwareSnapshot
    ids=[str(value) for value in snapshot_ids]
    if not ids or len(ids)>2 or len(ids)!=len(set(ids)) or sorted(ids)!=sorted(provenance.get('source_snapshot_ids',{}).get('HARDWARE_SNAPSHOT',provenance['snapshot_ids'])):
        raise ValueError('Invalid explicit hardware snapshot IDs')
    rows=list(HardwareSnapshot.objects.filter(pk__in=ids))
    if len(rows)!=len(ids):raise ValueError('Missing exact hardware input')
    frozen={}
    for row in rows:
        if str(row.environment_id)!=str(environment_id) or row.source!='demo-monitor' or row.created_at>as_of or str(row.asset_id)not in provenance.get('source_asset_ids',{}).get('HARDWARE_SNAPSHOT',provenance['asset_ids']) or row.window_start.isoformat()!=provenance['window_start'] or row.window_end.isoformat()!=provenance['window_end'] or row.payload['config_id']!=provenance['revision_id'] or row.sample_id!=f"mapping:{provenance['batch_id']}:{row.payload['kind']}":
            raise ValueError('Exact hardware input scope/provenance mismatch')
        frozen[str(row.asset_id)]={'snapshot_id':str(row.pk),'asset_id':str(row.asset_id),'environment_id':str(row.environment_id),'window_start':row.window_start.isoformat(),'window_end':row.window_end.isoformat(),'created_at':row.created_at.isoformat(),'frozen_at':as_of.isoformat(),'evaluation':deepcopy(row.evaluation),'payload':deepcopy(row.payload)}
    from apps.inspections.services.mapping_coverage import BINDING_FIELDS
    return {'source_type':'HARDWARE_SNAPSHOT','as_of':as_of.isoformat(),'snapshots':frozen,'mapping_binding':mapping_binding(provenance)}


def mapping_binding(provenance):
    from apps.inspections.services.mapping_coverage import BINDING_FIELDS
    keys = (*BINDING_FIELDS, *(key for key in ('cluster_uid', 'monitor_cluster_id', 'source_snapshot_ids', 'source_asset_ids') if key in provenance))
    return {key: deepcopy(provenance[key]) for key in keys}


def validate_exact_inference_snapshot(snapshot, *, environment_id, provenance):
    from apps.core.mapping_inference import check_scope, sample_id
    from apps.core.mapping_services import MOCK_INFERENCE_ENGINE
    from apps.inference_performance.schemas import parse_sample
    check_scope(provenance)
    if (snapshot.get('environment_id') != str(environment_id)
            or provenance['environment_id'] != str(environment_id)
            or snapshot.get('source') != provenance['source_ref']
            or any(snapshot.get(key) != value for key, value in MOCK_INFERENCE_ENGINE.items())
            or snapshot.get('sample_id') != sample_id(provenance)
            or snapshot.get('window_start') != provenance['window_start']
            or snapshot.get('window_end') != provenance['window_end']
            or snapshot.get('asset_id') not in provenance['source_asset_ids']['INFERENCE_SNAPSHOT']):
        raise ValueError('Exact inference scope/window/engine/batch/revision mismatch')
    parsed = parse_sample({'sample_id': snapshot['sample_id'], 'window_start': snapshot['window_start'],
                           'window_end': snapshot['window_end'], **snapshot['metrics']})
    expected = {field[4:]: value for field, value in provenance['mapped_values'].items() if field.startswith('llm.')}
    actual = {group+'.'+name: value for group, names in parsed.metrics.items() for name, value in names.items()}
    if actual != expected: raise ValueError('Exact inference metrics mismatch')


def freeze_exact_inference_inputs(snapshot_ids, *, environment_id, provenance, as_of):
    ids = [str(value) for value in snapshot_ids]
    if (len(ids) != 1 or len(set(ids)) != len(ids)
            or ids != provenance['source_snapshot_ids']['INFERENCE_SNAPSHOT']):
        raise ValueError('Invalid explicit inference snapshot IDs')
    rows = list(InferencePerformanceSnapshot.objects.filter(pk__in=ids))
    if len(rows) != len(ids): raise ValueError('Missing exact inference input')
    frozen = {}
    for row in rows:
        value = {key: deepcopy(getattr(row, key)) for key in ('engine_id', 'engine_type', 'model_name', 'source', 'sample_id', 'metrics', 'evaluation')}
        value.update(snapshot_id=str(row.pk), asset_id=str(row.asset_id), environment_id=str(row.environment_id),
                     identity={'environment_id': str(row.environment_id), 'asset_id': str(row.asset_id)},
                     window_start=row.window_start.isoformat(), window_end=row.window_end.isoformat(),
                     created_at=row.created_at.isoformat(), frozen_at=as_of.isoformat())
        if row.created_at > as_of or row.window_end > as_of: raise ValueError('Future exact inference input')
        validate_exact_inference_snapshot(value, environment_id=environment_id, provenance=provenance)
        frozen[str(row.asset_id)] = value
    if set(frozen) != set(provenance['source_asset_ids']['INFERENCE_SNAPSHOT']):
        raise ValueError('Exact inference asset set mismatch')
    return {'source_type': SOURCE, 'as_of': as_of.isoformat(), 'snapshots': frozen, 'mapping_binding': mapping_binding(provenance)}


def freeze_exact_mapping_inputs(hardware_ids, inference_ids, *, environment_id, provenance, as_of):
    partition = {'HARDWARE_SNAPSHOT': [str(x) for x in hardware_ids], SOURCE: [str(x) for x in inference_ids]}
    combined = partition['HARDWARE_SNAPSHOT'] + partition[SOURCE]
    if (partition != provenance.get('source_snapshot_ids') or not combined or len(combined) != len(set(combined))
            or sorted(combined) != sorted(provenance['snapshot_ids'])
            or provenance['environment_id'] != str(environment_id)):
        raise ValueError('Exact mapping snapshot partition mismatch')
    readers = {'HARDWARE_SNAPSHOT': freeze_exact_hardware_inputs, SOURCE: freeze_exact_inference_inputs}
    inputs = {source: readers[source](ids, environment_id=environment_id, provenance=provenance, as_of=as_of)
              for source, ids in partition.items() if ids}
    assets = [asset for part in inputs.values() for asset in part['snapshots']]
    if len(assets) != len(set(assets)) or sorted(assets) != sorted(provenance['asset_ids']):
        raise ValueError('Exact mapping asset partition mismatch')
    if len(inputs) == 1: return next(iter(inputs.values()))
    return {'source_type': 'EXTERNAL_SNAPSHOTS', 'as_of': as_of.isoformat(), 'sources': inputs, 'mapping_binding': mapping_binding(provenance)}
