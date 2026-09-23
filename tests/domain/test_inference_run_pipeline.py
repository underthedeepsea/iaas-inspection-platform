from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inspections.models import CheckResult, InspectionItem, InspectionItemResourceType, InspectionItemRun, ResourceType
from apps.inspections.services.execution import execute_inspection_run
from apps.inspections.services.trigger import create_manual_inspection_run
from apps.risks.models import Risk, RiskObservation, RiskStatusHistory
from apps.risks.services.correlation import correlate_run
from apps.risks.services.lifecycle import mark_handled
from apps.risks.services.reverify import reverify_pending_risks


def _snapshot(environment, asset, status):
    end = timezone.now() - timedelta(seconds=10)
    row = InferencePerformanceSnapshot.objects.create(
        environment=environment,
        asset=asset,
        source='test-monitor',
        sample_id=str(uuid.uuid4()),
        engine_id=asset.external_key,
        engine_type='vllm',
        model_name='Qwen/Test',
        window_start=end - timedelta(minutes=1),
        window_end=end,
        metrics={},
    )
    row.evaluation = {
        'schema_version': 1,
        'plugin': {'id': 'inference-performance', 'version': '1.0.0', 'rule_code': 'llm.performance_profile', 'operation': 'evaluate'},
        'input': {'snapshot_id': str(row.pk)},
        'quality': {'state': 'READY', 'pending_confirmation': False},
        'status': status,
        'resolved_policy': {},
        'policy_source': {'level': 'DEFAULT', 'config_hash': 'sha256:test'},
    }
    row.save(update_fields=['evaluation'])
    return row


@pytest.mark.django_db
def test_real_run_freezes_per_asset_result_and_correlates_valid_fail():
    environment = Environment.objects.create(name='Real run', slug=f'real-run-{uuid.uuid4().hex}')
    resource = ResourceType.objects.create(
        code=f'LLM_TEST_{uuid.uuid4().hex[:8].upper()}',
        name='Inference runtime',
        asset_selector={'asset_types': ['LLM_INSTANCE'], 'labels': {'input_source': 'INFERENCE_SNAPSHOT'}},
    )
    item = InspectionItem.objects.create(
        code='llm.performance_profile', name='Performance', domain='llm',
        execution_mode='CODE_ONLY', code_status='CODE_ACTIVE',
    )
    InspectionItemResourceType.objects.create(resource_type=resource, inspection_item=item)
    assets = [Asset.objects.create(
        environment=environment, external_key=f'inference:{index}', asset_type='LLM_INSTANCE',
        name=f'Engine {index}', labels={'input_source': 'INFERENCE_SNAPSHOT', 'engine_id': f'inference:{index}', 'engine_type': 'vllm', 'model_name': 'Qwen/Test'},
    ) for index in range(3)]
    bad = _snapshot(environment, assets[1], 'WARNING')
    good = _snapshot(environment, assets[2], 'NORMAL')
    run = create_manual_inspection_run(environment=environment, resource_type_codes=[resource.code])
    assert run.dataset_id is None
    frozen = run.config_snapshot['input']['snapshots']
    assert frozen[str(assets[0].pk)] is None
    assert frozen[str(assets[1].pk)]['snapshot_id'] == str(bad.pk)
    assert frozen[str(assets[2].pk)]['snapshot_id'] == str(good.pk)
    # A later upload cannot alter this run's selected facts.
    _snapshot(environment, assets[0], 'CRITICAL')
    execute_inspection_run(run)
    assert dict(CheckResult.objects.filter(inspection_run=run).values_list('asset_id', 'status')) == {
        assets[0].pk: 'UNKNOWN', assets[1].pk: 'FAIL', assets[2].pk: 'PASS',
    }
    CheckResult.objects.filter(inspection_run=run, asset=assets[0]).update(status='ERROR')
    InspectionItemRun.objects.filter(inspection_run=run).update(status='FAILED')
    correlate_run(run)
    risk = Risk.objects.get(environment=environment)
    assert risk.primary_asset_id == assets[1].pk
    assert risk.severity == 'P2'

    # A new normal measurement only recovers the handled risk when its window
    # starts after handling and it has a distinct snapshot identity.
    RiskObservation.objects.filter(risk=risk).update(created_at=timezone.now() - timedelta(minutes=3))
    mark_handled(risk)
    RiskStatusHistory.objects.filter(risk=risk, to_status=Risk.Status.PENDING_REVERIFY).update(created_at=timezone.now() - timedelta(minutes=2))
    _snapshot(environment, assets[1], 'NORMAL')
    later = create_manual_inspection_run(environment=environment, resource_type_codes=[resource.code])
    execute_inspection_run(later)
    later.status = later.Status.SUCCEEDED
    later.finished_at = timezone.now()
    later.save(update_fields=['status', 'finished_at'])
    recovered = reverify_pending_risks(later)
    assert [entry.pk for entry in recovered] == [risk.pk]
