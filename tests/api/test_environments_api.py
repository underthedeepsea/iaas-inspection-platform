import uuid

import pytest
from django.test import Client

from apps.assets.models import Asset
from apps.core.models import Environment


@pytest.mark.django_db
def test_environment_catalog_returns_real_environment_ids_and_data_counts():


    environment = Environment.objects.create(
        name="真实测试环境",
        slug=f"real-env-{uuid.uuid4().hex}",
        environment_type=Environment.EnvironmentType.TEST,
    )
    Asset.objects.create(
        environment=environment,
        external_key="environment-asset",
        asset_type=Asset.AssetType.HOST,
        name="Environment host",
    )

    client = Client()

    response = client.get("/api/v1/environments")

    assert response.status_code == 200
    item = next(row for row in response.json()["items"] if row["id"] == str(environment.id))
    assert item["slug"] == environment.slug
    assert item["name"] == "真实测试环境"
    assert item["environment_type"] == Environment.EnvironmentType.TEST
    assert item["assets_count"] == 1
