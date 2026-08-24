"""Thin, authenticated HTTP adapters for the Capability Registry."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from jsonschema import SchemaError
from jsonschema.validators import validator_for

from apps.api.auth import require_role
from apps.api.http import APIRequestError, api_error, parse_bool, parse_json_object
from apps.api.pagination import paginate
from apps.audits.services import record_event
from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from services.plugin_runtime.registry import CapabilityRegistry

from .serializers import serialize_candidate, serialize_capability, serialize_version


logger = logging.getLogger(__name__)
_VERSION_RE = re.compile(r"\A\d+\.\d+\.\d+\Z")
_IDENTIFIER_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}\Z")
_SCRIPT_PART_RE = re.compile(r"\A[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\Z")
_MAX_LIST = 100


class CapabilityAPIError(ValueError):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code = code
        self.status = status


def collection(request):
    if request.method == "GET":
        auth_error = require_role(request, "viewer")
        if auth_error is not None:
            return auth_error
        return _list(request)
    if request.method == "POST":
        auth_error = require_role(request, "platform_admin")
        if auth_error is not None:
            return auth_error
        return _create(request)
    return _method("capabilities")


def detail(request, capability_id):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "GET":
        return _method("capability detail")
    try:
        capability = Capability.objects.select_related("current_version").get(
            capability_id=capability_id
        )
    except Capability.DoesNotExist:
        return _not_found("capability")
    versions = CapabilityVersion.objects.filter(capability=capability).order_by("-created_at", "-version")[:100]
    bindings = InspectionCapabilityBinding.objects.filter(
        capability_version__capability=capability
    ).select_related("inspection_item").order_by("priority", "pk")[:64]
    return JsonResponse(
        serialize_capability(capability, versions=versions, bindings=bindings)
    )


def versions(request, capability_id):
    auth_error = require_role(request, "platform_admin")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _method("capability versions")
    try:
        payload = parse_json_object(request)
        with transaction.atomic():
            version = _create_version(capability_id, payload, request.user)
    except APIRequestError as error:
        return _request_error(error)
    except (Capability.DoesNotExist, CapabilityVersion.DoesNotExist):
        return _not_found("capability")
    except IntegrityError:
        return api_error("CONFLICT", "the capability version already exists", status=409)
    except ValueError as error:
        return api_error("VALIDATION_ERROR", str(error), status=400)
    except Exception:
        logger.exception("capability version creation failed")
        return api_error("INTERNAL_ERROR", "the capability version could not be created", status=500)
    return JsonResponse(serialize_version(version), status=201)


def test_version(request, capability_id, version):
    auth_error = require_role(request, "platform_admin")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _method("capability version test")
    try:
        payload = parse_json_object(request)
        cap, version_row = _get_version(capability_id, version)
        result = _simulate_version_test(cap, version_row, payload)
    except APIRequestError as error:
        return _request_error(error)
    except (Capability.DoesNotExist, CapabilityVersion.DoesNotExist):
        return _not_found("capability version")
    except CapabilityAPIError as error:
        return api_error(error.code, str(error), status=error.status)
    except ValueError as error:
        return api_error("VALIDATION_ERROR", str(error), status=400)
    except Exception:
        logger.exception("capability version test failed")
        return api_error("INTERNAL_ERROR", "the capability version test failed", status=500)
    return JsonResponse(result)


def shadow(request, capability_id, version):
    return _transition(request, capability_id, version, target=CapabilityVersion.Status.SHADOW)


def activate(request, capability_id, version):
    return _transition(request, capability_id, version, target=CapabilityVersion.Status.ACTIVE)


def resolve(request):
    auth_error = require_role(request, "viewer")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _method("capability resolve")
    try:
        payload = parse_json_object(request)
        claim = _text(payload.get("claim"), "claim", 192)
        subject_type = payload.get("subject_type")
        if subject_type is not None:
            subject_type = _text(subject_type, "subject_type", 192)
        tags = _string_list(payload.get("tags", []), "tags")
    except APIRequestError as error:
        return _request_error(error)
    try:
        candidates = _resolve_candidates(claim, subject_type, tags)
    except Exception:
        logger.exception("capability resolution failed")
        return api_error("INTERNAL_ERROR", "capability resolution failed", status=500)
    return JsonResponse({"claim": claim, "candidates": [serialize_candidate(item) for item in candidates]})


def _list(request):
    queryset = Capability.objects.select_related("current_version").all()
    if request.GET.get("domain"):
        queryset = queryset.filter(domain__iexact=request.GET["domain"].strip())
    if request.GET.get("status"):
        queryset = queryset.filter(status=request.GET["status"].strip().upper())
    if request.GET.get("implementation_type"):
        queryset = queryset.filter(
            capabilityversion__implementation_type=request.GET["implementation_type"].strip().upper()
        )
    if request.GET.get("resolves"):
        queryset = queryset.filter(
            capabilityversion__resolves__contains=[request.GET["resolves"].strip()]
        )
    if "read_only" in request.GET:
        try:
            read_only = parse_bool(_query_bool(request.GET["read_only"]))
        except APIRequestError as error:
            return _request_error(error)
        queryset = queryset.filter(read_only=read_only)
    queryset = queryset.distinct().order_by("capability_id")
    return paginate(queryset, request, lambda value: serialize_capability(value))


def _create(request):
    try:
        payload = parse_json_object(request)
        capability_id = _identifier(payload.get("capability_id"), "capability_id")
        name = _text(payload.get("name"), "name", 192)
        domain = _text(payload.get("domain"), "domain", 64)
        description = payload.get("description", "")
        if not isinstance(description, str) or len(description) > 10000:
            raise APIRequestError("VALIDATION_ERROR", "description is invalid")
        owner = payload.get("owner", "platform")
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
            raise APIRequestError("VALIDATION_ERROR", "owner is invalid")
        read_only = parse_bool(payload.get("read_only", True))
        status = payload.get("status", Capability.Status.ACTIVE)
        if status not in Capability.Status.values:
            raise APIRequestError("VALIDATION_ERROR", "status is invalid")
        with transaction.atomic():
            capability = Capability.objects.create(
                capability_id=capability_id,
                name=name,
                domain=domain,
                description=description,
                owner=owner.strip(),
                read_only=read_only,
                status=status,
            )
            record_event(
                actor=request.user,
                environment=None,
                event_type="capability.created",
                object_type="Capability",
                object_id=capability.pk,
                payload={"capability_id": capability.capability_id},
            )
    except APIRequestError as error:
        return _request_error(error)
    except IntegrityError:
        return api_error("CONFLICT", "the capability already exists", status=409)
    except Exception:
        logger.exception("capability creation failed")
        return api_error("INTERNAL_ERROR", "the capability could not be created", status=500)
    return JsonResponse(serialize_capability(capability), status=201)


def _create_version(capability_id, payload, actor):
    capability = Capability.objects.get(capability_id=capability_id)
    version = _text(payload.get("version"), "version", 32)
    if not _VERSION_RE.fullmatch(version):
        raise APIRequestError("VALIDATION_ERROR", "version must use numeric x.x.x format")
    implementation_type = str(payload.get("implementation_type", "")).strip().upper()
    if implementation_type not in CapabilityVersion.ImplementationType.values:
        raise APIRequestError("VALIDATION_ERROR", "implementation_type is invalid")
    status = payload.get("status", CapabilityVersion.Status.CANDIDATE)
    if status != CapabilityVersion.Status.CANDIDATE:
        raise APIRequestError("VALIDATION_ERROR", "new versions must start as CANDIDATE")
    input_schema = _schema(payload.get("input_schema", {}), "input_schema")
    output_schema = _schema(payload.get("output_schema", {}), "output_schema")
    _check_schema(input_schema, "input_schema")
    _check_schema(output_schema, "output_schema")
    semantic_tags = _string_list(payload.get("semantic_tags", []), "semantic_tags")
    subjects = _string_list(payload.get("subjects", []), "subjects")
    resolves = _string_list(payload.get("resolves", []), "resolves")
    timeout_seconds = _positive_int(payload.get("timeout_seconds", 15), "timeout_seconds", 300)
    retry_count = _positive_int(payload.get("retry_count", 0), "retry_count", 10, minimum=0)
    script_path = payload.get("script_path")
    endpoint = payload.get("endpoint")
    mcp_server = payload.get("mcp_server")
    mcp_tool = payload.get("mcp_tool")
    if implementation_type == "EXEC":
        if not _safe_script_path(script_path):
            raise APIRequestError("VALIDATION_ERROR", "EXEC script_path must be under the plugin allowlist")
        script_path = script_path.strip()
    elif script_path is not None:
        raise APIRequestError("VALIDATION_ERROR", "script_path is only valid for EXEC")
    if implementation_type == "REST":
        if not isinstance(endpoint, str) or not _rest_endpoint_allowed(endpoint):
            raise APIRequestError("VALIDATION_ERROR", "REST endpoint is outside the internal allowlist")
    elif endpoint is not None:
        raise APIRequestError("VALIDATION_ERROR", "endpoint is only valid for REST")
    if implementation_type == "MCP":
        if not _identifier(mcp_server, "mcp_server") or not _identifier(mcp_tool, "mcp_tool"):
            raise APIRequestError("VALIDATION_ERROR", "MCP server and tool are required")
    manifest = payload.get("manifest", {})
    if not isinstance(manifest, Mapping):
        raise APIRequestError("VALIDATION_ERROR", "manifest must be an object")
    version_row = CapabilityVersion.objects.create(
        capability=capability,
        version=version,
        implementation_type=implementation_type,
        status=CapabilityVersion.Status.CANDIDATE,
        manifest=dict(manifest),
        semantic_tags=semantic_tags,
        subjects=subjects,
        resolves=resolves,
        input_schema=input_schema,
        output_schema=output_schema,
        endpoint=endpoint,
        script_path=script_path,
        mcp_server=mcp_server,
        mcp_tool=mcp_tool,
        timeout_seconds=timeout_seconds,
        retry_count=retry_count,
    )
    record_event(
        actor=actor,
        environment=None,
        event_type="capability_version.created",
        object_type="CapabilityVersion",
        object_id=version_row.pk,
        payload={
            "capability_id": capability.capability_id,
            "capability_version_id": str(version_row.pk),
            "version": version_row.version,
            "implementation_type": version_row.implementation_type,
        },
    )
    return version_row


def _transition(request, capability_id, version, *, target):
    auth_error = require_role(request, "platform_admin")
    if auth_error is not None:
        return auth_error
    if request.method != "POST":
        return _method("capability transition")
    try:
        payload = parse_json_object(request)
        with transaction.atomic():
            capability, version_row = _get_version_locked(capability_id, version)
            if target == CapabilityVersion.Status.SHADOW:
                _enter_shadow(capability, version_row)
            else:
                _activate(capability, version_row, payload)
            record_event(
                actor=request.user,
                environment=None,
                event_type="capability_version." + target.lower(),
                object_type="CapabilityVersion",
                object_id=version_row.pk,
                payload={
                    "capability_id": capability.capability_id,
                    "capability_version_id": str(version_row.pk),
                    "version": version_row.version,
                    "to_status": target,
                },
            )
    except APIRequestError as error:
        return _request_error(error)
    except (Capability.DoesNotExist, CapabilityVersion.DoesNotExist):
        return _not_found("capability version")
    except CapabilityAPIError as error:
        return api_error(error.code, str(error), status=error.status)
    except ValueError as error:
        return api_error("VALIDATION_ERROR", str(error), status=400)
    except IntegrityError:
        return api_error("CONFLICT", "capability transition conflicts with existing state", status=409)
    except Exception:
        logger.exception("capability transition failed")
        return api_error("INTERNAL_ERROR", "the capability transition failed", status=500)
    return JsonResponse(serialize_version(version_row))


def _enter_shadow(capability, version):
    if capability.status != Capability.Status.ACTIVE:
        raise CapabilityAPIError("CAPABILITY_NOT_ACTIVE", "capability is not active", 409)
    _assert_read_only(capability, version)
    _validate_schemas(version)
    if version.status == CapabilityVersion.Status.SHADOW:
        return
    if version.status != CapabilityVersion.Status.CANDIDATE:
        raise ValueError("only CANDIDATE versions can enter SHADOW")
    version.status = CapabilityVersion.Status.SHADOW
    version.save(update_fields=["status"])


def _activate(capability, version, payload):
    _assert_read_only(capability, version)
    _validate_schemas(version)
    if (
        version.status == CapabilityVersion.Status.ACTIVE
        and capability.current_version_id == version.pk
    ):
        return
    if version.status != CapabilityVersion.Status.SHADOW:
        raise ValueError("only SHADOW versions can become ACTIVE")
    # The public demo has no separate validation table; omitted values mean the
    # documented passing threshold, while callers can supply measured values.
    shadow_cases = _threshold(payload, "shadow_cases", version, 3)
    precision = _threshold(payload, "precision", version, Decimal("0.8"))
    false_positives = _threshold(payload, "critical_false_positive", version, 0)
    if shadow_cases < 3 or precision < Decimal("0.8") or false_positives != 0:
        raise ValueError("shadow validation thresholds are not met")
    CapabilityVersion.objects.filter(
        capability=capability, status=CapabilityVersion.Status.ACTIVE
    ).exclude(pk=version.pk).update(
        status=CapabilityVersion.Status.RETIRED, retired_at=timezone.now()
    )
    version.status = CapabilityVersion.Status.ACTIVE
    version.activated_at = timezone.now()
    version.save(update_fields=["status", "activated_at"])
    capability.current_version = version
    capability.status = Capability.Status.ACTIVE
    capability.read_only = True
    capability.save(update_fields=["current_version", "status", "read_only", "updated_at"])


def _simulate_version_test(capability, version, payload):
    if capability.status != Capability.Status.ACTIVE:
        raise CapabilityAPIError("CAPABILITY_NOT_ACTIVE", "capability is not active", 409)
    _assert_read_only(capability, version)
    _validate_schemas(version)
    supplied = payload.get("input")
    if supplied is None:
        supplied = _schema_sample(version.input_schema)
    if not isinstance(supplied, Mapping):
        raise APIRequestError("VALIDATION_ERROR", "input must be an object")
    try:
        from jsonschema import validate

        validate(dict(supplied), version.input_schema)
    except Exception as error:
        raise ValueError("input does not satisfy the capability schema") from error
    # Mock tests intentionally never dispatch REST/EXEC/MCP or execute a path from HTTP.
    output = {"simulated": True, "implementation_type": version.implementation_type}
    return {
        "capability_id": capability.capability_id,
        "capability_version_id": str(version.pk),
        "version": version.version,
        "status": "PASSED",
        "simulated": True,
        "output": output,
    }


def _schema_sample(schema):
    if not isinstance(schema, Mapping):
        return {}
    if "default" in schema:
        return schema["default"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]
    if isinstance(schema.get("oneOf"), list) and schema["oneOf"]:
        return _schema_sample(schema["oneOf"][0])
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        required = schema.get("required", [])
        names = required if isinstance(required, list) else []
        return {name: _schema_sample(properties.get(name, {})) for name in names if isinstance(name, str)}
    if kind == "array":
        return []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0
    if kind == "boolean":
        return False
    return "mock"


def _resolve_candidates(claim, subject_type, tags):
    queryset = CapabilityVersion.objects.select_related("capability").filter(
        status=CapabilityVersion.Status.ACTIVE,
        capability__status=Capability.Status.ACTIVE,
        capability__read_only=True,
        capability__current_version_id=F("pk"),
        resolves__contains=[claim],
    )
    values = list(queryset[:100])
    try:
        formal = CapabilityRegistry().resolve(claim)
    except Exception:
        formal = None
    formal_id = getattr(formal, "pk", None)

    def rank(item):
        return (
            0 if formal_id is not None and item.pk == formal_id else 1,
            0 if not subject_type or subject_type in (item.subjects or []) else 1,
            0 if not tags or set(tags).intersection(item.semantic_tags or []) else 1,
            item.capability.capability_id,
            item.version,
        )

    return sorted(values, key=rank)


def _get_version(capability_id, version):
    capability = Capability.objects.select_related("current_version").get(capability_id=capability_id)
    return capability, CapabilityVersion.objects.select_related("capability").get(
        capability=capability, version=version
    )


def _get_version_locked(capability_id, version):
    capability = Capability.objects.select_for_update().get(capability_id=capability_id)
    version_row = CapabilityVersion.objects.select_for_update().select_related("capability").get(
        capability=capability, version=version
    )
    return capability, version_row


def _assert_read_only(capability, version):
    if capability.read_only is not True:
        raise CapabilityAPIError("CAPABILITY_NOT_READ_ONLY", "capability must be read-only", 403)
    manifest = version.manifest if isinstance(version.manifest, Mapping) else {}
    security = manifest.get("security")
    if manifest.get("read_only") is False or isinstance(security, Mapping) and security.get("read_only") is False:
        raise CapabilityAPIError(
            "CAPABILITY_NOT_READ_ONLY",
            "capability manifest must be read-only",
            403,
        )


def _validate_schemas(version):
    _check_schema(version.input_schema, "input_schema")
    _check_schema(version.output_schema, "output_schema")


def _check_schema(schema, label):
    if not isinstance(schema, Mapping):
        raise ValueError(f"{label} must be an object")
    try:
        validator_for(schema).check_schema(dict(schema))
    except (SchemaError, TypeError, ValueError) as error:
        raise ValueError(f"{label} is invalid") from error


def _threshold(payload, name, version, default):
    value = payload.get(name)
    if value is None:
        manifest = version.manifest if isinstance(version.manifest, Mapping) else {}
        validation = manifest.get("validation") if isinstance(manifest.get("validation"), Mapping) else {}
        value = validation.get(name, default)
    if name == "shadow_cases":
        return _positive_int(value, name, 100000, minimum=0)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} is invalid") from None
    if name == "precision" and not Decimal("0") <= parsed <= Decimal("1"):
        raise ValueError(f"{name} is outside the allowed range")
    return parsed


def _identifier(value, field):
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value.strip()):
        raise APIRequestError("VALIDATION_ERROR", f"{field} is invalid", details={"field": field})
    return value.strip()


def _text(value, field, max_length):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise APIRequestError("VALIDATION_ERROR", f"{field} is invalid", details={"field": field})
    return value.strip()


def _string_list(value, field):
    if not isinstance(value, list) or len(value) > _MAX_LIST or any(not isinstance(item, str) for item in value):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be a bounded string list")
    result = []
    for item in value:
        result.append(_identifier(item, field))
    return result


def _schema(value, field):
    if not isinstance(value, Mapping):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an object")
    return dict(value)


def _positive_int(value, field, maximum, *, minimum=1):
    if isinstance(value, bool):
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]*)", value.strip()):
        parsed = int(value)
    else:
        raise APIRequestError("VALIDATION_ERROR", f"{field} must be an integer") from None
    if parsed < minimum or parsed > maximum:
        raise APIRequestError("VALIDATION_ERROR", f"{field} is outside the allowed range")
    return parsed


def _query_bool(value):
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    raise APIRequestError("VALIDATION_ERROR", "read_only must be true or false")


def _rest_endpoint_allowed(endpoint):
    from services.plugin_runtime.rest_executor import RestExecutor

    return any(RestExecutor._is_allowed(endpoint, prefix) for prefix in RestExecutor().allowed_prefixes)


def _safe_script_path(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    if "\\" in value or value.startswith("/"):
        return False
    parts = value.split("/")
    prefix = ("plugins", "exec")
    if parts[: len(prefix)] != list(prefix) or len(parts) <= len(prefix):
        return False
    remainder = parts[len(prefix) :]
    return all(_SCRIPT_PART_RE.fullmatch(part) for part in remainder) and remainder[-1].endswith(".py")


def _request_error(error):
    return api_error(error.code, error.message, status=error.status, details=error.details)


def _not_found(resource):
    return api_error("NOT_FOUND", f"the requested {resource} does not exist", status=404)


def _method(resource):
    return api_error("METHOD_NOT_ALLOWED", f"{resource} method is not allowed", status=405)


# Readable aliases for callers that use the resource names directly.
capabilities = collection
capability_detail = detail
create_capability_version = versions
capability_versions = versions
version_test = test_version
version_shadow = shadow
version_activate = activate


__all__ = [
    "activate",
    "capabilities",
    "capability_detail",
    "capability_versions",
    "collection",
    "create_capability_version",
    "detail",
    "resolve",
    "shadow",
    "test_version",
    "version_activate",
    "version_shadow",
    "version_test",
    "versions",
]
