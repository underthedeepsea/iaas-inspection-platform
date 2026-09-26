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
