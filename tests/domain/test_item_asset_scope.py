import uuid

import pytest

from apps.core.models import Environment
from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType
from apps.inspections.services.trigger import create_manual_inspection_run


def make_item(code):
    return InspectionItem.objects.create(
        code=code,
        name=code,
        domain="TEST",
        execution_mode=InspectionItem.ExecutionMode.CODE_ONLY,
        code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
    )


@pytest.mark.django_db
def test_manual_run_freezes_asset_scope_for_each_inspection_item():
    environment = Environment.objects.create(
        name="Item scope",
        slug=f"item-scope-{uuid.uuid4().hex}",
    )
    control_plane = ResourceType.objects.get(code="CONTROL_PLANE")
    llm_runtime = ResourceType.objects.get(code="LLM_RUNTIME")
    control_item = make_item(f"item.scope.control.{uuid.uuid4().hex}")
    llm_item = make_item(f"item.scope.llm.{uuid.uuid4().hex}")
    InspectionItemResourceType.objects.create(
        resource_type=control_plane,
        inspection_item=control_item,
    )
    InspectionItemResourceType.objects.create(
        resource_type=llm_runtime,
        inspection_item=llm_item,
    )

    run = create_manual_inspection_run(
        environment=environment,
        resource_type_codes=[control_plane.code, llm_runtime.code],
    )

    control_scope = run.item_runs.get(inspection_item=control_item).asset_scope
    llm_scope = run.item_runs.get(inspection_item=llm_item).asset_scope
    assert control_scope["resource_types"] == [control_plane.code]
    assert llm_scope["resource_types"] == [llm_runtime.code]
    # CONTROL_PLANE and LLM_RUNTIME intentionally share POD assets under the
    # v0.2 resource composition contract.
    assert set(control_scope["asset_ids"]) & set(llm_scope["asset_ids"])
    assert set(control_scope["asset_ids"]) | set(llm_scope["asset_ids"]) == set(
        run.config_snapshot["resolved_scope"]["asset_ids"]
    )
