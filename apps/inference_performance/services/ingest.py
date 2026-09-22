from __future__ import annotations

import uuid
from django.db import IntegrityError, transaction

from apps.api.http import APIRequestError
from apps.core.models import Environment

from ..models import InferencePerformanceSnapshot
from ..schemas import BatchSnapshotRequest, PerformanceSample, SnapshotRequest
from .evaluator import evaluate_snapshot


def resolve_environment(value: str) -> Environment:
    try:
        try:
            return Environment.objects.get(pk=uuid.UUID(value))
        except ValueError:
            return Environment.objects.get(slug=value)
    except Environment.DoesNotExist:
        raise APIRequestError("ENVIRONMENT_NOT_FOUND", "environment does not exist", details={"environment_id": value}) from None


def _create_snapshot(*, environment: Environment, source: str, engine, sample: PerformanceSample) -> InferencePerformanceSnapshot:
    return InferencePerformanceSnapshot(
        environment=environment, source=source, sample_id=sample.sample_id,
        engine_id=engine.engine_id, engine_type=engine.engine_type, model_name=engine.model_name,
        window_start=sample.window_start, window_end=sample.window_end, metrics=sample.metrics,
    )


@transaction.atomic
def ingest_snapshot(request: SnapshotRequest) -> tuple[InferencePerformanceSnapshot, bool]:
    existing = InferencePerformanceSnapshot.objects.filter(source=request.source, sample_id=request.sample.sample_id).first()
    if existing is not None:
        return existing, False
    environment = resolve_environment(request.environment_id)
    try:
        snapshot = _create_snapshot(environment=environment, source=request.source, engine=request.engine, sample=request.sample)
        # Keep the uniqueness race inside a savepoint so the outer API transaction
        # remains usable when another ingest wins the same source/sample id race.
        with transaction.atomic():
            snapshot.save(force_insert=True)
    except IntegrityError:
        snapshot = InferencePerformanceSnapshot.objects.get(source=request.source, sample_id=request.sample.sample_id)
        return snapshot, False
    snapshot.evaluation = evaluate_snapshot(snapshot)
    snapshot.save(update_fields=["evaluation"])
    return snapshot, True


@transaction.atomic
def ingest_batch(request: BatchSnapshotRequest) -> tuple[list[InferencePerformanceSnapshot], InferencePerformanceSnapshot | None, int]:
    environment = resolve_environment(request.environment_id)
    existing_ids = set(
        InferencePerformanceSnapshot.objects.filter(source=request.source, sample_id__in=[sample.sample_id for sample in request.samples]).values_list("sample_id", flat=True)
    )
    to_create = [
        _create_snapshot(environment=environment, source=request.source, engine=request.engine, sample=sample)
        for sample in request.samples if sample.sample_id not in existing_ids
    ]
    created_count = 0
    if to_create:
        InferencePerformanceSnapshot.objects.bulk_create(to_create, ignore_conflicts=True)
    stored = list(InferencePerformanceSnapshot.objects.filter(source=request.source, sample_id__in=[sample.sample_id for sample in request.samples]))
    by_sample_id = {snapshot.sample_id: snapshot for snapshot in stored}
    ordered = [by_sample_id[sample.sample_id] for sample in request.samples]
    evaluated = None
    if request.evaluate_latest:
        evaluated = ordered[-1]
        if not evaluated.evaluation:
            evaluated.evaluation = evaluate_snapshot(evaluated)
            evaluated.save(update_fields=["evaluation"])
    created_count = len(set(sample.sample_id for sample in to_create) & set(by_sample_id))
    return ordered, evaluated, created_count
