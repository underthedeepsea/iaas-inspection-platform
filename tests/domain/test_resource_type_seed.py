import pytest

from apps.inspections.models import ResourceType


@pytest.mark.django_db
def test_default_resource_types_exist():
    codes = set(ResourceType.objects.values_list("code", flat=True))

    assert {
        "CONTROL_PLANE",
        "KVM_CLUSTER",
        "K8S_CLUSTER",
        "LLM_RUNTIME",
        "GPU_POOL",
        "HOST",
    }.issubset(codes)
