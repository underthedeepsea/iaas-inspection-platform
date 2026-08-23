from datetime import date
import uuid

import pytest

from apps.assets.models import Asset
from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.core.models import Environment
from apps.inspections.models import (
    Finding,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
    MockMetric,
)
from apps.mockdata.services import persist_dataset
from services.mock_generator.generator import generate_dataset


BUSINESS_DATE = date(2026, 8, 23)


def create_environment():
    return Environment.objects.create(
        name="Inspection execution test",
        slug=f"inspection-execution-{uuid.uuid4().hex}",
    )


def create_dataset(environment, scenario):
    return persist_dataset(
        environment,
        generate_dataset(1729, scenario, BUSINESS_DATE),
    )


def create_run(environment, dataset):
    return InspectionRun.objects.create(
        environment=environment,
        dataset=dataset,
        run_date=BUSINESS_DATE,
        trigger_type=InspectionRun.TriggerType.MANUAL,
    )


def create_item(*, code, execution_mode, code_status, required_claims):
    return InspectionItem.objects.create(
        code=code,
        name=code,
        domain="TEST",
        execution_mode=execution_mode,
        code_status=code_status,
        required_claims=required_claims,
    )


def register_resolver(
    claim,
    *,
    resolver_code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    version_status=CapabilityVersion.Status.ACTIVE,
    capability_status=Capability.Status.ACTIVE,
    binding_enabled=True,
):
    resolver_item = create_item(
        code=f"resolver.{uuid.uuid4().hex}",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=resolver_code_status,
        required_claims=[claim],
    )
    capability = Capability.objects.create(
        capability_id=f"capability.{uuid.uuid4().hex}",
        name=f"Resolver for {claim}",
        domain="TEST",
        status=capability_status,
    )
    version = CapabilityVersion.objects.create(
        capability=capability,
        version="1.0.0",
        implementation_type=CapabilityVersion.ImplementationType.RULE,
        status=version_status,
        resolves=[claim],
    )
    InspectionCapabilityBinding.objects.create(
        inspection_item=resolver_item,
        capability_version=version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
        enabled=binding_enabled,
    )
    return version


