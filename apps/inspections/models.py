from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import CreatedModel, EditableModel, semantic_version_validator


class Severity(models.TextChoices):
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"
    P4 = "P4", "P4"


class InspectionItem(EditableModel):
    class ExecutionMode(models.TextChoices):
        CODE_ONLY = "CODE_ONLY", "Code only"
        CODE_FIRST_AI_FALLBACK = "CODE_FIRST_AI_FALLBACK", "Code first, AI fallback"
        AI_INVESTIGATION = "AI_INVESTIGATION", "AI investigation"
        LEARNING_MODE = "LEARNING_MODE", "Learning mode"

    class CodeStatus(models.TextChoices):
        CODE_ACTIVE = "CODE_ACTIVE", "Code active"
        PARTIAL_CODE = "PARTIAL_CODE", "Partial code"
        CODE_PENDING = "CODE_PENDING", "Code pending"
        SHADOW = "SHADOW", "Shadow"
        NOT_CODED = "NOT_CODED", "Not coded"

    code = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=192, db_index=True)
    domain = models.CharField(max_length=64, db_index=True)
    description = models.TextField(default="")
    execution_mode = models.CharField(max_length=40, choices=ExecutionMode.choices, db_index=True)
    code_status = models.CharField(max_length=32, choices=CodeStatus.choices, db_index=True)
    code_coverage_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    default_severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.P3)
    enabled = models.BooleanField(default=True, db_index=True)
    schedule_policy = models.JSONField(default=dict)
    required_claims = models.JSONField(default=list)
    resolved_claims = models.JSONField(default=list)
    llm_responsibilities = models.JSONField(default=list)
    version = models.CharField(max_length=32, default="1.0.0", validators=[semantic_version_validator])

    class Meta:
        db_table = "inspection_items"


class ResourceType(EditableModel):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    asset_selector = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True, db_index=True)
    sort_order = models.IntegerField(default=100)

    class Meta:
        db_table = "resource_types"


class InspectionItemResourceType(CreatedModel):
    resource_type = models.ForeignKey(
        ResourceType,
        on_delete=models.CASCADE,
        related_name="inspection_items",
    )
    inspection_item = models.ForeignKey(
        InspectionItem,
        on_delete=models.CASCADE,
        related_name="resource_types",
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "inspection_item_resource_types"
        constraints = [
            models.UniqueConstraint(
                fields=["resource_type", "inspection_item"],
                name="uq_resource_type_inspection_item",
            )
        ]


class MockDataset(CreatedModel):
    class Status(models.TextChoices):
        GENERATING = "GENERATING", "Generating"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    seed = models.BigIntegerField(db_index=True)
    scenario = models.CharField(max_length=64, db_index=True)
    dataset_date = models.DateField(db_index=True)
    version = models.CharField(max_length=32, default="1.0.0", validators=[semantic_version_validator])
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.GENERATING, db_index=True)
    generator_config = models.JSONField(default=dict)
    asset_count = models.IntegerField(default=0)
    metric_count = models.IntegerField(default=0)
    log_count = models.IntegerField(default=0)
    event_count = models.IntegerField(default=0)
    change_count = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mock_datasets"


class MockMetric(models.Model):
    id = models.BigAutoField(primary_key=True)
    dataset = models.ForeignKey(MockDataset, on_delete=models.CASCADE)
    asset = models.ForeignKey("assets.Asset", on_delete=models.CASCADE)
    metric_name = models.CharField(max_length=128, db_index=True)
    ts = models.DateTimeField(db_index=True)
    value = models.FloatField()
    labels = models.JSONField(default=dict)

    class Meta:
        db_table = "mock_metrics"
        indexes = [models.Index(fields=["dataset", "asset", "metric_name", "ts"])]


class MockLog(models.Model):
    class Level(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    id = models.BigAutoField(primary_key=True)
    dataset = models.ForeignKey(MockDataset, on_delete=models.CASCADE)
    asset = models.ForeignKey("assets.Asset", on_delete=models.CASCADE)
    ts = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=64, db_index=True)
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.INFO, db_index=True)
    message = models.TextField()
    attributes = models.JSONField(default=dict)

    class Meta:
        db_table = "mock_logs"


class MockEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    dataset = models.ForeignKey(MockDataset, on_delete=models.CASCADE)
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL)
    ts = models.DateTimeField(db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    reason = models.CharField(max_length=128, default="")
    message = models.TextField(default="")
    attributes = models.JSONField(default=dict)

    class Meta:
        db_table = "mock_events"


class MockChange(models.Model):
    id = models.BigAutoField(primary_key=True)
    dataset = models.ForeignKey(MockDataset, on_delete=models.CASCADE)
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL)
    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(null=True, blank=True)
    change_type = models.CharField(max_length=64, db_index=True)
    summary = models.TextField()
    attributes = models.JSONField(default=dict)

    class Meta:
        db_table = "mock_changes"


