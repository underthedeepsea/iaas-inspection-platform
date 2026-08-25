from datetime import date, datetime, timezone
import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import (
    Finding,
    InspectionItem,
    InspectionItemResourceType,
    InspectionItemRun,
    InspectionRun,
    ResourceInspectionSummary,
    ResourceType,
)
from apps.inspections.services.resource_summary import build_resource_summaries
from apps.investigations.models import Investigation
from apps.risks.models import Risk, RiskObservation


def make_environment():
    return Environment.objects.create(name="Summary", slug=f"summary-{uuid.uuid4().hex}")


def make_item(index):
    return InspectionItem.objects.create(
        code=f"summary.item.{index}.{uuid.uuid4().hex}",
        name=f"Summary item {index}",
        domain="LLM",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


@pytest.mark.django_db
def test_one_summary_per_run_and_resource_type():
    environment = make_environment()
    resource_type = ResourceType.objects.create(code="SUMMARY_RESOURCE", name="Summary")
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=date(2026, 8, 25),
        trigger_type=InspectionRun.TriggerType.MANUAL,
    )
    ResourceInspectionSummary.objects.create(
        inspection_run=run,
        resource_type=resource_type,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResourceInspectionSummary.objects.create(
                inspection_run=run,
                resource_type=resource_type,
            )


@pytest.mark.django_db
def test_build_resource_summaries_aggregates_counts_and_explainable_health_score():
    environment = make_environment()
    resource_type = ResourceType.objects.create(
        code="SUMMARY_RESOURCE",
        name="Summary",
        asset_selector={"asset_types": ["LLM_INSTANCE"]},
    )
    assets = [
        Asset.objects.create(
            environment=environment,
            external_key=f"summary-asset-{index}",
            asset_type=Asset.AssetType.LLM_INSTANCE,
            name=f"summary-{index}",
        )
        for index in range(36)
    ]
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=date(2026, 8, 25),
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=InspectionRun.Status.SUCCEEDED,
        started_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        finished_at=datetime(2026, 8, 25, 0, 2, tzinfo=timezone.utc),
        config_snapshot={
            "resolved_scope": {
                "resource_types": [resource_type.code],
                "asset_ids": [str(asset.id) for asset in assets],
                "asset_count": 36,
            }
        },
    )
    item_runs = []
    covered_ids = [str(asset.id) for asset in assets[:35]]
    for index in range(7):
        item = make_item(index)
        InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
        item_run = InspectionItemRun.objects.create(
            inspection_run=run,
            inspection_item=item,
            status=InspectionItemRun.Status.SUCCEEDED if index < 6 else InspectionItemRun.Status.FAILED,
            ai_admission_status=(
                InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE
                if index < 2
                else InspectionItemRun.AIAdmissionStatus.NO_AI
            ),
            asset_scope={"asset_ids": covered_ids, "resource_types": [resource_type.code]},
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        item_runs.append(item_run)

    for index in range(8):
        Finding.objects.create(
            inspection_item_run=item_runs[index % 6],
            asset=assets[index % 35],
            finding_code=f"summary.finding.{index}",
            title=f"Finding {index}",
            category="performance",
            severity="P2" if index == 0 else "P3",
            source_type=Finding.SourceType.EVENT,
            observed_at=run.finished_at,
        )

    for index, severity in enumerate(("P2", "P3", "P3", "P4")):
        risk = Risk.objects.create(
            environment=environment,
            inspection_item=item_runs[index].inspection_item,
            primary_asset=assets[index],
            risk_key=f"summary-risk-{index}",
            fingerprint=f"summary-fingerprint-{index}",
            title=f"Risk {index}",
            domain="LLM",
            severity=severity,
            first_seen_at=run.started_at,
            last_seen_at=run.finished_at,
        )
        RiskObservation.objects.create(
            risk=risk,
            inspection_run=run,
            inspection_item_run=item_runs[index],
            observed_at=run.finished_at,
            severity=severity,
            status_after=Risk.Status.NEW,
            finding_count=1,
        )

    for index in range(2):
        Investigation.objects.create(
            inspection_item_run=item_runs[index],
            trigger_type=Investigation.TriggerType.HUMAN,
            status=Investigation.Status.RESOLVED,
            entry_reason=Investigation.EntryReason.CLAIM_GAP,
            model_provider="test",
            model_name="test",
        )

    summaries = build_resource_summaries(run.id)

    assert len(summaries) == 1
    summary = summaries[0]
    assert {
        "assets_total": summary.assets_total,
        "assets_covered": summary.assets_covered,
        "inspection_item_count": summary.inspection_item_count,
        "success_item_count": summary.success_item_count,
        "failed_item_count": summary.failed_item_count,
        "finding_count": summary.finding_count,
        "risk_count": summary.risk_count,
        "p1_count": summary.p1_count,
        "p2_count": summary.p2_count,
        "ai_dependent_cases": summary.ai_dependent_cases,
        "ai_investigation_count": summary.ai_investigation_count,
        "p3_count": summary.p3_count,
        "p4_count": summary.p4_count,
        "health_score": float(summary.health_score),
    } == {
        "assets_total": 36,
        "assets_covered": 35,
        "inspection_item_count": 7,
        "success_item_count": 6,
        "failed_item_count": 1,
        "finding_count": 8,
        "risk_count": 4,
        "p1_count": 0,
        "p2_count": 1,
        "ai_dependent_cases": 2,
        "ai_investigation_count": 2,
        "p3_count": 2,
        "p4_count": 1,
        "health_score": 78.0,
    }
    assert summary.summary["health_score_breakdown"] == {
        "penalty": 21,
        "coverage_penalty": 1,
        "coverage_rate": 35 / 36,
    }
