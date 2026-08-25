def serialize_manual_inspection_run(run):
    snapshot = run.config_snapshot or {}
    requested = snapshot.get("requested_scope") or {}
    resolved = snapshot.get("resolved_scope") or {}
    return {
        "id": str(run.pk),
        "inspection_run_id": str(run.pk),
        "status": run.status,
        "trigger_type": run.trigger_type,
        "scope": {
            "resource_types": list(requested.get("resource_types") or resolved.get("resource_types") or []),
            "asset_count": int(resolved.get("asset_count") or 0),
            "inspection_item_count": run.total_items,
        },
    }


__all__ = ["serialize_manual_inspection_run"]
