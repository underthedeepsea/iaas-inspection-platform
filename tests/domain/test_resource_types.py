import pytest
from django.db import IntegrityError, transaction

from apps.inspections.models import (
    InspectionItem,
    InspectionItemResourceType,
    ResourceType,
)
from apps.inspections.services.resource_types import (
    get_active_resource_types,
    resolve_inspection_items,
)


def make_item(code):
    return InspectionItem.objects.create(
        code=code,
        name=code,
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


@pytest.mark.django_db
def test_resource_type_code_is_unique():
    ResourceType.objects.create(code="LLM_RUNTIME", name="LLM 推理引擎")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResourceType.objects.create(code="LLM_RUNTIME", name="duplicate")


@pytest.mark.django_db
def test_resource_type_can_bind_multiple_inspection_items():
    resource_type = ResourceType.objects.create(code="LLM_RUNTIME", name="LLM 推理引擎")
    first = make_item("llm.performance")
    second = make_item("llm.scheduler")

    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=first)
    InspectionItemResourceType.objects.create(resource_type=resource_type, inspection_item=second)

    assert resource_type.inspection_items.count() == 2


@pytest.mark.django_db
def test_resolve_inspection_items_only_returns_enabled_bound_items():
    active = ResourceType.objects.create(code="LLM_RUNTIME", name="LLM 推理引擎")
    disabled = ResourceType.objects.create(code="HOST", name="主机", enabled=False)
    included = make_item("llm.included")
    disabled_item = make_item("llm.disabled")
    disabled_item.enabled = False
    disabled_item.save(update_fields=["enabled"])
    InspectionItemResourceType.objects.create(resource_type=active, inspection_item=included)
    InspectionItemResourceType.objects.create(resource_type=active, inspection_item=disabled_item)

    assert list(resolve_inspection_items(["LLM_RUNTIME"]).values_list("code", flat=True)) == [
        "llm.included"
    ]
    assert list(resolve_inspection_items([disabled.code])) == []


@pytest.mark.django_db
def test_get_active_resource_types_is_stable_and_excludes_disabled_types():
    ResourceType.objects.create(code="HOST", name="主机", enabled=True, sort_order=20)
    ResourceType.objects.create(code="GPU_POOL", name="GPU 资源", enabled=True, sort_order=10)
    ResourceType.objects.create(code="KVM_CLUSTER", name="KVM 集群", enabled=False, sort_order=1)

    values = get_active_resource_types("unused-environment")

    assert [value.code for value in values] == ["GPU_POOL", "HOST"]
