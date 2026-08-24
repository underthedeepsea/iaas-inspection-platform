"""Authenticated, bounded public Mock Dataset API."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from collections.abc import Mapping

from django.db import IntegrityError, transaction
from django.http import JsonResponse

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_json_object
from apps.api.pagination import paginate
from apps.audits.services import record_event
from apps.core.models import Environment
from apps.inspections.models import MockDataset
from .services import generate_and_persist


logger = logging.getLogger(__name__)
_MAX_CONFIG_KEYS = {"host_count", "duration_minutes"}


def generate(request):
    auth_error = require_role(request, "operator")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _method("mock dataset generation")
    try:
        payload = parse_json_object(request)
        environment_id = _uuid(payload.get("environment_id"), "environment_id")
        scenario = _text(payload.get("scenario"), "scenario", 64)
        dataset_date = _date(payload.get("dataset_date", payload.get("business_date")), "dataset_date")
        seed = _seed(payload.get("seed"))
        config = _config(payload.get("config", {}))
        with transaction.atomic():
            try:
                environment = Environment.objects.select_for_update().get(pk=environment_id)
            except Environment.DoesNotExist:
                return _not_found("environment")
            # The generator is a fixed, deterministic service; HTTP never supplies code.
            dataset = generate_and_persist(environment, seed, scenario, dataset_date)
            if config:
                stored = dict(dataset.generator_config or {})
                stored["config"] = config
                dataset.generator_config = stored
                dataset.save(update_fields=["generator_config"])
            record_event(
                actor=request.user,
                environment=environment,
                event_type="mock_dataset.generated",
                object_type="MockDataset",
                object_id=dataset.pk,
                payload={
                    "capability_id": "mockdata.generator",
                    "version": dataset.version,
                },
            )
    except APIRequestError as error:
        return _request_error(error)
    except ValueError as error:
        return api_error("VALIDATION_ERROR", str(error), status=400)
    except IntegrityError:
        return api_error("CONFLICT", "the mock dataset could not be persisted", status=409)
    except Exception:
        logger.exception("mock dataset generation failed")
        return api_error("INTERNAL_ERROR", "the mock dataset could not be generated", status=500)
    return JsonResponse(serialize_dataset(dataset), status=201)


def collection(request):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _method("mock datasets")
    queryset = MockDataset.objects.select_related("environment").all()
    if request.GET.get("environment_id"):
        try:
            environment_id = _uuid(request.GET["environment_id"], "environment_id")
        except APIRequestError as error:
            return _request_error(error)
        queryset = queryset.filter(environment_id=environment_id)
    if request.GET.get("scenario"):
        queryset = queryset.filter(scenario=request.GET["scenario"].strip())
    if request.GET.get("status"):
        queryset = queryset.filter(status=request.GET["status"].strip().upper())
    queryset = queryset.order_by("-dataset_date", "-created_at", "-pk")
    return paginate(queryset, request, serialize_dataset)


def detail(request, dataset_id):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _method("mock dataset detail")
    try:
        parsed = _uuid(dataset_id, "dataset_id")
        dataset = MockDataset.objects.select_related("environment").get(pk=parsed)
    except APIRequestError as error:
        return _request_error(error)
    except MockDataset.DoesNotExist:
        return _not_found("mock dataset")
    return JsonResponse(serialize_dataset(dataset))


def serialize_dataset(dataset):
    config = dict(dataset.generator_config or {})
    # Generator config is metadata only; never attach metric/log/event rows here.
    config.pop("script", None)
    config.pop("script_path", None)
    return {
        "id": str(dataset.pk),
        "dataset_id": str(dataset.pk),
        "environment_id": str(dataset.environment_id),
        "scenario": dataset.scenario,
        "dataset_date": dataset.dataset_date.isoformat(),
        "seed": dataset.seed,
        "version": dataset.version,
        "status": dataset.status,
        "generator_config": config,
        "asset_count": dataset.asset_count,
        "metric_count": dataset.metric_count,
        "log_count": dataset.log_count,
        "event_count": dataset.event_count,
        "change_count": dataset.change_count,
        "ready_at": dataset.ready_at.isoformat() if dataset.ready_at else None,
    }


def _config(value):
    if not isinstance(value, Mapping):
        raise APIRequestError("VALIDATION_ERROR", "config must be an object")
    if any(key not in _MAX_CONFIG_KEYS for key in value):
        raise APIRequestError("VALIDATION_ERROR", "config contains an unsupported key")
    result = {}
    for key, item in value.items():
        result[key] = _positive_int(item, key, 10000)
    return result


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a UUID", details={"field": field}) from None


def _date(value, field):
    if not isinstance(value, str):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO date", details={"field": field})
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an ISO date", details={"field": field}) from None


def _seed(value):
    if isinstance(value, bool):
        raise APIRequestError("VALIDATION_ERROR", "seed must be an integer", details={"field": "seed"})
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit() and str(int(value)) == value.strip():
        return int(value)
    raise APIRequestError("VALIDATION_ERROR", "seed must be an integer", details={"field": "seed"})


def _positive_int(value, field, maximum):
    if isinstance(value, bool):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit() and str(int(value)) == value.strip():
        parsed = int(value)
    else:
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a positive integer")
    if parsed < 1 or parsed > maximum:
        raise APIRequestError("VALIDATION_ERROR", f"{field} is outside the allowed range")
    return parsed


def _text(value, field, max_length):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise APIRequestError("VALIDATION_ERROR", f"{field} is invalid", details={"field": field})
    return value.strip()


def _request_error(error):
    return api_error(error.code, error.message, status=error.status, details=error.details)


def _not_found(resource):
    return api_error("NOT_FOUND", f"the requested {resource} does not exist", status=404)


def _method(resource):
    return api_error("METHOD_NOT_ALLOWED", f"{resource} method is not allowed", status=405)


datasets = collection
generate_dataset = generate


__all__ = ["collection", "datasets", "detail", "generate", "generate_dataset", "serialize_dataset"]
