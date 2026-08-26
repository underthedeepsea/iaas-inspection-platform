from dataclasses import dataclass

from apps.assets.models import Asset
from apps.inspections.models import InspectionItemResourceType, ResourceType
from apps.inspections.services.resource_types import resolve_inspection_items


class UnknownResourceType(ValueError):
    pass


class UnsupportedAssetSelector(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedInspectionScope:
    resource_type_codes: tuple[str, ...]
    inspection_item_ids: tuple
    asset_ids: tuple
    asset_count: int


def resolve_scope(*, environment_id, resource_type_codes):
    codes = _normalized_codes(resource_type_codes)
    resource_types = list(
        ResourceType.objects.filter(code__in=codes, enabled=True).order_by("code", "pk")
    )
    found_codes = {resource_type.code for resource_type in resource_types}
    missing = sorted(set(codes) - found_codes)
    if missing:
        raise UnknownResourceType(", ".join(missing))

    asset_types = set()
    for resource_type in resource_types:
        selector = resource_type.asset_selector or {}
        unsupported = set(selector) - {"asset_types"}
        if unsupported:
            raise UnsupportedAssetSelector(
                f"{resource_type.code} contains unsupported keys: {sorted(unsupported)}"
            )
        selected_types = selector.get("asset_types", [])
        if not isinstance(selected_types, list) or any(
            not isinstance(asset_type, str) for asset_type in selected_types
        ):
            raise UnsupportedAssetSelector(
                f"{resource_type.code}.asset_selector.asset_types must be a string list"
            )
        unknown_types = set(selected_types) - set(Asset.AssetType.values)
        if unknown_types:
            raise UnsupportedAssetSelector(
                f"{resource_type.code} contains unknown asset types: {sorted(unknown_types)}"
            )
        asset_types.update(selected_types)

    item_ids = tuple(
        sorted(
            set(resolve_inspection_items(list(codes)).values_list("id", flat=True)),
            key=str,
        )
    )
    asset_ids = tuple(
        sorted(
            set(
                Asset.objects.filter(
                    environment_id=environment_id,
                    status=Asset.Status.ACTIVE,
                    asset_type__in=sorted(asset_types),
                ).values_list("id", flat=True)
            ),
            key=str,
        )
    )
    return ResolvedInspectionScope(
        resource_type_codes=tuple(codes),
        inspection_item_ids=item_ids,
        asset_ids=asset_ids,
        asset_count=len(asset_ids),
    )


def scope_to_snapshot(scope: ResolvedInspectionScope):
    return {
        "resource_types": list(scope.resource_type_codes),
        "inspection_item_ids": [str(value) for value in scope.inspection_item_ids],
        "asset_ids": [str(value) for value in scope.asset_ids],
        "asset_count": scope.asset_count,
    }


def resolve_item_asset_scope(inspection_run, inspection_item):
    """Resolve the frozen assets applicable to one bound inspection item."""

    resolved = (inspection_run.config_snapshot or {}).get("resolved_scope")
    if not isinstance(resolved, dict) or "asset_ids" not in resolved:
        return None
    selected_codes = list(resolved.get("resource_types") or [])
    bindings = list(
        InspectionItemResourceType.objects.filter(
            inspection_item=inspection_item,
            enabled=True,
            resource_type__enabled=True,
            resource_type__code__in=selected_codes,
        )
        .select_related("resource_type")
        .order_by("resource_type__sort_order", "resource_type__code", "resource_type_id")
    )
    bindings_by_code = {binding.resource_type.code: binding for binding in bindings}
    item_resource_types = [code for code in selected_codes if code in bindings_by_code]
    asset_types = set()
    for code in item_resource_types:
        selector = bindings_by_code[code].resource_type.asset_selector or {}
        asset_types.update(selector.get("asset_types") or [])

    frozen_ids = [str(value) for value in resolved.get("asset_ids") or []]
    assets = list(
        Asset.objects.filter(
            environment_id=inspection_run.environment_id,
            status=Asset.Status.ACTIVE,
            id__in=frozen_ids,
            asset_type__in=sorted(asset_types),
        ).order_by("external_key", "pk")
    )
    asset_by_id = {str(asset.pk): asset for asset in assets}
    ordered_assets = [asset_by_id[asset_id] for asset_id in frozen_ids if asset_id in asset_by_id]
    return {
        "asset_ids": [str(asset.pk) for asset in ordered_assets],
        "asset_keys": [asset.external_key for asset in ordered_assets],
        "resource_types": item_resource_types,
    }


def _normalized_codes(values):
    if not isinstance(values, (list, tuple, set)):
        raise UnknownResourceType("resource_types must be a list")
    codes = sorted({str(value).strip().upper() for value in values if str(value).strip()})
    if not codes:
        raise UnknownResourceType("at least one resource type is required")
    return codes


__all__ = [
    "ResolvedInspectionScope",
    "UnknownResourceType",
    "UnsupportedAssetSelector",
    "resolve_item_asset_scope",
    "resolve_scope",
    "scope_to_snapshot",
]
