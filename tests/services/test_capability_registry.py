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
def test_llm_capability_resolution_uses_active_current_version_only():
    from services.plugin_runtime.registry import CapabilityRegistry

    capability = Capability.objects.create(
        capability_id=f"capability.current.{uuid.uuid4().hex}",
        name="Current version resolver",
        domain="LLM",
        read_only=True,
    )
    old = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        resolves=["degradation_category"],
    )
    current = CapabilityVersion.objects.create(
        capability=capability,
        version="2.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        resolves=["degradation_category"],
    )
    capability.current_version = current
    capability.save(update_fields=["current_version"])

    assert CapabilityRegistry().resolve_capability(
        capability.capability_id,
        claim="degradation_category",
    ) == current
    assert old != current


@pytest.mark.django_db
def test_atomic_llm_dispatch_rechecks_read_only_current_version_before_backend():
    from services.plugin_runtime.executor import ExecutionOrigin
    from services.plugin_runtime.errors import ReadOnlyCapabilityError
    from services.plugin_runtime.registry import CapabilityRegistry

    capability = Capability.objects.create(
        capability_id=f"capability.atomic.{uuid.uuid4().hex}",
        name="Atomic resolver",
        domain="LLM",
        read_only=False,
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        input_schema={"type": "object"},
        resolves=["degradation_category"],
    )
    capability.current_version = version
    capability.save(update_fields=["current_version"])

    class MustNotRun:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("backend must not be dispatched")

    with pytest.raises(ReadOnlyCapabilityError):
        CapabilityRegistry().execute_readonly(
            capability.capability_id,
            claim="degradation_category",
            payload={},
            executor=MustNotRun(),
            origin=ExecutionOrigin.LLM,
        )


@pytest.mark.django_db
def test_atomic_llm_dispatch_rejects_expected_version_after_current_switch_before_backend():
    from services.plugin_runtime.errors import PluginExecutionError
    from services.plugin_runtime.executor import ExecutionOrigin
    from services.plugin_runtime.registry import CapabilityRegistry

    capability = Capability.objects.create(
        capability_id=f"capability.switch.{uuid.uuid4().hex}",
        name="Switching resolver",
        domain="LLM",
        read_only=True,
    )
    old = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        input_schema={"type": "object"},
        resolves=["degradation_category"],
    )
    current = CapabilityVersion.objects.create(
        capability=capability,
        version="2.0.0",
        implementation_type="RULE",
        status=CapabilityVersion.Status.ACTIVE,
        input_schema={"type": "object"},
        resolves=["degradation_category"],
    )
    capability.current_version = current
    capability.save(update_fields=["current_version"])

    class MustNotRun:
        def __init__(self):
            self.calls = 0

        def execute(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("backend must not be dispatched")

    executor = MustNotRun()
    with pytest.raises(PluginExecutionError):
        CapabilityRegistry().execute_readonly(
            capability.capability_id,
            claim="degradation_category",
            payload={},
            executor=executor,
            origin=ExecutionOrigin.LLM,
            expected_capability_version_id=str(old.pk),
        )
    assert executor.calls == 0


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
