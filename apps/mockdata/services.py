"""Persistence boundary for pure mock datasets."""

import os

from django.conf import settings
from django.db import transaction
from django.utils import timezone


def persist_dataset(environment, generated_dataset):
    from apps.assets.models import Asset
    from apps.inspections.models import MockChange, MockDataset, MockEvent, MockLog, MockMetric

    with transaction.atomic():
        dataset = MockDataset.objects.create(
            environment=environment,
            seed=generated_dataset.seed,
            scenario=generated_dataset.scenario,
            dataset_date=generated_dataset.dataset_date,
            version="1.0.0",
            status=MockDataset.Status.GENERATING,
            generator_config={
                "seed": generated_dataset.seed,
                "scenario": generated_dataset.scenario,
                "dataset_date": generated_dataset.dataset_date.isoformat(),
                "version": generated_dataset.version,
                "missing_data": list(generated_dataset.missing_data),
            },
        )

        assets = {}
        for record in generated_dataset.assets:
            asset, _ = Asset.objects.update_or_create(
                environment=environment,
                external_key=record.asset_key,
                defaults={
                    "asset_type": record.asset_type,
                    "name": record.name,
                    "parent": assets.get(record.parent_key),
                    "labels": dict(record.labels),
                    "topology": dict(record.topology),
                },
            )
            assets[record.asset_key] = asset

        MockMetric.objects.bulk_create(
            [
                MockMetric(
                    dataset=dataset,
                    asset=assets[point.asset_key],
                    metric_name=point.metric_name,
                    ts=point.ts,
                    value=point.value,
                    labels=dict(point.labels),
                )
                for point in generated_dataset.metrics
            ]
        )
        MockLog.objects.bulk_create(
            [
                MockLog(
                    dataset=dataset,
                    asset=assets[record.asset_key],
                    ts=record.ts,
                    source=record.source,
                    level=record.level,
                    message=record.message,
                    attributes=dict(record.attributes),
                )
                for record in generated_dataset.logs
            ]
        )
        MockEvent.objects.bulk_create(
            [
                MockEvent(
                    dataset=dataset,
                    asset=assets.get(record.asset_key),
                    ts=record.ts,
                    event_type=record.event_type,
                    reason=record.reason,
                    message=record.message,
                    attributes=dict(record.attributes),
                )
                for record in generated_dataset.events
            ]
        )
        MockChange.objects.bulk_create(
            [
                MockChange(
                    dataset=dataset,
                    asset=assets.get(record.asset_key),
                    start_at=record.start_at,
                    end_at=record.end_at,
                    change_type=record.change_type,
                    summary=record.summary,
                    attributes=dict(record.attributes),
                )
                for record in generated_dataset.changes
            ]
        )

        dataset.asset_count = len(assets)
        dataset.metric_count = len(generated_dataset.metrics)
        dataset.log_count = len(generated_dataset.logs)
        dataset.event_count = len(generated_dataset.events)
        dataset.change_count = len(generated_dataset.changes)
        dataset.status = MockDataset.Status.READY
        dataset.ready_at = timezone.now()
        dataset.save(
            update_fields=[
                "asset_count",
                "metric_count",
                "log_count",
                "event_count",
                "change_count",
                "status",
                "ready_at",
            ]
        )
    return dataset


def generate_and_persist(environment, seed, scenario, dataset_date=None, *, business_date=None):
    from services.mock_generator.generator import generate_dataset

    generated = generate_dataset(
        seed,
        scenario,
        dataset_date,
        business_date=business_date,
    )
    return persist_dataset(environment, generated)


def get_or_create_manual_dataset(environment, run_date=None):
    """Return the deterministic dataset used by a manual inspection run.

    Manual runs have one canonical input.  Reusing a READY dataset makes a
    retry idempotent while keeping dataset generation out of the HTTP stage
    executor.  The environment row is locked by the caller before this
    function is used, so two manual triggers cannot generate competing
    datasets for the same immutable input.
    """

    from apps.inspections.models import MockDataset

    run_date = run_date or timezone.localdate()
    seed = getattr(settings, "MANUAL_INSPECTION_SEED", None)
    if seed is None:
        seed = os.getenv("MANUAL_INSPECTION_SEED", "20260823")
    scenario = getattr(settings, "MANUAL_INSPECTION_SCENARIO", None)
    if scenario is None:
        scenario = os.getenv("MANUAL_INSPECTION_SCENARIO", "llm_scheduler_pressure")
    seed = int(seed)
    scenario = str(scenario).strip()

    dataset = (
        MockDataset.objects.select_for_update()
        .filter(
            environment=environment,
            dataset_date=run_date,
            seed=seed,
            scenario=scenario,
            status=MockDataset.Status.READY,
        )
        .order_by("created_at", "pk")
        .first()
    )
    if dataset is not None:
        return dataset
    return generate_and_persist(environment, seed, scenario, run_date)


create_mock_dataset = generate_and_persist


__all__ = [
    "create_mock_dataset",
    "generate_and_persist",
    "get_or_create_manual_dataset",
    "persist_dataset",
]
