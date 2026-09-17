from django.db import models

from apps.core.models import EditableModel


class Asset(EditableModel):
    class AssetType(models.TextChoices):
        CLUSTER = "CLUSTER", "Cluster"
        HOST = "HOST", "Host"
        VM = "VM", "VM"
        POD = "POD", "Pod"
        GPU = "GPU", "GPU"
        LLM_INSTANCE = "LLM_INSTANCE", "LLM instance"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    external_key = models.CharField(max_length=192)
    asset_type = models.CharField(max_length=32, choices=AssetType.choices, db_index=True)
    name = models.CharField(max_length=192, db_index=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    labels = models.JSONField(default=dict)
    topology = models.JSONField(default=dict)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "assets"
        constraints = [
            models.UniqueConstraint(fields=["environment", "external_key"], name="asset_environment_external_key_unique"),
        ]
