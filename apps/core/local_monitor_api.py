"""Strict HTTP boundary for the fixed synthetic monitor only."""
from functools import wraps
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from apps.api.http import APIRequestError, api_error, parse_json_object
from . import local_monitor_services as service
from .models import Environment


def boundary(method):
    def decorate(view):
        @wraps(view)
        def guarded(request):
            try:
                if request.method != method:
                    return api_error("METHOD", "Method not allowed.", status=405)
                if method == "GET":
                    if any(len(request.GET.getlist(k)) != 1 for k in request.GET):
                        service.invalid("Repeated query fields.")
                    data = request.GET.dict()
                else:
                    if request.GET:
                        service.invalid("Use only the JSON body.")
                    if request.content_type != "application/json":
                        return api_error("JSON_REQUIRED", "JSON is required.", status=415)
                    length = request.META.get("CONTENT_LENGTH", "0") or "0"
                    if not length.isdigit() or int(length) > 65536 or len(request.body) > 65536:
                        return api_error("BODY_LIMIT", "Request body exceeds the limit.", status=413)
                    data = parse_json_object(request)
                return JsonResponse(view(data))
            except service.store.MappingScopeError:
                return api_error("MOCK_SCOPE", "Only the registered active MOCK scope is allowed.", status=403)
            except Environment.DoesNotExist:
                return api_error("NOT_FOUND", "Mock environment was not found.", status=404)
            except (APIRequestError, service.store.MappingInputError, ValidationError, ValueError, TypeError, UnicodeError):
                return api_error("INVALID_INPUT", "Invalid or unsupported synthetic request.", status=400)
            except DatabaseError:
                return api_error("STORAGE_UNAVAILABLE", "Mock environment storage is unavailable.", status=503)
        return guarded
    return decorate


@boundary("GET")
def endpoint_metric(data):
    return service.discover(data)


@boundary("POST")
def batch_endpoint_counter(data):
    return service.describe(data)


@boundary("GET")
def data(data):
    return service.data_response(data, query=True)


@boundary("POST")
def batch_data(data):
    return service.data_response(data, batch=True)
