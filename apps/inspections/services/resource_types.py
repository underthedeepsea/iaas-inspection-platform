from apps.inspections.models import InspectionItem, ResourceType


def get_active_resource_types(environment_id):
    """Return product resource types in their configured display order.

    ResourceType is intentionally global in v0.2; the environment argument is
    kept in the service contract so the API can evolve to tenant-specific
    catalogs without changing callers.
    """

    del environment_id
    return list(ResourceType.objects.filter(enabled=True).order_by("sort_order", "code", "pk"))


def resolve_inspection_items(resource_type_codes):
    """Resolve enabled inspection items bound to at least one requested type."""

    codes = sorted({str(code).strip().upper() for code in resource_type_codes if str(code).strip()})
    if not codes:
        return InspectionItem.objects.none()
    return (
        InspectionItem.objects.filter(
            enabled=True,
            resource_types__enabled=True,
            resource_types__resource_type__enabled=True,
            resource_types__resource_type__code__in=codes,
        )
        .distinct()
        .order_by("code", "created_at", "pk")
    )


__all__ = ["get_active_resource_types", "resolve_inspection_items"]
