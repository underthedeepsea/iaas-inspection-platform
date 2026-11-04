from django.db import transaction
from django.utils import timezone

from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemRun, InspectionRun, ResourceType
from apps.inspections.services.events import append_run_event
from apps.inspections.services.inference_freeze import SOURCE, freeze_external_inputs
from apps.inspections.services.scope import (
    asset_ids_for_selectors,
    resolve_item_asset_scope,
    resolve_scope,
    scope_to_snapshot,
)
from apps.inspections.rules.registry import UnsupportedInspectionRule, get_code_plugin


AI_MODES = {"DEFERRED", "DISABLED"}


@transaction.atomic
def create_manual_inspection_run(*, environment, resource_type_codes, ai_mode="DEFERRED", run_date=None, explicit_hardware_snapshot_ids=None, explicit_inference_snapshot_ids=None, mapping_inputs=None):
    if ai_mode not in AI_MODES:
        raise ValueError("ai_mode must be DEFERRED or DISABLED")
    environment = Environment.objects.select_for_update().get(pk=environment.pk)
    run_date = run_date or timezone.localdate()
    requested_codes = _requested_codes(resource_type_codes)
    scope = resolve_scope(
        environment_id=environment.pk,
        resource_type_codes=requested_codes,
    )
    if not scope.inspection_item_ids:
        raise ValueError("NO_ACTIVE_PLUGIN")
    items = list(InspectionItem.objects.filter(id__in=scope.inspection_item_ids).order_by("code", "created_at", "pk"))
    try:
        sources = {get_code_plugin(item.code).input_source for item in items}
    except UnsupportedInspectionRule:
        raise ValueError("NO_ACTIVE_PLUGIN") from None
    if not sources or not sources <= {'INFERENCE_SNAPSHOT', 'HARDWARE_SNAPSHOT'}:
        raise ValueError("unsupported inspection input source")
    as_of = timezone.now()
    resolved_snapshot = scope_to_snapshot(scope)
    resolved_snapshot['resource_asset_ids'] = {
        resource.code: sorted(str(pk) for pk in asset_ids_for_selectors(environment.pk, [resource.asset_selector], frozen_ids=scope.asset_ids))
        for resource in ResourceType.objects.filter(code__in=scope.resource_type_codes)
    }
    frozen_input = None
    if explicit_inference_snapshot_ids is not None:
        expected_sources = ({'HARDWARE_SNAPSHOT'} if explicit_hardware_snapshot_ids else set()) | ({'INFERENCE_SNAPSHOT'} if explicit_inference_snapshot_ids else set())
        if ai_mode != 'DISABLED' or not mapping_inputs or sources != expected_sources:
            raise ValueError('Explicit mapping source partition requires AI-disabled matching plugins')
        from apps.inspections.services.inference_freeze import freeze_exact_mapping_inputs
        frozen_input = freeze_exact_mapping_inputs(explicit_hardware_snapshot_ids or [], explicit_inference_snapshot_ids,
            environment_id=environment.pk, provenance=mapping_inputs, as_of=as_of)
        parts = frozen_input.get('sources', {frozen_input['source_type']: frozen_input})
        exact_assets = sorted(asset for part in parts.values() for asset in part['snapshots'])
        from apps.assets.models import Asset
        exact_rows = list(Asset.objects.filter(pk__in=exact_assets, environment=environment))
        kind_resource = {'HOST': 'HOST', 'GPU': 'GPU_POOL', 'LLM_INSTANCE': 'LLM_RUNTIME'}
        if len(exact_rows) != len(exact_assets) or any(kind_resource.get(asset.asset_type) not in requested_codes for asset in exact_rows):
            raise ValueError('Explicit mapping asset kind is outside requested resource scope')
        resolved_snapshot['asset_ids'] = exact_assets
        resolved_snapshot['asset_count'] = len(exact_assets)
        resolved_snapshot['resource_asset_ids'] = {
            resource.code: sorted(str(asset.pk) for asset in exact_rows if kind_resource[asset.asset_type] == resource.code)
            for resource in ResourceType.objects.filter(code__in=scope.resource_type_codes)
        }
    elif explicit_hardware_snapshot_ids is not None:
        if sources != {'HARDWARE_SNAPSHOT'} or ai_mode != 'DISABLED' or not mapping_inputs:
            raise ValueError('Explicit mapping inputs require hardware-only AI-disabled run')
        from apps.inspections.services.inference_freeze import freeze_exact_hardware_inputs
        frozen_input = freeze_exact_hardware_inputs(explicit_hardware_snapshot_ids, environment_id=environment.pk, provenance=mapping_inputs, as_of=as_of)
        exact_assets = sorted(frozen_input['snapshots'])
        # Legacy resource discovery can exclude hardware-ingest asset types.
        # This branch admits ONLY the already verified batch-owned snapshot IDs,
        # with exact environment and canonical HOST/GPU resource-kind matching.
        from apps.assets.models import Asset
        exact_rows = list(Asset.objects.filter(pk__in=exact_assets, environment=environment))
        kind_resource = {'HOST': 'HOST', 'GPU': 'GPU_POOL'}
        if len(exact_rows) != len(exact_assets) or any(kind_resource.get(asset.asset_type) not in requested_codes for asset in exact_rows):
            raise ValueError('Explicit hardware asset kind is outside requested resource scope')
        resolved_snapshot['asset_ids'] = exact_assets
        resolved_snapshot['asset_count'] = len(exact_assets)
        resolved_snapshot['resource_asset_ids'] = {
            resource.code: sorted(str(asset.pk) for asset in exact_rows if kind_resource[asset.asset_type] == resource.code)
            for resource in ResourceType.objects.filter(code__in=scope.resource_type_codes)
        }
    run = InspectionRun.objects.create(
        environment=environment,
        dataset=None,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=InspectionRun.Status.PENDING,
        total_items=len(scope.inspection_item_ids),
        config_snapshot={
            "requested_scope": {"resource_types": requested_codes},
            "resolved_scope": resolved_snapshot,
            "input": frozen_input if frozen_input is not None else freeze_external_inputs(scope.asset_ids, sources=sources, as_of=as_of),
            **({"mapping_inputs": mapping_inputs} if mapping_inputs is not None else {}),
            "trigger_options": {"ai_mode": ai_mode},
        },
    )
    InspectionItemRun.objects.bulk_create(
        [
            InspectionItemRun(
                inspection_run=run,
                inspection_item=item,
                asset_scope=resolve_item_asset_scope(run, item) or {},
            )
            for item in items
        ]
    )
    append_run_event(
        run,
        "scope.resolved",
        "PENDING",
        {
            "resource_types": list(scope.resource_type_codes),
            "inspection_item_count": len(scope.inspection_item_ids),
            "asset_count": scope.asset_count,
        },
    )
    append_run_event(
        run,
        "assets.discovered",
        "PENDING",
        {"asset_count": scope.asset_count},
    )
    return run


def _requested_codes(values):
    if not isinstance(values, list):
        raise ValueError("scope.resource_types must be a list")
    codes = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("scope.resource_types must contain non-empty strings")
        code = value.strip().upper()
        if code not in codes:
            codes.append(code)
    if not codes:
        raise ValueError("scope.resource_types must contain at least one resource type")
    return codes


__all__ = ["AI_MODES", "create_manual_inspection_run"]
