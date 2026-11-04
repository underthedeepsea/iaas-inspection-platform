"""Coverage of server-frozen mapping inputs, separate from execution and risk.

No latest-data lookup, detector or threshold. Required metric names come from
existing hardware schema for the actual kind/components of each frozen payload.
"""
from apps.hardware_health.schemas import FIELDS,parse_request

BINDING_FIELDS=('batch_id','revision_id','content_hash','validation_id','activation_id','source_ref','environment_id','window_start','window_end','snapshot_ids','asset_ids','versions')


def mapping_input_quality(run):
    config=run.config_snapshot or {}
    if 'mapping_inputs'not in config:return None
    provenance=config.get('mapping_inputs')
    source=config.get('input') or {}
    errors=[];missing=[];required=valid=0
    if not isinstance(provenance,dict):provenance={};errors.append('INVALID_MAPPING_PROVENANCE')
    expected={key:provenance.get(key)for key in BINDING_FIELDS}
    if source.get('source_type')!='HARDWARE_SNAPSHOT':return _mapping_external_quality(run,provenance,source)
    from .inference_freeze import mapping_binding
    expected=mapping_binding(provenance)
    if source.get('source_type')!='HARDWARE_SNAPSHOT' or source.get('mapping_binding')!=expected:errors.append('EXPLICIT_BINDING_MISMATCH')
    if expected['source_ref']!='demo-monitor' or expected['environment_id']!=str(run.environment_id):errors.append('ENVIRONMENT_SOURCE_MISMATCH')
    if not isinstance(expected['content_hash'],str)or len(expected['content_hash'])!=64:errors.append('MISSING_REVISION_HASH')
    try:
        from apps.core.mapping_loop import versions
        if expected['versions']!=versions():errors.append('CONTRACT_POLICY_MISMATCH')
    except (ValueError,TypeError,KeyError):errors.append('INVALID_CONTRACT_VERSION')
    frozen=source.get('snapshots')or{}
    if not isinstance(frozen,dict):frozen={};errors.append('INVALID_SNAPSHOT_MAP')
    asset_ids=expected['asset_ids']if isinstance(expected['asset_ids'],list)else[]
    snapshot_ids=expected['snapshot_ids']if isinstance(expected['snapshot_ids'],list)else[]
    if not asset_ids or len(asset_ids)!=len(set(asset_ids))or set(frozen)!=set(asset_ids):errors.append('ASSET_SET_MISMATCH')
    actual_ids=[]
    for asset_id,snapshot in frozen.items():
        if not isinstance(snapshot,dict):errors.append('MISSING_SNAPSHOT');continue
        actual_ids.append(snapshot.get('snapshot_id'))
        payload=snapshot.get('payload')or{}
        if not isinstance(payload,dict):payload={};errors.append('INVALID_PAYLOAD')
        kind=payload.get('kind');primary={'HOST':'host','GPU':'gpu'}.get(kind)
        if (snapshot.get('asset_id')!=asset_id or snapshot.get('environment_id')!=str(run.environment_id)
                or payload.get('environment_id')!=str(run.environment_id)or payload.get('source')!=expected['source_ref']
                or snapshot.get('window_start')!=expected['window_start']or snapshot.get('window_end')!=expected['window_end']
                or payload.get('window_start')!=expected['window_start']or payload.get('window_end')!=expected['window_end']
                or payload.get('config_id')!=expected['revision_id']or payload.get('sample_id')!=f"mapping:{expected['batch_id']}:{kind}"):
            errors.append('SNAPSHOT_SCOPE_WINDOW_REVISION_MISMATCH')
        schema_ok=True
        try:parse_request({key:value for key,value in payload.items()if not key.startswith('_')})
        except Exception:schema_ok=False;errors.append('FROZEN_SCHEMA_INVALID')
        components=payload.get('metrics')or{}
        if not isinstance(components,dict):components={};schema_ok=False
        if primary is None:errors.append('INVALID_HARDWARE_KIND');continue
        components={**{primary:{}},**components}
        for component,body in components.items():
            family=component.split(':')[0]
            if family not in FIELDS:errors.append('UNKNOWN_COMPONENT');continue
            points=body.get('values',{})if isinstance(body,dict)else{}
            for metric in sorted(FIELDS[family]):
                required+=1;point=points.get(metric,{})if isinstance(points,dict)else{}
                covered=schema_ok and isinstance(point,dict)and point.get('quality')=='VALID'and point.get('value')is not None
                if covered:valid+=1
                elif len(missing)<256:missing.append({'asset_id':asset_id,'component':component,'field':metric,'quality':point.get('quality','UNCONFIGURED')if isinstance(point,dict)else'UNCONFIGURED'})
    if len(actual_ids)!=len(set(actual_ids))or set(actual_ids)!=set(snapshot_ids):errors.append('SNAPSHOT_SET_MISMATCH')
    complete=required>0 and required==valid and not errors
    return {'status':'COMPLETE'if complete else'PARTIAL','required_fields':required,'valid_fields':valid,'coverage':valid/required if required else 0.0,'missing_count':required-valid,'missing':missing,'missing_truncated':required-valid>len(missing),'binding_errors':sorted(set(errors)),'baseline_status':provenance.get('baseline_status','NOT_READY'),'basis':'frozen hardware schema-required kind/component fields; execution and risk remain separate'}


