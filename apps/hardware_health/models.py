"""Immutable external hardware observations; evaluations are frozen at ingestion."""
import uuid
from django.db import models


class HardwareSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.ForeignKey('core.Environment', on_delete=models.CASCADE)
    asset = models.ForeignKey('assets.Asset', on_delete=models.PROTECT, related_name='hardware_snapshots')
    source = models.CharField(max_length=64)
    sample_id = models.CharField(max_length=192)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField(db_index=True)
    payload = models.JSONField()
    evaluation = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['environment', 'source', 'sample_id'], name='uq_hw_env_source_sample'),
                       models.UniqueConstraint(fields=['asset', 'window_start', 'window_end'], name='uq_hw_asset_window')]
        indexes = [models.Index(fields=['asset', 'window_end'], name='idx_hw_asset_window')]
