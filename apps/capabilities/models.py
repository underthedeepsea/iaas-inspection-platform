from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.models import CreatedModel, EditableModel, semantic_version_validator


class Capability(EditableModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DISABLED = "DISABLED", "Disabled"
        RETIRED = "RETIRED", "Retired"

    capability_id = models.CharField(max_length=192, unique=True)
    name = models.CharField(max_length=192, db_index=True)
    description = models.TextField(default="")
    domain = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    current_version = models.ForeignKey("CapabilityVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    owner = models.CharField(max_length=128, default="platform")
    read_only = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "capabilities"


class CapabilityVersion(CreatedModel):
    class ImplementationType(models.TextChoices):
        RULE = "RULE", "Rule"
        EXEC = "EXEC", "Exec"
        REST = "REST", "REST"
        MCP = "MCP", "MCP"

    class Status(models.TextChoices):
        CANDIDATE = "CANDIDATE", "Candidate"
        SHADOW = "SHADOW", "Shadow"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    class HealthStatus(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Unknown"
        HEALTHY = "HEALTHY", "Healthy"
        UNHEALTHY = "UNHEALTHY", "Unhealthy"

    capability = models.ForeignKey(Capability, on_delete=models.CASCADE)
    version = models.CharField(max_length=32, validators=[semantic_version_validator])
    implementation_type = models.CharField(max_length=16, choices=ImplementationType.choices, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CANDIDATE, db_index=True)
    manifest = models.JSONField(default=dict)
    semantic_tags = ArrayField(models.CharField(max_length=192), default=list)
    subjects = ArrayField(models.CharField(max_length=192), default=list)
    resolves = ArrayField(models.CharField(max_length=192), default=list)
    input_schema = models.JSONField(default=dict)
    output_schema = models.JSONField(default=dict)
    endpoint = models.CharField(max_length=512, null=True, blank=True)
    script_path = models.CharField(max_length=512, null=True, blank=True)
    mcp_server = models.CharField(max_length=192, null=True, blank=True)
    mcp_tool = models.CharField(max_length=192, null=True, blank=True)
    timeout_seconds = models.IntegerField(default=15)
    retry_count = models.IntegerField(default=0)
    health_status = models.CharField(max_length=32, choices=HealthStatus.choices, default=HealthStatus.UNKNOWN, db_index=True)
    last_health_check_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "capability_versions"
        constraints = [models.UniqueConstraint(fields=["capability", "version"], name="capability_version_unique")]
        indexes = [GinIndex(fields=["semantic_tags"]), GinIndex(fields=["subjects"]), GinIndex(fields=["resolves"])]


class InspectionCapabilityBinding(CreatedModel):
    class Role(models.TextChoices):
        DETECTOR = "DETECTOR", "Detector"
        ENRICHER = "ENRICHER", "Enricher"
        RESOLVER = "RESOLVER", "Resolver"
        VALIDATOR = "VALIDATOR", "Validator"

    inspection_item = models.ForeignKey("inspections.InspectionItem", on_delete=models.CASCADE)
    capability_version = models.ForeignKey(CapabilityVersion, on_delete=models.CASCADE)
    role = models.CharField(max_length=32, choices=Role.choices, db_index=True)
    claim = models.CharField(max_length=192, db_index=True)
    priority = models.IntegerField(default=100)
    required = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "inspection_capability_bindings"
        constraints = [models.UniqueConstraint(fields=["inspection_item", "capability_version", "role", "claim"], name="inspection_capability_binding_unique")]
