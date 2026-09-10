from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import CheckResult, InspectionItem, InspectionItemRun, InspectionRun


@pytest.fixture
def check_context(db):
    env = Environment.objects.create(name='Checks', slug='checks')
    asset = Asset.objects.create(environment=env, external_key='a', name='a', asset_type='LLM_INSTANCE')
    item = InspectionItem.objects.create(code='llm.ttft_slo', name='TTFT', domain='llm', execution_mode='CODE_ONLY', code_status='CODE_ACTIVE')
    run = InspectionRun.objects.create(environment=env, run_date=date(2026, 9, 10), trigger_type='MANUAL')
    item_run = InspectionItemRun.objects.create(inspection_run=run, inspection_item=item)
    return dict(inspection_run=run, inspection_item_run=item_run, asset=asset, checked_at=timezone.now())


def test_one_item_run_has_one_result_per_asset(check_context):
    CheckResult.objects.create(**check_context, status='PASS')
    with pytest.raises(IntegrityError), transaction.atomic():
        CheckResult.objects.create(**check_context, status='FAIL')


@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'UNKNOWN', 'ERROR', 'NOT_APPLICABLE'])
def test_check_result_accepts_pass_fail_unknown_error_na(check_context, status):
    result = CheckResult.objects.create(**check_context, status=status)
    result.full_clean(exclude=['summary', 'observed_value', 'expected_value', 'evidence'])
    assert CheckResult.objects.get(pk=result.pk).status == status


@pytest.mark.parametrize('field', ['inspection_run', 'inspection_item_run', 'asset'])
def test_check_result_requires_inspection_run_item_run_and_asset(check_context, field):
    check_context[field] = None
    with pytest.raises(IntegrityError), transaction.atomic():
        CheckResult.objects.create(**check_context, status='PASS')
