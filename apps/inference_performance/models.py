import uuid

from django.db import models


class InferencePerformanceSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="performance_snapshots")
    source = models.CharField(max_length=64)
    sample_id = models.CharField(max_length=192)
    engine_id = models.CharField(max_length=192)
    engine_type = models.CharField(max_length=32)
    model_name = models.CharField(max_length=256)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField(db_index=True)
    metrics = models.JSONField(default=dict)
    evaluation = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "sample_id"], name="uq_inference_perf_source_sample"),
        ]
        indexes = [
            models.Index(fields=["asset", "window_end"], name="idx_inf_perf_asset_time"),
            models.Index(fields=["environment", "engine_id", "window_end"], name="idx_inf_perf_engine_time"),
            models.Index(fields=["engine_type", "model_name", "window_end"], name="idx_inf_perf_model_time"),
        ]
