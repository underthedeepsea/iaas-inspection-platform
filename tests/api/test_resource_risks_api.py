import uuid
from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType
from apps.risks.models import Risk


@pytest.mark.django_db
def test_resource_risks_returns_current_risks_for_selected_resource_type():
    user = get_user_model().objects.create_user(
        username=f"resource-risk-viewer-{uuid.uuid4().hex}",
        password="password",
    )
    group, _ = Group.objects.get_or_create(name="viewer")
    user.groups.add(group)
    environment = Environment.objects.create(name="Resource risks", slug=f"resource-risks-{uuid.uuid4().hex}")
    resource_type = ResourceType.objects.create(
        code="RESOURCE_RISK_TYPE",
        name="Resource risk type",
        asset_selector={"asset_types": [Asset.AssetType.HOST]},
    )
    item = InspectionItem.objects.create(
        code=f"resource-risk-item.{uuid.uuid4().hex}",
        name="Resource risk item",
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=item)
    asset = Asset.objects.create(
        environment=environment,
        external_key="resource-risk-host",
        asset_type=Asset.AssetType.HOST,
        name="Resource risk host",
    )
    risk = Risk.objects.create(
        environment=environment,
        inspection_item=item,
        primary_asset=asset,
        risk_key="resource-risk",
        fingerprint="resource-risk-fingerprint",
        title="资源风险",
        domain="TEST",
        severity="P1",
        status=Risk.Status.PENDING_ACTION,
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )

    client = Client()
    client.force_login(user)
    response = client.get(
        f"/api/v1/resource-types/{resource_type.code}/risks",
        {"environment_id": str(environment.id)},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    row = response.json()["items"][0]
    assert row["risk_id"] == str(risk.id)
    assert row["severity"] == "P1"
    assert row["primary_asset_id"] == str(asset.id)
