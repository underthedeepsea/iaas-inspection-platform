from __future__ import annotations

from functools import wraps

from django.utils import timezone

from django.http import JsonResponse

from apps.api.http import APIRequestError, api_error, parse_json_object

from .models import InferencePerformanceSnapshot
from .schemas import parse_batch_snapshot_request, parse_snapshot_request
from .services.ingest import ingest_batch, ingest_snapshot, resolve_environment


def _boundary(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except APIRequestError as error:
            status = getattr(error, 'status', 400)
            if error.code == 'ENVIRONMENT_NOT_FOUND':
                status = 404
            return api_error(error.code, error.message, status=status, details=error.details)
        except Exception:
            return api_error("INTERNAL_ERROR", "the request could not be completed", status=500)
    return wrapped


def _endpoint(*methods):
    accepted = frozenset(methods)
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in accepted:
                return api_error("METHOD_NOT_ALLOWED", f"this endpoint only accepts {'/'.join(sorted(accepted))}", status=405)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def _current_status(evaluation: dict, freshness: dict) -> str:
    if freshness['state'] != 'FRESH':
        return 'UNKNOWN'
    plugin = evaluation.get('plugin') or {}
    if plugin.get('id') != 'inference-performance' or plugin.get('version') != '1.0.0':
        return 'UNKNOWN'
    status = evaluation.get('status')
    if status in {'WARNING', 'CRITICAL', 'ERROR'}:
        return status
    quality = evaluation.get('quality') or {}
    if status == 'NORMAL' and quality.get('state') == 'READY' and not quality.get('pending_confirmation'):
        return 'NORMAL'
    return 'UNKNOWN'


def serialize_profile(snapshot: InferencePerformanceSnapshot) -> dict:
    evaluation = snapshot.evaluation or {}
    age_seconds = max(0, (timezone.now() - snapshot.window_end).total_seconds())
    max_age = int((evaluation.get('resolved_policy') or {}).get('quality', {}).get('max_age_seconds', 300))
    freshness = {'state': 'FRESH' if age_seconds <= max_age else 'STALE', 'age_seconds': age_seconds,
                 'max_age_seconds': max_age}
    current_status = _current_status(evaluation, freshness)
    return {
        "snapshot_id": str(snapshot.id),
        "engine": {"engine_id": snapshot.engine_id, "engine_type": snapshot.engine_type, "model_name": snapshot.model_name},
        "window": {"start": snapshot.window_start.isoformat(), "end": snapshot.window_end.isoformat()},
        "status": current_status, "evaluation_status": evaluation.get('status', 'UNKNOWN'),
        "freshness": freshness, "plugin": evaluation.get('plugin', {}), "quality": evaluation.get('quality', {}),
        "current_metrics": snapshot.metrics,
        "fixed": evaluation.get("fixed", {}), "dynamic": evaluation.get("dynamic", {}),
        "trend": evaluation.get("trend", {}), "policy_source": evaluation.get("policy_source", {}),
        "reasons": evaluation.get("reasons", []),
    }


@_boundary
@_endpoint("POST")
def snapshots(request):
    snapshot, created = ingest_snapshot(parse_snapshot_request(parse_json_object(request)))
    return JsonResponse({"created": created, "profile": serialize_profile(snapshot)}, status=201 if created else 200)


@_boundary
@_endpoint("POST")
def snapshots_batch(request):
    snapshots, evaluated, created_count = ingest_batch(parse_batch_snapshot_request(parse_json_object(request)))
    return JsonResponse({
        "count": len(snapshots), "created_count": created_count,
        "evaluated": serialize_profile(evaluated) if evaluated else None,
    }, status=201)


@_boundary
@_endpoint("GET")
def engine_profile(request, engine_id: str):
    environment_id = request.GET.get("environment_id")
    if not environment_id:
        raise APIRequestError("VALIDATION_ERROR", "environment_id is required", details={"field": "environment_id"})
    environment = resolve_environment(environment_id)
    snapshots = InferencePerformanceSnapshot.objects.filter(environment=environment)
    if engine_id != "latest":
        snapshots = snapshots.filter(engine_id=engine_id)
    engine_type = request.GET.get('engine_type')
    model_name = request.GET.get('model_name')
    if engine_type:
        snapshots = snapshots.filter(engine_type=engine_type)
    if model_name:
        snapshots = snapshots.filter(model_name=model_name)
    if engine_id != 'latest' and (not engine_type or not model_name):
        identities = list(snapshots.values_list('engine_type', 'model_name').distinct()[:2])
        if len(identities) > 1:
            return api_error('AMBIGUOUS_ENGINE', 'engine identity needs engine_type and model_name', status=409)
    snapshot = snapshots.order_by("-window_end", "-pk").first()
    if snapshot is None:
        return api_error("ENGINE_PERFORMANCE_NOT_FOUND", "engine performance profile does not exist", status=404)
    return JsonResponse(serialize_profile(snapshot))


@_boundary
@_endpoint('GET')
def engines(request):
    environment_id = request.GET.get('environment_id')
    if not environment_id:
        raise APIRequestError('VALIDATION_ERROR', 'environment_id is required', details={'field': 'environment_id'})
    environment = resolve_environment(environment_id)
    rows = InferencePerformanceSnapshot.objects.filter(environment=environment).order_by('engine_id', 'engine_type', 'model_name').values(
        'engine_id', 'engine_type', 'model_name').distinct()
    return JsonResponse({'engines': list(rows)})
