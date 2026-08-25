from dataclasses import dataclass

from apps.assets.models import Asset
from apps.inspections.models import ResourceType
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
    "resolve_scope",
    "scope_to_snapshot",
]
