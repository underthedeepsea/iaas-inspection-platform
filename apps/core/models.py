import uuid

from django.db import models


class Environment(models.Model):
    class EnvironmentType(models.TextChoices):
        DEV = "DEV", "Development"
        TEST = "TEST", "Test"
        PROD_SIM = "PROD_SIM", "Production simulation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    slug = models.CharField(max_length=64, unique=True)
    environment_type = models.CharField(
        max_length=32,
        choices=EnvironmentType.choices,
        default=EnvironmentType.DEV,
        db_index=True,
    )
    tenant_key = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "environments"
