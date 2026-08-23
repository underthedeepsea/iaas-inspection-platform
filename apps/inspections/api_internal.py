"""Authenticated HTTP boundary for the Airflow inspection batch stages."""

from datetime import date
import json
import logging
import os
import secrets
import uuid
from functools import wraps

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone

from apps.core.models import Environment
from apps.inspections.models import (
    DailySnapshot,
    InspectionItemRun,
    InspectionRun,
    MockDataset,
)
from apps.inspections.services.execution import execute_inspection_run
from apps.inspections.services.snapshot import build_daily_snapshot
from apps.mockdata.services import persist_dataset
from apps.risks.models import RiskObservation
from apps.risks.services.correlation import correlate_run
from apps.risks.services.reverify import reverify_pending_risks
from services.mock_generator.generator import generate_dataset


logger = logging.getLogger(__name__)


class BatchAPIError(Exception):
    def __init__(self, code, message, status=400, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def _error(error, status):
    payload = {"error": {"code": error.code, "message": error.message}}
    if error.details:
        payload["error"]["details"] = error.details
    return JsonResponse(payload, status=status)


def _configured_token():
    token = getattr(settings, "AIRFLOW_INTERNAL_TOKEN", None)
    if token is None:
        token = os.getenv("AIRFLOW_INTERNAL_TOKEN")
    return token


def _token_matches(request):
    configured = _configured_token()
    supplied = request.META.get("HTTP_X_AIRFLOW_TOKEN")
    if not isinstance(configured, str) or not configured:
        return False
    if not isinstance(supplied, str) or not supplied:
        return False
    return secrets.compare_digest(supplied, configured)


def batch_endpoint(view):
    """Authenticate before reading the request body or invoking a stage."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not _token_matches(request):
            return _error(
                BatchAPIError(
                    "invalid_airflow_token",
                    "a valid X-Airflow-Token is required",
                    403,
                ),
                403,
            )
        if request.method != "POST":
            return _error(
                BatchAPIError("method_not_allowed", "batch endpoints only accept POST", 405),
                405,
            )
        try:
            return view(request, *args, **kwargs)
        except BatchAPIError as error:
            return _error(error, error.status)
        except (Environment.DoesNotExist, MockDataset.DoesNotExist, InspectionRun.DoesNotExist):
            return _error(
                BatchAPIError("not_found", "the requested batch resource does not exist", 404),
                404,
            )
        except IntegrityError:
            return _error(
                BatchAPIError(
                    "immutable_input_conflict",
                    "the batch resource already exists with different immutable input",
                    409,
                ),
                409,
            )
        except ValueError as error:
            return _error(BatchAPIError("invalid_input", str(error), 400), 400)
        except Exception:
            logger.exception("internal inspection batch stage failed")
            return _error(
                BatchAPIError("internal_error", "the batch stage could not be completed", 500),
                500,
            )

    return wrapped


def _payload(request):
    try:
        raw = request.body
        value = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BatchAPIError("invalid_json", "request body must be valid JSON") from None
    if not isinstance(value, dict):
        raise BatchAPIError("invalid_json", "request body must be a JSON object")
    return value


def _required(payload, field):
    value = payload.get(field)
    if value is None or value == "":
        raise BatchAPIError("missing_field", f"{field} is required", details={"field": field})
    return value


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise BatchAPIError("invalid_field", f"{field} must be a UUID", details={"field": field}) from None


def _date(value, field):
    if not isinstance(value, str):
        raise BatchAPIError("invalid_field", f"{field} must be an ISO date", details={"field": field})
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BatchAPIError("invalid_field", f"{field} must be an ISO date", details={"field": field}) from None


def _seed(value):
    if isinstance(value, bool):
        raise BatchAPIError("invalid_field", "seed must be an integer", details={"field": "seed"})
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise BatchAPIError("invalid_field", "seed must be an integer", details={"field": "seed"}) from None
    if isinstance(value, str) and str(parsed) != value.strip():
        raise BatchAPIError("invalid_field", "seed must be an integer", details={"field": "seed"})
    return parsed


def _text(value, field, max_length=None):
    if not isinstance(value, str) or not value.strip():
        raise BatchAPIError("invalid_field", f"{field} must be a non-empty string", details={"field": field})
    value = value.strip()
    if max_length is not None and len(value) > max_length:
        raise BatchAPIError("invalid_field", f"{field} is too long", details={"field": field})
    return value


def _environment(environment_id, *, lock=False):
    query = Environment.objects
    if lock:
        query = query.select_for_update()
    try:
        return query.get(pk=environment_id)
    except Environment.DoesNotExist:
        raise BatchAPIError("not_found", "environment does not exist", 404) from None


def _dataset(dataset_id):
    try:
        return MockDataset.objects.select_related("environment").get(pk=dataset_id)
    except MockDataset.DoesNotExist:
        raise BatchAPIError("not_found", "dataset does not exist", 404) from None


def _run(run_id, *, lock=False):
    parsed = _uuid(run_id, "inspection_run_id")
    query = InspectionRun.objects.select_related("environment", "dataset")
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get(pk=parsed)
    except InspectionRun.DoesNotExist:
        raise BatchAPIError("not_found", "inspection run does not exist", 404) from None


def _check_run_context(run, payload):
    if "environment_id" in payload and _uuid(payload["environment_id"], "environment_id") != run.environment_id:
        raise BatchAPIError(
            "immutable_input_conflict",
            "environment_id does not match the inspection run",
            409,
        )
    if "dataset_id" in payload and _uuid(payload["dataset_id"], "dataset_id") != run.dataset_id:
        raise BatchAPIError(
            "immutable_input_conflict",
            "dataset_id does not match the inspection run",
            409,
        )
    if "run_date" in payload and _date(payload["run_date"], "run_date") != run.run_date:
        raise BatchAPIError(
            "immutable_input_conflict",
            "run_date does not match the inspection run",
            409,
        )


def _stage_done(run, stage):
    batch = (run.config_snapshot or {}).get("batch") or {}
    return bool((batch.get("stages") or {}).get(stage))


def _mark_stage(run, stage):
    snapshot = dict(run.config_snapshot or {})
    batch = dict(snapshot.get("batch") or {})
    stages = dict(batch.get("stages") or {})
    stages[stage] = True
    batch["stages"] = stages
    snapshot["batch"] = batch
    run.config_snapshot = snapshot
    run.save(update_fields=["config_snapshot"])


def _finish_run(run):
    """Reconcile run totals once, preserving terminal status on retries."""

    if run.status in {
        InspectionRun.Status.SUCCEEDED,
        InspectionRun.Status.PARTIAL,
        InspectionRun.Status.FAILED,
    } and run.finished_at is not None:
        return run
    item_runs = InspectionItemRun.objects.filter(inspection_run=run)
    total = item_runs.count()
    succeeded = item_runs.filter(status=InspectionItemRun.Status.SUCCEEDED).count()
    failed = item_runs.filter(status=InspectionItemRun.Status.FAILED).count()
    if run.status == InspectionRun.Status.FAILED:
        status = InspectionRun.Status.FAILED
    elif failed:
        status = InspectionRun.Status.PARTIAL
    else:
        status = InspectionRun.Status.SUCCEEDED
    run.status = status
    run.total_items = total
    run.success_items = succeeded
    run.failed_items = failed
    run.finished_at = run.finished_at or timezone.now()
    run.save(
        update_fields=[
            "status",
            "total_items",
            "success_items",
            "failed_items",
            "finished_at",
        ]
    )
    return run


def _run_response(run, **extra):
    run.refresh_from_db()
    data = {
        "inspection_run_id": str(run.pk),
        "environment_id": str(run.environment_id),
        "dataset_id": str(run.dataset_id) if run.dataset_id else None,
        "run_date": run.run_date.isoformat(),
        "status": run.status,
        "total_items": run.total_items,
        "success_items": run.success_items,
        "failed_items": run.failed_items,
        "risk_count": run.risk_count,
    }
    data.update(extra)
    return JsonResponse(data)


@batch_endpoint
def datasets(request):
    payload = _payload(request)
    environment_id = _uuid(_required(payload, "environment_id"), "environment_id")
    dataset_date = _date(
        payload.get("dataset_date", payload.get("business_date", payload.get("run_date"))),
        "dataset_date",
    )
    seed = _seed(_required(payload, "seed"))
    scenario = _text(_required(payload, "scenario"), "scenario", 64)
    requested_dataset_id = None
    if "dataset_id" in payload:
        requested_dataset_id = _uuid(payload["dataset_id"], "dataset_id")

    with transaction.atomic():
        environment = _environment(environment_id, lock=True)
        if requested_dataset_id is not None:
            try:
                requested_dataset = MockDataset.objects.select_for_update().get(
                    pk=requested_dataset_id
                )
            except MockDataset.DoesNotExist:
                raise BatchAPIError("not_found", "dataset does not exist", 404) from None
            if (
                requested_dataset.environment_id != environment_id
                or requested_dataset.dataset_date != dataset_date
                or requested_dataset.seed != seed
                or requested_dataset.scenario != scenario
            ):
                raise BatchAPIError(
                    "immutable_input_conflict",
                    "dataset_id is already bound to different immutable input",
                    409,
                )
        dataset = (
            MockDataset.objects.select_for_update()
            .filter(
                environment=environment,
                dataset_date=dataset_date,
                seed=seed,
                scenario=scenario,
            )
            .order_by("created_at", "pk")
            .first()
        )
        if dataset is None:
            try:
                generated = generate_dataset(seed, scenario, dataset_date)
            except ValueError as error:
                raise BatchAPIError("invalid_input", str(error)) from None
            dataset = persist_dataset(environment, generated)
        elif requested_dataset_id is not None and requested_dataset_id != dataset.pk:
            raise BatchAPIError(
                "immutable_input_conflict",
                "dataset_id does not match the canonical dataset input",
                409,
            )

    return JsonResponse(
        {
            "dataset_id": str(dataset.pk),
            "environment_id": str(dataset.environment_id),
            "dataset_date": dataset.dataset_date.isoformat(),
            "seed": dataset.seed,
            "scenario": dataset.scenario,
            "status": dataset.status,
        }
    )


@batch_endpoint
def inspection_runs(request):
    payload = _payload(request)
    dataset_id = _uuid(_required(payload, "dataset_id"), "dataset_id")
    environment_id = _uuid(_required(payload, "environment_id"), "environment_id")
    run_date = _date(
        payload.get("run_date", payload.get("business_date")),
        "run_date",
    )
    dag_run_id = _text(_required(payload, "dag_run_id"), "dag_run_id", 250)
    dataset = _dataset(dataset_id)
    if dataset.environment_id != environment_id or dataset.dataset_date != run_date:
        raise BatchAPIError(
            "immutable_input_conflict",
            "dataset and run context do not match",
            409,
        )

    with transaction.atomic():
        _environment(environment_id, lock=True)
        run = (
            InspectionRun.objects.select_for_update()
            .filter(airflow_dag_run_id=dag_run_id)
            .first()
        )
        if run is not None:
            if (
                run.environment_id != environment_id
                or run.dataset_id != dataset_id
                or run.run_date != run_date
            ):
                raise BatchAPIError(
                    "immutable_input_conflict",
                    "dag_run_id is already bound to different immutable input",
                    409,
                )
        else:
            try:
                run = InspectionRun.objects.create(
                    environment_id=environment_id,
                    dataset_id=dataset_id,
                    run_date=run_date,
                    trigger_type=InspectionRun.TriggerType.AIRFLOW,
                    airflow_dag_run_id=dag_run_id,
                    config_snapshot={
                        "batch": {
                            "environment_id": str(environment_id),
                            "dataset_id": str(dataset_id),
                            "run_date": run_date.isoformat(),
                            "dag_run_id": dag_run_id,
                            "stages": {},
                        }
                    },
                )
            except IntegrityError:
                run = InspectionRun.objects.select_for_update().get(airflow_dag_run_id=dag_run_id)

    return _run_response(run)


def _stage_run(request, run_id):
    payload = _payload(request)
    run = _run(run_id)
    _check_run_context(run, payload)
    if run.dataset_id is None:
        raise BatchAPIError("invalid_state", "inspection run has no dataset", 409)
    return run


@batch_endpoint
def execute(request, run_id):
    run = _stage_run(request, run_id)
    with transaction.atomic():
        run = _run(run.pk, lock=True)
        if _stage_done(run, "execute"):
            return _run_response(run)
        if run.started_at is None:
            run.started_at = timezone.now()
        run.status = InspectionRun.Status.RUNNING
        run.save(update_fields=["started_at", "status"])
        execute_inspection_run(run)
        _mark_stage(run, "execute")
    return _run_response(run)


@batch_endpoint
def correlate_risks(request, run_id):
    run = _stage_run(request, run_id)
    with transaction.atomic():
        run = _run(run.pk, lock=True)
        if not _stage_done(run, "correlate_risks"):
            correlate_run(run)
            _mark_stage(run, "correlate_risks")
    run.refresh_from_db()
    return _run_response(
        run,
        risk_ids=[
            str(pk)
            for pk in RiskObservation.objects.filter(inspection_run=run)
            .values_list("risk_id", flat=True)
            .distinct()
        ],
    )


@batch_endpoint
def reverify(request, run_id):
    run = _stage_run(request, run_id)
    with transaction.atomic():
        run = _run(run.pk, lock=True)
        if not _stage_done(run, "reverify"):
            # Task 8's reverify service intentionally accepts only a completed
            # successful run.  Reconcile that state here before delegating.
            _finish_run(run)
            reverify_pending_risks(run)
            _mark_stage(run, "reverify")
    return _run_response(run)


@batch_endpoint
def snapshot(request, run_id):
    payload = _payload(request)
    run = _run(run_id)
    _check_run_context(run, payload)
    if "snapshot_date" in payload and _date(payload["snapshot_date"], "snapshot_date") != run.run_date:
        raise BatchAPIError(
            "immutable_input_conflict",
            "snapshot_date does not match the inspection run date",
            409,
        )
    with transaction.atomic():
        run = _run(run.pk, lock=True)
        if _stage_done(run, "snapshot"):
            existing = DailySnapshot.objects.get(environment_id=run.environment_id, snapshot_date=run.run_date)
        else:
            _finish_run(run)
            try:
                existing = build_daily_snapshot(run)
            except ValueError as error:
                raise BatchAPIError("immutable_input_conflict", str(error), 409) from None
            _mark_stage(run, "snapshot")
    return JsonResponse(
        {
            "snapshot_id": str(existing.pk),
            "inspection_run_id": str(existing.inspection_run_id),
            "environment_id": str(existing.environment_id),
            "snapshot_date": existing.snapshot_date.isoformat(),
        }
    )


@batch_endpoint
def complete(request, run_id):
    run = _stage_run(request, run_id)
    with transaction.atomic():
        run = _run(run.pk, lock=True)
        if not _stage_done(run, "complete"):
            _finish_run(run)
            _mark_stage(run, "complete")
    return _run_response(run)


__all__ = [
    "batch_endpoint",
    "complete",
    "correlate_risks",
    "datasets",
    "execute",
    "inspection_runs",
    "reverify",
    "snapshot",
]