def _mapping_external_quality(run, provenance, source):
    from copy import deepcopy
    from types import SimpleNamespace
    from .inference_freeze import mapping_binding, validate_exact_inference_snapshot
    errors=[]; required=valid=0;missing=[]
    try:
        expected=mapping_binding(provenance)
        if source.get('mapping_binding')!=expected:errors.append('EXPLICIT_BINDING_MISMATCH')
        from apps.core.mapping_loop import versions
        if provenance['versions']!=versions():errors.append('CONTRACT_POLICY_MISMATCH')
        if provenance['environment_id']!=str(run.environment_id):errors.append('ENVIRONMENT_SOURCE_MISMATCH')
        parts=source.get('sources') if source.get('source_type')=='EXTERNAL_SNAPSHOTS' else {source.get('source_type'):source}
        if not isinstance(parts,dict)or not parts:raise ValueError('Missing source partition')
        actual_ids=[];actual_assets=[]
        for kind,part in parts.items():
            if kind not in {'INFERENCE_SNAPSHOT','HARDWARE_SNAPSHOT'} or part.get('source_type')!=kind or part.get('mapping_binding')!=expected:
                raise ValueError('Invalid source partition binding')
            rows=part.get('snapshots')or{}
            if sorted(rows)!=sorted(provenance['source_asset_ids'][kind]):errors.append('ASSET_SET_MISMATCH')
            if sorted(r['snapshot_id']for r in rows.values())!=sorted(provenance['source_snapshot_ids'][kind]):errors.append('SNAPSHOT_SET_MISMATCH')
            actual_ids.extend(r['snapshot_id']for r in rows.values());actual_assets.extend(rows)
            if kind=='HARDWARE_SNAPSHOT':
                sub=deepcopy(provenance);sub['asset_ids']=list(rows);sub['snapshot_ids']=[r['snapshot_id']for r in rows.values()]
                frozen=deepcopy(part);frozen['mapping_binding']=mapping_binding(sub)
                quality=mapping_input_quality(SimpleNamespace(environment_id=run.environment_id,config_snapshot={'mapping_inputs':sub,'input':frozen}))
                required+=quality['required_fields'];valid+=quality['valid_fields'];missing.extend(quality['missing']);errors.extend(quality['binding_errors'])
            else:
                for asset_id,row in rows.items():
                    required+=20
                    try:
                        if row.get('asset_id')!=asset_id:raise ValueError('Asset key mismatch')
                        validate_exact_inference_snapshot(row,environment_id=run.environment_id,provenance=provenance)
                    except (ValueError,KeyError,TypeError):errors.append('INFERENCE_SNAPSHOT_INVALID');missing.append({'asset_id':asset_id,'field':'complete20'})
                    else:valid+=20
        if len(actual_ids)!=len(set(actual_ids))or sorted(actual_ids)!=sorted(provenance['snapshot_ids']):errors.append('SNAPSHOT_SET_MISMATCH')
        if len(actual_assets)!=len(set(actual_assets))or sorted(actual_assets)!=sorted(provenance['asset_ids']):errors.append('ASSET_SET_MISMATCH')
    except (ValueError,KeyError,TypeError):errors.append('INVALID_MAPPING_PROVENANCE')
    return {'status':'COMPLETE'if required and required==valid and not errors else'PARTIAL','required_fields':required,
            'valid_fields':valid,'coverage':valid/required if required else 0.,'missing_count':required-valid,'missing':missing[:256],
            'missing_truncated':len(missing)>256,'binding_errors':sorted(set(errors)),
            'baseline_status':provenance.get('baseline_status','NOT_READY'),'basis':'exact frozen source-partitioned hardware/inference schema fields'}
