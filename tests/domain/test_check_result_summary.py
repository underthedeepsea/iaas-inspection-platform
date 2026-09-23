from datetime import date

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import CheckResult, InspectionItem, InspectionItemRun, InspectionItemResourceType, InspectionRun, ResourceType
from apps.inspections.services.resource_summary import build_resource_summaries


@pytest.mark.django_db
@pytest.mark.parametrize(
    'statuses,covered,health,state,applicable,conclusive,rate',
    [
        ([], 0, None, 'UNKNOWN', 0, 0, None),
        (['UNKNOWN'], 1, None, 'UNKNOWN', 1, 0, 0),
        (['ERROR'], 1, None, 'UNKNOWN', 1, 0, 0),
        (['NOT_APPLICABLE'], 1, None, 'UNKNOWN', 0, 0, None),
        (['PASS'], 1, 100, 'READY', 1, 1, 1),
    ],
)
def test_summary_counts_actual_results_not_planned_scope(statuses, covered, health, state, applicable, conclusive, rate):
    env = Environment.objects.create(name='Summary',slug='summary')
    asset = Asset.objects.create(environment=env, external_key='a', name='a', asset_type='LLM_INSTANCE', labels={'workload':'llm'})
    item = InspectionItem.objects.create(code='llm.ttft_slo', name='TTFT', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    resource = ResourceType.objects.get(code='LLM_RUNTIME')
    InspectionItemResourceType.objects.create(inspection_item=item, resource_type=resource)
    run = InspectionRun.objects.create(environment=env, run_date=date.today(), trigger_type='MANUAL', config_snapshot={'resolved_scope':{'asset_ids':[str(asset.pk)],'resource_types':['LLM_RUNTIME']}})
    item_run = InspectionItemRun.objects.create(inspection_run=run, inspection_item=item, status='FAILED' if not statuses else 'SUCCEEDED', asset_scope={'asset_ids':[str(asset.pk)]})
    for status in statuses:
        CheckResult.objects.create(inspection_run=run, inspection_item_run=item_run, asset=asset, status=status, checked_at=timezone.now())
    summary = build_resource_summaries(run)[0]
    assert summary.assets_total == 1
    assert summary.assets_covered == covered
    assert summary.health_score == health
    assert summary.summary['data_state'] == state
    assert summary.summary['unknown_assets'] == statuses.count('UNKNOWN')
    assert summary.summary['error_assets'] == statuses.count('ERROR')
    assert summary.summary['not_applicable_assets'] == statuses.count('NOT_APPLICABLE')
    assert summary.summary['applicable_assets'] == applicable
    assert summary.summary['conclusive_assets'] == conclusive
    assert summary.summary['conclusive_rate'] == rate


@pytest.mark.django_db
def test_one_pass_and_ninety_nine_unknowns_cannot_show_perfect_health():
    env = Environment.objects.create(name='Partial', slug='partial')
    resource = ResourceType.objects.create(code='PARTIAL_LLM', name='Partial LLM', asset_selector={'asset_types': ['LLM_INSTANCE']})
    item = InspectionItem.objects.create(code='partial.performance', name='Performance', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    InspectionItemResourceType.objects.create(inspection_item=item, resource_type=resource)
    assets = [Asset.objects.create(environment=env, external_key=f'engine-{index}', name=f'Engine {index}', asset_type='LLM_INSTANCE') for index in range(100)]
    run = InspectionRun.objects.create(
        environment=env, run_date=date.today(), trigger_type='MANUAL',
        config_snapshot={'resolved_scope': {'resource_types': [resource.code], 'asset_ids': [str(asset.pk) for asset in assets]}},
    )
    item_run = InspectionItemRun.objects.create(inspection_run=run, inspection_item=item, status='SUCCEEDED', asset_scope={'asset_ids': [str(asset.pk) for asset in assets], 'resource_types': [resource.code]})
    CheckResult.objects.bulk_create([
        CheckResult(inspection_run=run, inspection_item_run=item_run, asset=asset, status='PASS' if index == 0 else 'UNKNOWN', checked_at=timezone.now())
        for index, asset in enumerate(assets)
    ])
    summary = build_resource_summaries(run)[0]
    assert summary.assets_covered == 100
    assert summary.summary['pass_count'] == 1
    assert summary.summary['unknown_assets'] == 99
    assert summary.summary['conclusive_assets'] == 1
    assert summary.summary['conclusive_rate'] == 0.01
    assert summary.summary['data_state'] == 'PARTIAL'
    assert summary.health_score is None