class InspectionRun(CreatedModel):
    class TriggerType(models.TextChoices):
        AIRFLOW = "AIRFLOW", "Airflow"
        MANUAL = "MANUAL", "Manual"
        API = "API", "API"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        PARTIAL = "PARTIAL", "Partial"
        FAILED = "FAILED", "Failed"

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    dataset = models.ForeignKey(MockDataset, null=True, blank=True, on_delete=models.SET_NULL)
    run_date = models.DateField(db_index=True)
    trigger_type = models.CharField(max_length=32, choices=TriggerType.choices, db_index=True)
    airflow_dag_run_id = models.CharField(max_length=250, null=True, blank=True, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total_items = models.IntegerField(default=0)
    success_items = models.IntegerField(default=0)
    failed_items = models.IntegerField(default=0)
    risk_count = models.IntegerField(default=0)
    config_snapshot = models.JSONField(default=dict)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "inspection_runs"
        constraints = [
            models.UniqueConstraint(fields=["environment", "run_date", "trigger_type", "airflow_dag_run_id"], name="inspection_run_idempotency_unique"),
        ]


class InspectionItemRun(CreatedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    class AIAdmissionStatus(models.TextChoices):
        NOT_EVALUATED = "NOT_EVALUATED", "Not evaluated"
        NO_AI = "NO_AI", "No AI"
        AI_ELIGIBLE = "AI_ELIGIBLE", "AI eligible"
        AI_DEFERRED = "AI_DEFERRED", "AI deferred"
        DATA_INVALID = "DATA_INVALID", "Data invalid"

    inspection_run = models.ForeignKey(
        InspectionRun,
        on_delete=models.CASCADE,
        related_name="item_runs",
    )
    inspection_item = models.ForeignKey(
        InspectionItem,
        on_delete=models.CASCADE,
        related_name="item_runs",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    ai_admission_status = models.CharField(max_length=40, choices=AIAdmissionStatus.choices, default=AIAdmissionStatus.NOT_EVALUATED, db_index=True)
    asset_scope = models.JSONField(default=dict)
    summary = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    model_provider = models.CharField(max_length=32, null=True, blank=True)
    model_name = models.CharField(max_length=128, null=True, blank=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "inspection_item_runs"
        constraints = [models.UniqueConstraint(fields=["inspection_run", "inspection_item"], name="inspection_item_run_unique")]


class Finding(CreatedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RESOLVED = "RESOLVED", "Resolved"
        INVALID = "INVALID", "Invalid"

    class SourceType(models.TextChoices):
        METRIC = "METRIC", "Metric"
        LOG = "LOG", "Log"
        EVENT = "EVENT", "Event"
        TOPOLOGY = "TOPOLOGY", "Topology"
        RULE = "RULE", "Rule"

    inspection_item_run = models.ForeignKey(InspectionItemRun, on_delete=models.CASCADE)
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL)
    finding_code = models.CharField(max_length=128, db_index=True)
    title = models.CharField(max_length=192)
    category = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.P3, db_index=True)
    materiality = models.DecimalField(max_digits=5, decimal_places=4, default=0, validators=[MinValueValidator(0), MaxValueValidator(1)])
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    value = models.JSONField(default=dict)
    source_type = models.CharField(max_length=32, choices=SourceType.choices, db_index=True)
    observed_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "findings"


class DailySnapshot(CreatedModel):
    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    snapshot_date = models.DateField()
    inspection_run = models.OneToOneField(InspectionRun, on_delete=models.CASCADE)
    assets_total = models.IntegerField(default=0)
    assets_covered = models.IntegerField(default=0)
    inspection_item_count = models.IntegerField(default=0)
    risk_total = models.IntegerField(default=0)
    p1_count = models.IntegerField(default=0)
    p2_count = models.IntegerField(default=0)
    new_count = models.IntegerField(default=0)
    worsened_count = models.IntegerField(default=0)
    recovered_count = models.IntegerField(default=0)
    pending_action_count = models.IntegerField(default=0)
    pending_reverify_count = models.IntegerField(default=0)
    code_only_cases = models.IntegerField(default=0)
    ai_dependent_cases = models.IntegerField(default=0)
    code_coverage_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    deterministic_deflection_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    ai_displacement_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    data_completeness_rate = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    summary = models.JSONField(default=dict)

    class Meta:
        db_table = "daily_snapshots"
        constraints = [models.UniqueConstraint(fields=["environment", "snapshot_date"], name="daily_snapshot_environment_date_unique")]
