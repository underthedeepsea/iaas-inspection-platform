from datetime import date

import pytest
from django.utils import timezone

from apps.assets.models import Asset
from apps.core.models import Environment
from apps.inspections.models import MockDataset, MockMetric, MockEvent
from apps.inspections.services.input_reader import InspectionInputReader


@pytest.mark.django_db
def test_reader_never_returns_metrics_or_events_outside_frozen_scope():
    env = Environment.objects.create(name='Reader', slug='reader')
    other = Environment.objects.create(name='Other', slug='other')
    assets = [Asset.objects.create(environment=e, external_key=str(i), name=str(i), asset_type='LLM_INSTANCE') for i, e in enumerate([env, env, other])]
    dataset = MockDataset.objects.create(environment=env, seed=1, scenario='any', dataset_date=date.today())
    second = MockDataset.objects.create(environment=env, seed=2, scenario='any', dataset_date=date.today())
    for source in [dataset, second]:
        for asset in assets:
            MockMetric.objects.create(dataset=source, asset=asset, metric_name='ttft_ms', value=999, ts=timezone.now())
            MockEvent.objects.create(dataset=source, asset=asset, event_type='TEST', ts=timezone.now())
    reader = InspectionInputReader(dataset, [assets[0].pk, assets[2].pk])
    assert list(reader.assets()) == [assets[0]]
    assert list(reader.metrics('ttft_ms').values_list('asset_id', flat=True)) == [assets[0].pk]
    assert list(reader.events('TEST').values_list('asset_id', flat=True)) == [assets[0].pk]
    assert not reader.metrics('ttft_ms', asset_ids=[assets[1].pk]).exists()
    assert not reader.events(asset_ids=[assets[1].pk]).exists()
    assert not InspectionInputReader(dataset, []).metrics('ttft_ms').exists()
