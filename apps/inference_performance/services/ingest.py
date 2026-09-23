from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction

from apps.api.http import APIRequestError
from apps.core.models import Environment
from apps.inspections.services.code_dispatch import dispatch_code_rule

from ..models import InferencePerformanceSnapshot
from ..schemas import BatchSnapshotRequest, PerformanceSample, SnapshotRequest
from .assets import get_or_create_inference_asset
from .input_reader import InferenceSnapshotInputReader


class IdempotencyConflict(APIRequestError):
    def __init__(self):
        super().__init__('IDEMPOTENCY_CONFLICT', 'sample identity or window conflicts with an existing observation')
        self.status = 409


def resolve_environment(value: str) -> Environment:
    try:
        try:
            return Environment.objects.get(pk=uuid.UUID(value))
        except ValueError:
            return Environment.objects.get(slug=value)
    except Environment.DoesNotExist:
        raise APIRequestError('ENVIRONMENT_NOT_FOUND', 'environment does not exist', details={'environment_id': value}) from None


def _same(snapshot, *, environment, engine, sample):
    return (
        snapshot.environment_id == environment.pk
        and snapshot.engine_id == engine.engine_id
        and snapshot.engine_type == engine.engine_type
        and snapshot.model_name == engine.model_name
        and snapshot.window_start == sample.window_start
        and snapshot.window_end == sample.window_end
        and snapshot.metrics == sample.metrics
    )


def _evaluate(snapshot):
    reader = InferenceSnapshotInputReader(mode='COMPUTE', assets=[snapshot.asset], snapshot=snapshot)
    results = dispatch_code_rule(rule_code='llm.performance_profile', reader=reader, assets=[snapshot.asset], config={})
    if len(results) != 1 or results[0].status == 'ERROR':
        raise RuntimeError('performance plugin evaluation failed')
    snapshot.evaluation = results[0].evidence['evaluation']
    snapshot.save(update_fields=['evaluation'])


def _store_sample(*, environment, source, engine, sample, asset):
    existing = InferencePerformanceSnapshot.objects.filter(source=source, sample_id=sample.sample_id).first()
    if existing is not None:
        if not _same(existing, environment=environment, engine=engine, sample=sample):
            raise IdempotencyConflict()
        if existing.asset_id is None:
            existing.asset = asset
            existing.save(update_fields=['asset'])
        return existing, False

    same_window = InferencePerformanceSnapshot.objects.filter(
        environment=environment, engine_id=engine.engine_id, engine_type=engine.engine_type,
        model_name=engine.model_name, window_start=sample.window_start, window_end=sample.window_end,
    ).first()
    if same_window is not None:
        if same_window.metrics != sample.metrics:
            raise IdempotencyConflict()
        if same_window.asset_id is None:
            same_window.asset = asset
            same_window.save(update_fields=['asset'])
        return same_window, False

    snapshot = InferencePerformanceSnapshot(
        environment=environment, asset=asset, source=source, sample_id=sample.sample_id,
        engine_id=engine.engine_id, engine_type=engine.engine_type, model_name=engine.model_name,
        window_start=sample.window_start, window_end=sample.window_end, metrics=sample.metrics,
    )
    try:
        with transaction.atomic():
            snapshot.save(force_insert=True)
    except IntegrityError:
        existing = InferencePerformanceSnapshot.objects.get(source=source, sample_id=sample.sample_id)
        if not _same(existing, environment=environment, engine=engine, sample=sample):
            raise IdempotencyConflict() from None
        return existing, False
    return snapshot, True


@transaction.atomic
def ingest_snapshot(request: SnapshotRequest) -> tuple[InferencePerformanceSnapshot, bool]:
    environment = resolve_environment(request.environment_id)
    asset = get_or_create_inference_asset(environment=environment, engine_id=request.engine.engine_id,
                                          engine_type=request.engine.engine_type, model_name=request.engine.model_name)
    # Locking the stable asset serializes window checks and evaluation for this identity.
    type(asset).objects.select_for_update().get(pk=asset.pk)
    snapshot, created = _store_sample(environment=environment, source=request.source,
                                      engine=request.engine, sample=request.sample, asset=asset)
    if created:
        _evaluate(snapshot)
    return snapshot, created


@transaction.atomic
def ingest_batch(request: BatchSnapshotRequest) -> tuple[list[InferencePerformanceSnapshot], InferencePerformanceSnapshot | None, int]:
    environment = resolve_environment(request.environment_id)
    asset = get_or_create_inference_asset(environment=environment, engine_id=request.engine.engine_id,
                                          engine_type=request.engine.engine_type, model_name=request.engine.model_name)
    type(asset).objects.select_for_update().get(pk=asset.pk)
    # The surrounding transaction rolls back every row if any later member conflicts.
    ordered = []
    created_count = 0
    for sample in request.samples:
        snapshot, created = _store_sample(environment=environment, source=request.source,
                                          engine=request.engine, sample=sample, asset=asset)
        ordered.append(snapshot)
        created_count += int(created)
    evaluated = None
    if request.evaluate_latest:
        evaluated = max(ordered, key=lambda row: (row.window_end, row.window_start, row.sample_id))
        if not evaluated.evaluation:
            _evaluate(evaluated)
    return ordered, evaluated, created_count
