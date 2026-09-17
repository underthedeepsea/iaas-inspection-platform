"""Token-protected bounded query endpoints used by the internal REST plugin."""

from __future__ import annotations

import logging
import os
import re
import secrets
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import Avg, Count, Max, Min, Q
from django.http import JsonResponse

from apps.api.http import APIRequestError, api_error, parse_json_object, parse_positive_int
from apps.assets.models import Asset
from apps.inspections.models import MockDataset, MockEvent, MockLog, MockMetric


logger = logging.getLogger(__name__)
MAX_QUERY_ROWS = 100
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[\W_]*key|access[\W_]*key|token|secret|password|passwd|credential|authorization|cookie|private[\W_]*key|raw|provider|model|endpoint|url|uri|payload)"
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:[A-Za-z][A-Za-z0-9+.-]*://|\b(?:api[_ -]?key|password|passwd|token|secret|authorization)\s*(?:=|:)|bearer\s+)"
)


def metrics(request):
    if not _authorized(request):
        return _forbidden()
    if request.method != "POST":
        return _method("metric query")
    try:
        payload = parse_json_object(request)
        dataset = _dataset(payload.get("dataset_id"))
        limit = _limit(payload.get("limit"))
        queryset = _metric_queryset(dataset, payload)
        aggregation = payload.get("aggregation", "raw")
        if aggregation == "avg":
            values = list(
                queryset.values("asset__external_key", "metric_name")
                .annotate(
                    value=Avg("value"),
                    sample_count=Count("id"),
                    start_at=Min("ts"),
                    end_at=Max("ts"),
                )
                .order_by("metric_name", "asset__external_key")[:limit]
            )
            items = [
                {
                    "asset_id": _safe_text(row["asset__external_key"], 192),
                    "metric_name": _safe_text(row["metric_name"], 192),
                    "value": row["value"],
                    "sample_count": row["sample_count"],
                    "start_time": row["start_at"].isoformat() if row["start_at"] else None,
                    "end_time": row["end_at"].isoformat() if row["end_at"] else None,
                }
                for row in values
            ]
        elif aggregation in {"raw", "min", "max", "sum", "latest"}:
            rows = list(queryset.order_by("ts", "id")[:limit])
            items = [_metric_row(row) for row in rows]
        else:
            raise APIRequestError("VALIDATION_ERROR", "aggregation is invalid")
    except APIRequestError as error:
        return _request_error(error)
    except MockDataset.DoesNotExist:
        return _not_found("mock dataset")
    except Exception:
        logger.exception("internal metric query failed")
        return api_error("INTERNAL_ERROR", "metric query failed", status=500)
    return JsonResponse({"dataset_id": str(dataset.pk), "items": items, "count": len(items)})


def logs(request):
    if not _authorized(request):
        return _forbidden()
    if request.method != "POST":
        return _method("log query")
    try:
        payload = parse_json_object(request)
        dataset = _dataset(payload.get("dataset_id"))
        limit = _limit(payload.get("limit"))
        queryset = MockLog.objects.filter(dataset=dataset)
        queryset = _apply_asset_filter(queryset, payload.get("asset_ids"))
        queryset = _apply_time_filter(queryset, payload)
        sources = _string_list(payload.get("sources", []), "sources")
        if sources:
            queryset = queryset.filter(source__in=sources)
        query = payload.get("query")
        if query is not None:
            if not isinstance(query, str) or len(query) > 512:
                raise APIRequestError("VALIDATION_ERROR", "query is invalid")
            queryset = queryset.filter(message__icontains=query)
        rows = queryset.order_by("-ts", "-id")[:limit]
        items = [_log_row(row) for row in rows]
    except APIRequestError as error:
        return _request_error(error)
    except MockDataset.DoesNotExist:
        return _not_found("mock dataset")
    except Exception:
        logger.exception("internal log query failed")
        return api_error("INTERNAL_ERROR", "log query failed", status=500)
    return JsonResponse({"dataset_id": str(dataset.pk), "items": items, "count": len(items)})


