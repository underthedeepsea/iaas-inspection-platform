from datetime import date
import uuid

import pytest

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType
from apps.inspections.services.execution import execute_inspection_run
from apps.inspections.services.trigger import create_manual_inspection_run
from apps.mockdata.services import persist_dataset
from services.mock_generator.generator import generate_dataset


def make_environment():
    return Environment.objects.create(name="Frozen scope", slug=f"frozen-{uuid.uuid4().hex}")


def make_item(code):
    return InspectionItem.objects.create(
        code=code,
        name=code,
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


@pytest.mark.django_db
def test_execution_uses_item_ids_frozen_at_run_creation():
    environment = make_environment()
    dataset = persist_dataset(
        environment,
        generate_dataset(1729, "control_plane_anti_affinity", date(2026, 8, 23)),
    )
    resource_type = ResourceType.objects.get(code="CONTROL_PLANE")
    original_item = make_item("frozen.original")
    InspectionItemResourceType.objects.create(
        resource_type=resource_type,
        inspection_item=original_item,
    )
    run = create_manual_inspection_run(
        environment=environment,
        resource_type_codes=[resource_type.code],
    )
    run.dataset = dataset
    run.save(update_fields=["dataset"])
    original_item_ids = set(run.config_snapshot["resolved_scope"]["inspection_item_ids"])

    new_item = make_item("frozen.added-after-run")
    InspectionItemResourceType.objects.create(
        resource_type=resource_type,
        inspection_item=new_item,
    )

    execute_inspection_run(run)

    assert {
        str(value) for value in run.item_runs.values_list("inspection_item_id", flat=True)
    } == original_item_ids
    item_run = run.item_runs.get()
    assert item_run.asset_scope["resource_types"] == [resource_type.code]
    assert item_run.asset_scope["asset_ids"] == run.config_snapshot["resolved_scope"]["asset_ids"]