@pytest.mark.django_db
def test_control_plane_anti_affinity_is_code_only_and_persists_literal_finding_and_coverage():
    environment = create_environment()
    dataset = create_dataset(environment, "control_plane_anti_affinity")
    claim = "topology.control_plane_anti_affinity"
    register_resolver(claim)
    item = create_item(
        code="topology.control_plane_anti_affinity",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        required_claims=[claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item)

    item_run.refresh_from_db()
    assert item_run.status == InspectionItemRun.Status.SUCCEEDED
    assert item_run.ai_admission_status == InspectionItemRun.AIAdmissionStatus.NO_AI
    assert item_run.summary["required_claims"] == [claim]
    assert item_run.summary["resolved_claims"] == [claim]
    assert item_run.summary["unresolved_claims"] == []
    assert item_run.summary["material_claim_gaps"] == []
    assert item_run.summary["code_coverage_percent"] == 100.0
    assert item_run.asset_scope == {
        "asset_keys": sorted(
            [
                "cluster-0",
                "host-control-0",
                "host-worker-0",
                "vm-0",
                "control-plane-0",
                "control-plane-1",
                "gpu-0",
                "llm-0",
            ]
        )
    }
    assert item_run.pk == InspectionItemRun.objects.get(
        inspection_run=run,
        inspection_item=item,
    ).pk

    finding = Finding.objects.get(inspection_item_run=item_run)
    assert {
        "finding_code": finding.finding_code,
        "title": finding.title,
        "category": finding.category,
        "severity": finding.severity,
        "status": finding.status,
        "source_type": finding.source_type,
    } == {
        "finding_code": "CONTROL_PLANE_ANTI_AFFINITY",
        "title": "控制面反亲和违规",
        "category": "topology",
        "severity": "P2",
        "status": Finding.Status.ACTIVE,
        "source_type": Finding.SourceType.EVENT,
    }
    assert finding.value == {
        "anti_affinity_key": "control-plane",
        "host": "host-control-0",
        "members": ["control-plane-0", "control-plane-1"],
    }
    run.refresh_from_db()
    assert run.risk_count == 0


@pytest.mark.django_db
def test_asset_scope_uses_mutated_persisted_assets_instead_of_regenerating_dataset():
    environment = create_environment()
    dataset = create_dataset(environment, "control_plane_anti_affinity")
    claim = "topology.control_plane_anti_affinity"
    register_resolver(claim)
    renamed_asset = Asset.objects.get(
        environment=environment,
        external_key="control-plane-1",
    )
    renamed_asset.external_key = "persisted-control-plane-renamed"
    renamed_asset.save(update_fields=["external_key"])
    Asset.objects.get(environment=environment, external_key="gpu-0").delete()
    item = create_item(
        code="topology.control_plane_anti_affinity.persisted-scope",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        required_claims=[claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item)

    assert item_run.asset_scope == {
        "asset_keys": sorted(
            [
                "cluster-0",
                "control-plane-0",
                "host-control-0",
                "host-worker-0",
                "llm-0",
                "persisted-control-plane-renamed",
                "vm-0",
            ]
        )
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "resolver_state",
    ["missing", "shadow", "inactive", "disabled"],
)
def test_non_active_registry_resolver_does_not_resolve_detector_claim(resolver_state):
    environment = create_environment()
    dataset = create_dataset(environment, "llm_scheduler_pressure")
    status_claim = "llm.performance.status"
    gap_claim = "llm.performance.degradation_category"
    if resolver_state == "shadow":
        register_resolver(
            status_claim,
            resolver_code_status=InspectionItem.CodeStatus.SHADOW,
            version_status=CapabilityVersion.Status.SHADOW,
        )
    elif resolver_state == "inactive":
        register_resolver(status_claim, capability_status=Capability.Status.DISABLED)
    elif resolver_state == "disabled":
        register_resolver(status_claim, binding_enabled=False)
    item = create_item(
        code=f"llm.performance.registry.{resolver_state}",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
        required_claims=[status_claim, gap_claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item)

    assert item_run.summary["resolved_claims"] == []
    assert item_run.summary["unresolved_claims"] == [status_claim, gap_claim]
    assert item_run.summary["material_claim_gaps"] == [status_claim, gap_claim]
    assert item_run.ai_admission_status == InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE


@pytest.mark.django_db
def test_registry_without_resolve_method_does_not_resolve_detector_claim():
    environment = create_environment()
    dataset = create_dataset(environment, "llm_scheduler_pressure")
    status_claim = "llm.performance.status"
    gap_claim = "llm.performance.degradation_category"
    register_resolver(status_claim)
    item = create_item(
        code="llm.performance.registry.no-resolve",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
        required_claims=[status_claim, gap_claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item, registry=object())

    assert item_run.summary["resolved_claims"] == []
    assert item_run.summary["unresolved_claims"] == [status_claim, gap_claim]
    assert item_run.summary["material_claim_gaps"] == [status_claim, gap_claim]


@pytest.mark.django_db
def test_ready_dataset_with_deleted_queue_rows_is_data_invalid_and_never_ai_eligible():
    environment = create_environment()
    dataset = create_dataset(environment, "llm_scheduler_pressure")
    MockMetric.objects.filter(dataset=dataset, metric_name="queue_depth").delete()
    dataset.generator_config = {**dataset.generator_config, "missing_data": []}
    dataset.save(update_fields=["generator_config"])
    status_claim = "llm.performance.status"
    gap_claim = "llm.performance.degradation_category"
    register_resolver(status_claim)
    item = create_item(
        code="llm.performance.deleted-queue",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
        required_claims=[status_claim, gap_claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item)

    item_run.refresh_from_db()
    assert dataset.status == dataset.Status.READY
    assert item_run.ai_admission_status == InspectionItemRun.AIAdmissionStatus.DATA_INVALID
    assert item_run.summary["data_valid"] is False
    assert item_run.summary["missing_data"] == ["queue_depth"]
    assert item_run.summary["resolved_claims"] == []
    assert item_run.summary["material_claim_gaps"] == []
    finding = Finding.objects.get(inspection_item_run=item_run)
    assert finding.finding_code == "DATA_INCOMPLETE"


@pytest.mark.django_db
def test_llm_scheduler_pressure_leaves_only_degradation_category_as_ai_claim_gap():
    environment = create_environment()
    dataset = create_dataset(environment, "llm_scheduler_pressure")
    status_claim = "llm.performance.status"
    gap_claim = "llm.performance.degradation_category"
    register_resolver(status_claim)
    item = create_item(
        code="llm.performance",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
        required_claims=[status_claim, gap_claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item)

    item_run.refresh_from_db()
    assert item_run.status == InspectionItemRun.Status.SUCCEEDED
    assert item_run.ai_admission_status == InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE
    assert item_run.summary["required_claims"] == [status_claim, gap_claim]
    assert item_run.summary["resolved_claims"] == [status_claim]
    assert item_run.summary["unresolved_claims"] == [gap_claim]
    assert item_run.summary["material_claim_gaps"] == [gap_claim]
    assert item_run.summary["code_coverage_percent"] == 50.0

    finding = Finding.objects.get(inspection_item_run=item_run)
    assert finding.finding_code == "LLM_PERFORMANCE_DEGRADED"
    assert finding.title == "LLM 性能退化"
    assert finding.category == "performance"
    assert finding.severity == "P2"
    assert finding.source_type == Finding.SourceType.EVENT
    assert finding.value == {
        "signals": ["ttft_ms", "queue_depth", "gpu_util_percent"],
        "ttft_ms": {"first": 99.0, "last": 201.0},
        "queue_depth": {"first": 2.0, "last": 16.0},
        "gpu_util_percent": {"first": 85.0, "last": 63.0},
    }


@pytest.mark.django_db
def test_data_incomplete_is_invalid_and_never_ai_eligible_when_required_evidence_is_missing():
    environment = create_environment()
    dataset = create_dataset(environment, "data_incomplete")
    status_claim = "llm.performance.status"
    gap_claim = "llm.performance.degradation_category"
    register_resolver(status_claim)
    item = create_item(
        code="llm.performance.incomplete",
        execution_mode=InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK,
        code_status=InspectionItem.CodeStatus.PARTIAL_CODE,
        required_claims=[status_claim, gap_claim],
    )
    run = create_run(environment, dataset)

    from apps.inspections.services.execution import execute_inspection_item

    item_run = execute_inspection_item(run, item)

    item_run.refresh_from_db()
    assert item_run.status == InspectionItemRun.Status.SUCCEEDED
    assert item_run.ai_admission_status == InspectionItemRun.AIAdmissionStatus.DATA_INVALID
    assert item_run.summary["data_valid"] is False
    assert item_run.summary["missing_data"] == ["queue_depth"]
    assert item_run.summary["resolved_claims"] == []
    assert item_run.summary["unresolved_claims"] == [status_claim, gap_claim]
    assert item_run.summary["material_claim_gaps"] == []

    finding = Finding.objects.get(inspection_item_run=item_run)
    assert finding.finding_code == "DATA_INCOMPLETE"
    assert finding.category == "data_quality"
    assert finding.status == Finding.Status.INVALID
    assert finding.value == {"missing_data": ["queue_depth"]}