def events(request):
    if not _authorized(request):
        return _forbidden()
    if request.method != "POST":
        return _method("event query")
    try:
        payload = parse_json_object(request)
        dataset = _dataset(payload.get("dataset_id"))
        limit = _limit(payload.get("limit"))
        queryset = MockEvent.objects.filter(dataset=dataset)
        queryset = _apply_asset_filter(queryset, payload.get("asset_ids"))
        queryset = _apply_time_filter(queryset, payload)
        requested_event_types = payload.get("event_types", [])
        if "event_type" in payload and "event_types" not in payload:
            requested_event_types = [payload["event_type"]]
        event_types = _string_list(requested_event_types, "event_types")
        if event_types:
            queryset = queryset.filter(event_type__in=event_types)
        rows = queryset.order_by("-ts", "-id")[:limit]
        items = [_event_row(row) for row in rows]
    except APIRequestError as error:
        return _request_error(error)
    except MockDataset.DoesNotExist:
        return _not_found("mock dataset")
    except Exception:
        logger.exception("internal event query failed")
        return api_error("INTERNAL_ERROR", "event query failed", status=500)
    return JsonResponse({"dataset_id": str(dataset.pk), "items": items, "count": len(items)})


def topology(request):
    if not _authorized(request):
        return _forbidden()
    if request.method != "POST":
        return _method("topology query")
    try:
        payload = parse_json_object(request)
        dataset = _dataset(payload.get("dataset_id"))
        limit = _limit(payload.get("limit"))
        asset_ids = payload.get("asset_ids")
        if asset_ids is not None:
            asset_ids = _string_list(asset_ids, "asset_ids")
        queryset = Asset.objects.filter(environment=dataset.environment)
        if asset_ids:
            queryset = queryset.filter(_topology_asset_q(asset_ids))
        else:
            dataset_asset_ids = set(
                MockMetric.objects.filter(dataset=dataset).values_list("asset_id", flat=True)
            )
            dataset_asset_ids.update(
                MockLog.objects.filter(dataset=dataset).values_list("asset_id", flat=True)
            )
            dataset_asset_ids.update(
                MockEvent.objects.filter(dataset=dataset, asset_id__isnull=False).values_list("asset_id", flat=True)
            )
            queryset = queryset.filter(pk__in=dataset_asset_ids)
        rows = queryset.order_by("external_key")[:limit]
        items = [_asset_row(row) for row in rows]
    except APIRequestError as error:
        return _request_error(error)
    except MockDataset.DoesNotExist:
        return _not_found("mock dataset")
    except Exception:
        logger.exception("internal topology query failed")
        return api_error("INTERNAL_ERROR", "topology query failed", status=500)
    return JsonResponse({"dataset_id": str(dataset.pk), "items": items, "count": len(items)})


def _authorized(request):
    configured = None
    for name in (
        "MOCK_INTERNAL_TOKEN",
        "MOCKDATA_INTERNAL_TOKEN",
        "INTERNAL_MOCK_TOKEN",
        "INTERNAL_TOKEN",
    ):
        candidate = getattr(settings, name, None) or os.getenv(name)
        if candidate:
            configured = candidate
            break
    supplied = request.META.get("HTTP_X_INTERNAL_TOKEN")
    return (
        isinstance(configured, str)
        and bool(configured)
        and isinstance(supplied, str)
        and bool(supplied)
        and secrets.compare_digest(supplied, configured)
    )


def _dataset(value):
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise APIRequestError("VALIDATION_ERROR", "dataset_id must be a UUID") from None
    return MockDataset.objects.select_related("environment").get(pk=parsed)


def _metric_queryset(dataset, payload):
    queryset = MockMetric.objects.filter(dataset=dataset)
    queryset = _apply_asset_filter(queryset, payload.get("asset_ids"))
    metric_names = _string_list(payload.get("metric_names", []), "metric_names")
    if metric_names:
        queryset = queryset.filter(metric_name__in=metric_names)
    return _apply_time_filter(queryset, payload)


def _apply_asset_filter(queryset, value):
    if value is None:
        return queryset
    asset_ids = _string_list(value, "asset_ids")
    return queryset.filter(_asset_q(asset_ids))


