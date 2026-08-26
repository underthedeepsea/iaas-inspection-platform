from datetime import date, datetime, timedelta, timezone
import json
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

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
from apps.risks.models import Risk, RiskObservation


def make_user():
    user = get_user_model().objects.create_user(
        username=f"resource-api-{uuid.uuid4().hex}", password="password"
    )
    group, _ = Group.objects.get_or_create(name="viewer")
    user.groups.add(group)
    return user


def make_environment():
    return Environment.objects.create(name="Resource API", slug=f"resource-{uuid.uuid4().hex}")


def make_item(index):
    return InspectionItem.objects.create(
        code=f"resource.api.item.{index}.{uuid.uuid4().hex}",
        name=f"Resource item {index}",
        domain="LLM",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


def make_run(environment, resource_type, run_date, *, status=InspectionRun.Status.SUCCEEDED):
    run = InspectionRun.objects.create(
        environment=environment,
        run_date=run_date,
        trigger_type=InspectionRun.TriggerType.MANUAL,
        status=status,
        started_at=datetime.combine(run_date, datetime.min.time(), tzinfo=timezone.utc),
        finished_at=datetime.combine(run_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=2),
        config_snapshot={"resolved_scope": {"resource_types": [resource_type.code]}},
    )
    ResourceInspectionSummary.objects.create(
        inspection_run=run,
        resource_type=resource_type,
        assets_total=36,
        assets_covered=35,
        inspection_item_count=7,
        success_item_count=6,
        failed_item_count=1,
        finding_count=8,
        risk_count=4,
        p1_count=0,
        p2_count=1,
        p3_count=2,
        p4_count=1,
        ai_dependent_cases=2,
        ai_investigation_count=2,
        health_score=78,
        status=status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary={"health_score_breakdown": {"penalty": 21, "coverage_penalty": 1}},
    )
    return run


@pytest.mark.django_db
def test_resource_type_list_exposes_latest_summary_metrics():
    environment = make_environment()
    resource_type = ResourceType.objects.create(
        code="RESOURCE_API_LLM",
        name="LLM 推理引擎",
        asset_selector={"asset_types": ["LLM_INSTANCE"]},
    )
    item = make_item(1)
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    Asset.objects.create(
        environment=environment,
        external_key="resource-api-llm",
        asset_type=Asset.AssetType.LLM_INSTANCE,
        name="LLM",
    )
    make_run(environment, resource_type, date(2026, 8, 25))
    client = Client()
    client.force_login(make_user())

    response = client.get("/api/v1/resource-types", {"environment_id": str(environment.id)})

    assert response.status_code == 200
    item_body = next(row for row in response.json()["items"] if row["code"] == resource_type.code)
    assert item_body == {
        **item_body,
        "name": "LLM 推理引擎",
        "asset_count": 36,
        "assets_total": 36,
        "assets_covered": 35,
        "coverage_rate": 35 / 36,
        "inspection_item_count": 7,
        "health_score": 78.0,
        "risk_count": 4,
        "ai_investigation_count": 2,
    }


@pytest.mark.django_db
def test_resource_type_endpoints_accept_environment_slug():
    environment = make_environment()
    client = Client()
    client.force_login(make_user())

    response = client.get("/api/v1/resource-types", {"environment_id": environment.slug})

    assert response.status_code == 200


@pytest.mark.django_db
def test_resource_history_supports_date_filters_pagination_and_newest_first():
    environment = make_environment()
    resource_type = ResourceType.objects.create(code="RESOURCE_API_HISTORY", name="历史")
    older = make_run(environment, resource_type, date(2026, 8, 23))
    newer = make_run(environment, resource_type, date(2026, 8, 25))
    client = Client()
    client.force_login(make_user())

    response = client.get(
        f"/api/v1/resource-types/{resource_type.code}/inspection-history",
        {"environment_id": str(environment.id), "page": 1, "page_size": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["inspection_run_id"] == str(newer.id)
    filtered = client.get(
        f"/api/v1/resource-types/{resource_type.code}/inspection-history",
        {
            "environment_id": str(environment.id),
            "date_from": "2026-08-24",
            "date_to": "2026-08-25",
        },
    )
    assert [row["inspection_run_id"] for row in filtered.json()["items"]] == [str(newer.id)]


@pytest.mark.django_db
def test_resource_run_detail_exposes_counts_major_risks_and_timing():
    environment = make_environment()
    resource_type = ResourceType.objects.create(code="RESOURCE_API_DETAIL", name="详情")
    first_item = make_item(1)
    second_item = make_item(2)
    for item in (first_item, second_item):
        InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    run = make_run(environment, resource_type, date(2026, 8, 25), status=InspectionRun.Status.PARTIAL)
    first_run = InspectionItemRun.objects.create(
        inspection_run=run,
        inspection_item=first_item,
        status=InspectionItemRun.Status.SUCCEEDED,
        asset_scope={"asset_ids": []},
    )
    second_run = InspectionItemRun.objects.create(
        inspection_run=run,
        inspection_item=second_item,
        status=InspectionItemRun.Status.FAILED,
        asset_scope={"asset_ids": []},
    )
    Finding.objects.create(
        inspection_item_run=first_run,
        finding_code="resource.detail.finding",
        title="Major risk",
        category="performance",
        severity="P2",
        source_type=Finding.SourceType.EVENT,
        observed_at=run.finished_at,
    )
    risk = Risk.objects.create(
        environment=environment,
        inspection_item=first_item,
        risk_key="resource-detail-risk",
        fingerprint="resource-detail-fingerprint",
        title="Major risk",
        domain="LLM",
        severity="P2",
        first_seen_at=run.started_at,
        last_seen_at=run.finished_at,
    )
    RiskObservation.objects.create(
        risk=risk,
        inspection_run=run,
        inspection_item_run=first_run,
        observed_at=run.finished_at,
        severity="P2",
        status_after=Risk.Status.NEW,
    )
    client = Client()
    client.force_login(make_user())

    response = client.get(
        f"/api/v1/resource-types/{resource_type.code}/inspection-history/{run.id}",
        {"environment_id": str(environment.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == {"assets_total": 36, "assets_covered": 35, "rate": 35 / 36}
    assert body["inspection_item_status_counts"] == {"SUCCEEDED": 1, "FAILED": 1}
    assert body["finding_count"] == 8
    assert body["risk_count"] == 4
    assert body["severity_counts"] == {"P1": 0, "P2": 1, "P3": 2, "P4": 1}
    assert body["ai_investigation_count"] == 2
    assert body["run"]["status"] == InspectionRun.Status.PARTIAL
    assert body["major_risks"][0]["title"] == "Major risk"
