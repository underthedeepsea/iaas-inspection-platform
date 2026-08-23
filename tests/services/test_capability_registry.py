import uuid

import pytest

from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.inspections.models import InspectionItem


def create_item(code_status):
    return InspectionItem.objects.create(
        code=f"capability.registry.{uuid.uuid4().hex}",
        name="Capability registry test",
        domain="NETWORK",
        execution_mode="CODE_ONLY",
        code_status=code_status,
    )


def create_resolver(*, code_status, version_status):
    capability = Capability.objects.create(
        capability_id=f"capability.registry.{uuid.uuid4().hex}",
        name="RX path resolver",
        domain="NETWORK",
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type="RULE",
        status=version_status,
        resolves=["network.rx_path_pressure"],
    )
    InspectionCapabilityBinding.objects.create(
        inspection_item=create_item(code_status),
        capability_version=version,
        role="RESOLVER",
        claim="network.rx_path_pressure",
    )
    return version


@pytest.mark.django_db
def test_resolve_claim_returns_enabled_code_active_resolver():
    from services.plugin_runtime.registry import CapabilityRegistry

    expected = create_resolver(code_status="CODE_ACTIVE", version_status="ACTIVE")

    assert CapabilityRegistry().resolve("network.rx_path_pressure") == expected


@pytest.mark.django_db
def test_shadow_resolver_is_not_formally_resolved_but_is_available_to_shadow_runner():
    from services.plugin_runtime.registry import CapabilityRegistry

    shadow = create_resolver(code_status="SHADOW", version_status="SHADOW")
    registry = CapabilityRegistry()

    assert registry.resolve("network.rx_path_pressure") is None
    assert registry.resolve_shadow("network.rx_path_pressure") == shadow


@pytest.mark.django_db
@pytest.mark.parametrize("disabled_part", ["binding", "item", "capability"])
def test_resolve_excludes_disabled_bindings_items_and_capabilities(disabled_part):
    from services.plugin_runtime.registry import CapabilityRegistry

    expected = create_resolver(code_status="CODE_ACTIVE", version_status="ACTIVE")
    binding = InspectionCapabilityBinding.objects.get(capability_version=expected)

    if disabled_part == "binding":
        binding.enabled = False
        binding.save(update_fields=["enabled"])
    elif disabled_part == "item":
        binding.inspection_item.enabled = False
        binding.inspection_item.save(update_fields=["enabled"])
    else:
        expected.capability.status = Capability.Status.DISABLED
        expected.capability.save(update_fields=["status"])

    assert CapabilityRegistry().resolve("network.rx_path_pressure") is None
