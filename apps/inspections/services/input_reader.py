"""Read snapshot facts inside the intersection of dataset, environment and scope."""
from apps.assets.models import Asset
from apps.inspections.models import MockEvent, MockMetric


class InspectionInputReader:
    def __init__(self, dataset, asset_ids):
        self.dataset = dataset
        self.asset_ids = tuple(asset_ids)

    def assets(self):
        assets = list(Asset.objects.filter(environment_id=self.dataset.environment_id, pk__in=self.asset_ids).select_related('parent').order_by('external_key', 'pk'))
        snapshot = (self.dataset.generator_config or {}).get('asset_snapshot')
        if snapshot is not None:
            for asset in assets:
                facts = snapshot.get(str(asset.pk), {})
                asset.parent = None
                asset.topology = facts.get('topology', {})
                asset.labels = facts.get('labels', asset.labels)
                asset.name = facts.get('name', asset.name)
                asset.asset_type = facts.get('asset_type', asset.asset_type)
        return assets

    def metrics(self, metric_name, *, asset_ids=None):
        query = MockMetric.objects.filter(dataset=self.dataset, asset__in=self.assets(), metric_name=metric_name)
        if asset_ids is not None:
            query = query.filter(asset_id__in=asset_ids)
        return query.order_by('ts', 'id')

    def events(self, event_type=None, *, asset_ids=None):
        query = MockEvent.objects.filter(dataset=self.dataset, asset__in=self.assets())
        if event_type is not None:
            query = query.filter(event_type=event_type)
        if asset_ids is not None:
            query = query.filter(asset_id__in=asset_ids)
        return query.order_by('ts', 'id')
