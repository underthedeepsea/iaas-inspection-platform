import uuid

import pytest

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType
from apps.inspections.services.scope import (
    UnknownResourceType,
    UnsupportedAssetSelector,
    resolve_scope,
    scope_to_snapshot,
)


def make_environment():
    return Environment.objects.create(name="Scope test", slug=f"scope-{uuid.uuid4().hex}")


def make_item(code):
    return InspectionItem.objects.create(
        code=code,
        name=code,
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


@pytest.mark.django_db
def test_resolve_scope_rejects_unknown_resource_type():
    environment = make_environment()

    with pytest.raises(UnknownResourceType):
        resolve_scope(environment_id=environment.id, resource_type_codes=["NO_SUCH_TYPE"])


@pytest.mark.django_db
def test_resolve_scope_returns_stable_sorted_ids():
    environment = make_environment()
    first_asset = Asset.objects.create(
        environment=environment,
        external_key="asset-a",
        asset_type=Asset.AssetType.LLM_INSTANCE,
        name="asset-a",
    )
    second_asset = Asset.objects.create(
        environment=environment,
        external_key="asset-b",
        asset_type=Asset.AssetType.LLM_INSTANCE,
        name="asset-b",
    )
    resource_type = ResourceType.objects.create(
        code="LLM_RUNTIME_SCOPE",
        name="LLM",
        asset_selector={"asset_types": ["LLM_INSTANCE"]},
    )
    first_item = make_item("scope.first")
    second_item = make_item("scope.second")
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=first_item)
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=second_item)

    scope = resolve_scope(
        environment_id=environment.id,
        resource_type_codes=[resource_type.code],
    )

    assert scope.resource_type_codes == (resource_type.code,)
    assert scope.inspection_item_ids == tuple(sorted((first_item.id, second_item.id), key=str))
    assert scope.asset_ids == tuple(sorted((first_asset.id, second_asset.id), key=str))
    assert scope.asset_count == 2
    assert scope_to_snapshot(scope) == {
        "resource_types": [resource_type.code],
        "inspection_item_ids": [str(value) for value in scope.inspection_item_ids],
        "asset_ids": [str(value) for value in scope.asset_ids],
        "asset_count": 2,
    }


@pytest.mark.django_db
def test_resolve_scope_rejects_unsupported_selector_keys():
    environment = make_environment()
    ResourceType.objects.create(
        code="BAD_SELECTOR",
        name="Bad selector",
        asset_selector={"selector": {"team": "llm"}},
    )

    with pytest.raises(UnsupportedAssetSelector):
        resolve_scope(environment_id=environment.id, resource_type_codes=["BAD_SELECTOR"])


@pytest.mark.django_db
def test_resolve_scope_matches_supported_labels_exactly():
    environment = make_environment()
    kvm = Asset.objects.create(
        environment=environment,
        external_key="cluster-kvm",
        asset_type=Asset.AssetType.CLUSTER,
        name="KVM",
        labels={"platform": "kvm", "zone": "a"},
    )
    kubernetes = Asset.objects.create(
        environment=environment,
        external_key="cluster-k8s",
        asset_type=Asset.AssetType.CLUSTER,
        name="Kubernetes",
        labels={"platform": "kubernetes", "zone": "a"},
    )
    resource_type = ResourceType.objects.create(
        code="KVM_CLUSTER_SCOPE",
        name="KVM",
        asset_selector={"asset_types": ["CLUSTER"], "labels": {"platform": "kvm"}},
    )
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=make_item("scope.kvm"))

    scope = resolve_scope(
        environment_id=environment.id,
        resource_type_codes=[resource_type.code],
    )

    assert scope.asset_ids == (kvm.id,)
    assert kubernetes.id not in scope.asset_ids
