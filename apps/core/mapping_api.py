"""Mapping draft business input contract; deployment access is handled externally."""
import json
from functools import wraps
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse

from apps.api.http import APIRequestError, api_error
from . import mapping_services as svc
from .models import Environment, MappingBundle

SCOPE = {"environment_id", "source_ref", "cluster_uid"}
WRITE = {"expected_head", "reason", "actor_label"}


def _fail(message):
    raise svc.MappingInputError(message)


def _uuid(value):
    if type(value) is not str:
        _fail("A UUID string is required.")
    try:
        return UUID(value)
    except ValueError:
        _fail("Invalid UUID.")


def _strict(data, fields):
    if type(data) is not dict or set(data) != fields:
        _fail("Unexpected or missing request fields.")
    return data


def _scope(data):
    return {"environment_id": _uuid(data["environment_id"]), "source_ref": data["source_ref"], "cluster_uid": svc._token(data["cluster_uid"], "cluster_uid")}


def _environment(environment_id, source_ref):
    environment = Environment.objects.get(pk=_uuid(environment_id))
    svc.check_mock_environment(environment, source_ref)
    return environment


def business_boundary(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        try:
            if request.method not in ("GET", "POST"):
                return api_error("METHOD", "Method not allowed.", status=405)
            if request.method == "POST":
                if request.content_type != "application/json":
                    return api_error("JSON_REQUIRED", "JSON is required.", status=415)
                length = request.META.get("CONTENT_LENGTH", "0") or "0"
                if not length.isdigit() or int(length) > 65536:
                    return api_error("BODY_LIMIT", "Request body exceeds the limit.", status=413)
                if len(request.body) > 65536:
                    return api_error("BODY_LIMIT", "Request body exceeds the limit.", status=413)
            return view(request, *args, **kwargs)
        except svc.MappingConflict as exc:
            return api_error("HEAD_CONFLICT", "版本冲突；保留输入，重新读取后再提交。", status=409, details={"current_head": exc.current_head})
        except svc.MappingScopeError:
            return api_error("MOCK_SCOPE", "Only the explicitly selected mock scope is allowed.", status=403)
        except (Environment.DoesNotExist, MappingBundle.DoesNotExist):
            return api_error("NOT_FOUND", "Mapping scope was not found.", status=404)
        except svc.MappingInputError as exc:
            if exc.path is not None:
                return api_error("INVALID_INPUT", "Invalid or unsupported mapping request.", status=400, details={"path": exc.path, "reason": str(exc)})
            return api_error("INVALID_INPUT", "Invalid or unsupported mapping request.", status=400)
        except (APIRequestError, ValidationError, ValueError, TypeError, UnicodeError):
            return api_error("INVALID_INPUT", "Invalid or unsupported mapping request.", status=400)
        except DatabaseError:
            return api_error("STORAGE_UNAVAILABLE", "映射存储未就绪；需要显式部署迁移和模拟环境。", status=503)
    return guarded


def _input(request, fields):
    if request.method == "GET":
        if any(len(request.GET.getlist(key)) != 1 for key in request.GET):
            _fail("Repeated query fields are not supported.")
        data = request.GET.dict()
    else:
        if request.GET:
            _fail("Write scope belongs in the JSON body.")
        data = json.loads(request.body.decode("utf-8"), parse_constant=lambda _: _fail("Nonfinite JSON is not allowed."))
    return _strict(data, fields)


@business_boundary
def context(request):
    if request.method != "GET" or request.GET:
        return api_error("METHOD", "Use GET without query fields.", status=405)
    environments = []
    for env in Environment.objects.filter(is_active=True, environment_type__in=Environment.EnvironmentType.values, metadata__local_mapping=svc.MOCK_METADATA).order_by("name", "id")[:101]:
        try:
            svc.check_mock_environment(env, svc.SOURCE_REF)
        except svc.MappingScopeError:
            continue
        environments.append({"id": str(env.pk), "name": env.name})
    catalog = [{"standard_field": field, "source_metric": spec[0], "source_type": svc.source_type(field), "source_unit": spec[1], "output_unit": spec[2], "conversion": spec[3]} for field, spec in svc.FIELD_SPECS.items()]
    return JsonResponse({"environments": environments, "catalog": catalog, "source_ref": svc.SOURCE_REF, "schema_version": svc.SCHEMA_VERSION, "status": "DRAFT", "validation": "NOT_RUN", "unimplemented_fields": 37-len(svc.FIELD_SPECS)})


@business_boundary
def bundles(request):
    if request.method == "GET":
        data = _input(request, {"environment_id", "source_ref"})
        env = _environment(data["environment_id"], data["source_ref"])
        rows = list(MappingBundle.objects.filter(environment=env, source_ref=data["source_ref"]).order_by("created_at", "id")[:101])
        items = [svc.read_bundle(bundle_id=row.pk, environment_id=env.pk, source_ref=data["source_ref"], cluster_uid=row.cluster_uid) for row in rows[:100]]
        return JsonResponse({"items": items, "has_more": len(rows) > 100})
    data = _input(request, SCOPE | WRITE | {"monitor_cluster_id", "content"})
    bundle = svc.create_bundle(**_scope(data), monitor_cluster_id=data["monitor_cluster_id"], content=data["content"], **{key: data[key] for key in WRITE})
    return JsonResponse(svc.read_bundle(bundle_id=bundle.pk, **_scope(data)), status=201)


@business_boundary
def detail(request, bundle_id):
    if request.method != "GET":
        return api_error("METHOD", "Use GET.", status=405)
    data = _input(request, SCOPE)
    return JsonResponse(svc.read_bundle(bundle_id=bundle_id, **_scope(data)))


@business_boundary
def revisions(request, bundle_id):
    if request.method == "POST":
        data = _input(request, SCOPE | WRITE | {"content"})
        svc.append_revision(bundle_id=bundle_id, **_scope(data), content=data["content"], **{key: data[key] for key in WRITE})
        return JsonResponse(svc.read_bundle(bundle_id=bundle_id, **_scope(data)), status=201)
    data = _input(request, SCOPE)
    scoped = _scope(data)
    svc.read_bundle(bundle_id=bundle_id, **scoped)
    rows = list(MappingBundle.objects.get(pk=bundle_id, environment_id=scoped["environment_id"], source_ref=scoped["source_ref"], cluster_uid=scoped["cluster_uid"]).revisions.order_by("-version")[:101])
    return JsonResponse({"items": [{"version": row.version, "content": json.loads(row.canonical_json), "content_hash": row.content_hash, "parent_revision": str(row.parent_revision_id) if row.parent_revision_id else None, "rollback_from": str(row.rollback_from_id) if row.rollback_from_id else None, "reason": row.reason, "actor_label": row.actor_label, "created_at": row.created_at.isoformat()} for row in rows[:100]], "has_more": len(rows) > 100})


@business_boundary
def rollback(request, bundle_id):
    if request.method != "POST":
        return api_error("METHOD", "Use POST.", status=405)
    data = _input(request, SCOPE | WRITE | {"target_version"})
    svc.rollback_revision(bundle_id=bundle_id, **_scope(data), target_version=data["target_version"], **{key: data[key] for key in WRITE})
    return JsonResponse(svc.read_bundle(bundle_id=bundle_id, **_scope(data)), status=201)


@business_boundary
def activate(request, bundle_id):
    from . import mapping_loop as loop
    if request.method != 'POST':return api_error('METHOD','Use POST.',status=405)
    data=_input(request,SCOPE|WRITE|{'expected_active','content_hash','validation_id','idempotency_key'})
    try:
        event=loop.activate(scope={'bundle_id':bundle_id,**_scope(data)},**{key:data[key]for key in WRITE|{'expected_active','content_hash','validation_id','idempotency_key'}})
    except loop.ValidationRejected:return api_error('VALIDATION_REQUIRED','A current bound mock receipt is required.',status=422)
    return JsonResponse({'activation_id':str(event.pk),'active_revision_id':str(event.revision_id),'active_version':event.revision.version})


@business_boundary
def validate(request,bundle_id):
    from . import mapping_loop as loop
    if request.method!='POST':return api_error('METHOD','Use POST.',status=405)
    data=_input(request,SCOPE|{'expected_head','kind','fixture','seed','start','end','step'})
    row=loop.validate(scope={'bundle_id':bundle_id,**_scope(data)},**{key:data[key]for key in {'expected_head','kind','fixture','seed','start','end','step'}})
    return JsonResponse({'validation_id':str(row.pk),'kind':row.kind,'result':row.result,'binding':row.binding,'valid_until':row.valid_until.isoformat()})


@business_boundary
def collect(request,bundle_id):
    from . import mapping_loop as loop
    if request.method!='POST':return api_error('METHOD','Use POST.',status=405)
    data=_input(request,SCOPE|{'expected_active','idempotency_key'})
    try:row=loop.collect(scope={'bundle_id':bundle_id,**_scope(data)},expected_active=data['expected_active'],idempotency_key=data['idempotency_key'])
    except loop.ValidationRejected:return api_error('VALIDATION_REQUIRED','A current bound mock receipt is required.',status=422)
    return JsonResponse({'batch_id':str(row.pk),'status':row.status,'run_id':str(row.run_id)if row.run_id else None,'error_code':row.error_code})


@business_boundary
def batch(request,bundle_id,batch_id):
    from .models import MappingCollection
    if request.method!='GET':return api_error('METHOD','Use GET.',status=405)
    data=_input(request,SCOPE);svc.read_bundle(bundle_id=bundle_id,**_scope(data))
    row=MappingCollection.objects.get(pk=batch_id,bundle_id=bundle_id)
    return JsonResponse({'batch_id':str(row.pk),'status':row.status,'run_id':str(row.run_id)if row.run_id else None,'error_code':row.error_code,'binding':row.binding,'evidence':row.evidence})


@business_boundary
def enabled(request, bundle_id):
    from . import mapping_loop as loop
    if request.method != 'POST':
        return api_error('METHOD', 'Use POST.', status=405)
    fields = WRITE | {'expected_active', 'enabled', 'validation_id', 'idempotency_key'}
    data = _input(request, SCOPE | fields)
    try:
        event = loop.set_enabled(scope={'bundle_id': bundle_id, **_scope(data)},
            **{key: data[key] for key in fields})
    except loop.ValidationRejected:
        return api_error('VALIDATION_REQUIRED', 'Enable requires a current active-head mock receipt.', status=422)
    return JsonResponse({'event_id': str(event.pk), 'enabled': event.enabled,
        'actor_label_kind': 'SELF_DESCRIBED_LOCAL'})
