from __future__ import annotations

from functools import wraps

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
            status = 404 if error.code == "ENVIRONMENT_NOT_FOUND" else 400
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


def serialize_profile(snapshot: InferencePerformanceSnapshot) -> dict:
    evaluation = snapshot.evaluation or {}
    return {
        "snapshot_id": str(snapshot.id),
        "engine": {"engine_id": snapshot.engine_id, "engine_type": snapshot.engine_type, "model_name": snapshot.model_name},
        "window": {"start": snapshot.window_start.isoformat(), "end": snapshot.window_end.isoformat()},
        "status": evaluation.get("status", "UNKNOWN"), "current_metrics": snapshot.metrics,
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
    snapshot = snapshots.order_by("-window_end", "-pk").first()
    if snapshot is None:
        return api_error("ENGINE_PERFORMANCE_NOT_FOUND", "engine performance profile does not exist", status=404)
    return JsonResponse(serialize_profile(snapshot))