def _asset_q(asset_ids):
    external_keys = []
    primary_keys = []
    for value in asset_ids:
        external_keys.append(value)
        try:
            primary_keys.append(uuid.UUID(value))
        except ValueError:
            pass
    return Q(asset__external_key__in=external_keys) | Q(asset_id__in=primary_keys)


def _topology_asset_q(asset_ids):
    external_keys = []
    primary_keys = []
    for value in asset_ids:
        external_keys.append(value)
        try:
            primary_keys.append(uuid.UUID(value))
        except ValueError:
            pass
    return Q(external_key__in=external_keys) | Q(pk__in=primary_keys)


def _apply_time_filter(queryset, payload):
    start = _datetime(payload["start_time"], "start_time") if payload.get("start_time") is not None else None
    end = _datetime(payload["end_time"], "end_time") if payload.get("end_time") is not None else None
    if start is not None and end is not None and start > end:
        raise APIRequestError("VALIDATION_ERROR", "start_time must be before end_time")
    if start is not None:
        queryset = queryset.filter(ts__gte=start)
    if end is not None:
        queryset = queryset.filter(ts__lte=end)
    return queryset


def _datetime(value, field):
    if not isinstance(value, str):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO datetime") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _limit(value):
    try:
        return parse_positive_int(value, default=50, maximum=MAX_QUERY_ROWS)
    except APIRequestError as error:
        raise error


def _string_list(value, field):
    if not isinstance(value, list) or len(value) > MAX_QUERY_ROWS or any(
        not isinstance(item, str) or not item.strip() or len(item.strip()) > 192 for item in value
    ):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a bounded string list")
    return [item.strip() for item in value]


def _metric_row(row):
    return {
        "id": row.pk,
        "asset_id": _safe_text(row.asset.external_key, 192),
        "metric_name": _safe_text(row.metric_name, 192),
        "timestamp": row.ts.isoformat(),
        "value": row.value,
    }


def _log_row(row):
    return {
        "id": row.pk,
        "asset_id": _safe_text(row.asset.external_key, 192),
        "timestamp": row.ts.isoformat(),
        "source": _safe_text(row.source, 192),
        "level": _safe_text(row.level, 64),
        "message": _safe_text(row.message, 2000),
    }


def _event_row(row):
    return {
        "id": row.pk,
        "asset_id": _safe_text(row.asset.external_key, 192) if row.asset_id else None,
        "timestamp": row.ts.isoformat(),
        "event_type": _safe_text(row.event_type, 192),
        "reason": _safe_text(row.reason, 2000),
        "message": _safe_text(row.message, 2000),
    }


def _asset_row(row):
    return {
        "asset_id": _safe_text(row.external_key, 192),
        "asset_type": _safe_text(row.asset_type, 128),
        "name": _safe_text(row.name, 255),
        "parent_id": _safe_text(row.parent.external_key, 192) if row.parent_id else None,
        "labels": _safe_mapping(row.labels),
        "topology": _safe_mapping(row.topology),
    }


def _safe_text(value, limit):
    if not isinstance(value, str):
        return ""
    if _SENSITIVE_TEXT_RE.search(value):
        return "[redacted]"
    return value[:limit]


def _safe_mapping(value, depth=0):
    if depth > 3:
        return {}
    if isinstance(value, Mapping):
        result = {}
        for key, item in list(value.items())[:32]:
            key = str(key)[:128]
            if _SENSITIVE_KEY_RE.search(key):
                continue
            result[key] = _safe_mapping(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_mapping(item, depth + 1) for item in value[:32]]
    if isinstance(value, str):
        return _safe_text(value, 512)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _request_error(error):
    return api_error(error.code, error.message, status=error.status, details=error.details)


def _forbidden():
    return api_error("PERMISSION_DENIED", "a valid X-Internal-Token is required", status=403)


def _not_found(resource):
    return api_error("NOT_FOUND", f"the requested {resource} does not exist", status=404)


def _method(resource):
    return api_error("METHOD_NOT_ALLOWED", f"{resource} method is not allowed", status=405)


metrics_query = metrics
logs_search = logs
events_query = events
topology_query = topology


__all__ = [
    "events",
    "events_query",
    "logs",
    "logs_search",
    "metrics",
    "metrics_query",
    "topology",
    "topology_query",
]
