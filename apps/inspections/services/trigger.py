from django.db import transaction
from django.utils import timezone

from apps.inspections.models import InspectionItem, InspectionItemRun, InspectionRun
from apps.inspections.services.events import append_run_event
from apps.inspections.services.scope import resolve_scope, scope_to_snapshot


AI_MODES = {"DEFERRED", "DISABLED"}


@transaction.atomic
def create_manual_inspection_run(*, environment, resource_type_codes, ai_mode="DEFERRED"):
    if ai_mode not in AI_MODES:
        raise ValueError("ai_mode must be DEFERRED or DISABLED")
    requested_codes = _requested_codes(resource_type_codes)
    scope = resolve_scope(
        environment_id=environment.pk,
        resource_type_codes=requested_codes,
    )
    resolved_snapshot = scope_to_snapshot(scope)
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=timezone.localdate(),
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=InspectionRun.Status.PENDING,
        total_items=len(scope.inspection_item_ids),
        config_snapshot={
            "requested_scope": {"resource_types": requested_codes},
            "resolved_scope": resolved_snapshot,
            "trigger_options": {"ai_mode": ai_mode},
        },
    )
    items = InspectionItem.objects.filter(id__in=scope.inspection_item_ids).order_by("code", "created_at", "pk")
    InspectionItemRun.objects.bulk_create(
        [
            InspectionItemRun(
                inspection_run=run,
                inspection_item=item,
                asset_scope={
                    "asset_ids": [str(asset_id) for asset_id in scope.asset_ids],
                    "resource_types": list(scope.resource_type_codes),
                },
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
