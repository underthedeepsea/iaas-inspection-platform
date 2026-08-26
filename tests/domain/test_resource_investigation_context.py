from datetime import date, datetime, timezone
import json
import uuid

import pytest

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
from apps.investigations.models import Conversation
from apps.investigations.services.context_builder import (
    build_resource_run_context,
    build_resource_type_context,
)
from apps.risks.models import Evidence, Risk, RiskObservation


def make_environment():
    return Environment.objects.create(name="Context", slug=f"context-{uuid.uuid4().hex}")


def make_item():
    return InspectionItem.objects.create(
        code=f"context.item.{uuid.uuid4().hex}",
        name="Context item",
        domain="LLM",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


def make_run(environment, resource_type, run_date):
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=InspectionRun.Status.SUCCEEDED,
        started_at=datetime.combine(run_date, datetime.min.time(), tzinfo=timezone.utc),
        finished_at=datetime.combine(run_date, datetime.min.time(), tzinfo=timezone.utc),
    )
    ResourceInspectionSummary.objects.create(
        inspection_run=run,
        resource_type=resource_type,
        assets_total=10,
        assets_covered=10,
        inspection_item_count=1,
        success_item_count=1,
        health_score=90,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary={"health_score_breakdown": {"penalty": 10}},
    )
    return run


@pytest.mark.django_db
def test_resource_context_types_are_supported():
    assert Conversation.ContextType.RESOURCE_TYPE == "RESOURCE_TYPE"
    assert Conversation.ContextType.RESOURCE_RUN == "RESOURCE_RUN"


@pytest.mark.django_db
def test_resource_run_context_is_bounded_and_evidence_backed():
    environment = make_environment()
    resource_type = ResourceType.objects.create(
        code="CONTEXT_RESOURCE",
        name="Context resource",
        asset_selector={"asset_types": ["LLM_INSTANCE"]},
    )
    item = make_item()
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    asset = Asset.objects.create(
        environment=environment,
        external_key="context-llm",
        asset_type=Asset.AssetType.LLM_INSTANCE,
        name="Context LLM",
    )
    run = make_run(environment, resource_type, date(2026, 8, 25))
    item_run = InspectionItemRun.objects.create(
        inspection_run=run,
        inspection_item=item,
        status=InspectionItemRun.Status.SUCCEEDED,
        asset_scope={"asset_ids": [str(asset.id)]},
    )
    finding = Finding.objects.create(
        inspection_item_run=item_run,
        asset=asset,
        finding_code="context.finding",
        title="Context finding",
        category="performance",
        severity="P2",
        source_type=Finding.SourceType.EVENT,
        observed_at=run.finished_at,
    )
    Evidence.objects.create(
        inspection_run=run,
        inspection_item_run=item_run,
        evidence_type=Evidence.EvidenceType.EVENT,
        evidence_key="context.event",
        summary="bounded event reference",
        payload={"raw_log": "x" * 10000},
        source="mock",
    )

    context = build_resource_run_context(
        resource_type_code=resource_type.code,
        inspection_run_id=run.id,
    )

    assert context["context_type"] == "RESOURCE_RUN"
    assert context["current_summary"]["health_score"] == 90.0
    assert context["findings"][0]["id"] == str(finding.id)
    assert context["findings"][0]["title"] == "Context finding"
    assert context["findings"][0]["observed_at"]
    assert context["evidence"][0]["evidence_key"] == "context.event"
    assert context["evidence"][0]["source"] == "mock"
    assert context["evidence"][0]["confidence"] == 1.0
    assert context["inspection_item_results"][0]["status"] == "SUCCEEDED"
    assert context["asset_context"][0]["external_key"] == "context-llm"
    assert context["trend_7d"]
    assert "raw_log" not in json.dumps(context)
    assert len(json.dumps(context).encode()) <= 4096


@pytest.mark.django_db
def test_resource_type_context_contains_window_summaries_and_active_risks():
    environment = make_environment()
    resource_type = ResourceType.objects.create(code="CONTEXT_TREND", name="Trend")
    old_run = make_run(environment, resource_type, date(2026, 8, 20))
    latest_run = make_run(environment, resource_type, date(2026, 8, 25))
    item = make_item()
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    risk = Risk.objects.create(
        environment=environment,
        inspection_item=item,
        risk_key="context-risk",
        fingerprint="context-fingerprint",
        title="Active context risk",
        domain="LLM",
        severity="P2",
        first_seen_at=latest_run.started_at,
        last_seen_at=latest_run.finished_at,
    )
    item_run = InspectionItemRun.objects.create(
        inspection_run=latest_run,
        inspection_item=item,
        status=InspectionItemRun.Status.SUCCEEDED,
    )
    RiskObservation.objects.create(
        risk=risk,
        inspection_run=latest_run,
        inspection_item_run=item_run,
        observed_at=latest_run.finished_at,
        severity="P2",
        status_after=Risk.Status.NEW,
    )

    context = build_resource_type_context(
        environment_id=environment.id,
        resource_type_code=resource_type.code,
        date_from=date(2026, 8, 20),
        date_to=date(2026, 8, 25),
    )

    assert context["context_type"] == "RESOURCE_TYPE"
    assert [row["inspection_run_id"] for row in context["summaries"]] == [
        str(old_run.id),
        str(latest_run.id),
    ]
    assert context["active_risks"][0]["id"] == str(risk.id)
    assert context["active_risks"][0]["title"] == "Active context risk"
    assert context["active_risks"][0]["ai_involved"] is False
