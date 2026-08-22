from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import CreatedModel, EditableModel


class Experience(EditableModel):
    class Status(models.TextChoices):
        DISCOVERED = "DISCOVERED", "Discovered"
        CONFIRMED = "CONFIRMED", "Confirmed"
        RULE_CANDIDATE = "RULE_CANDIDATE", "Rule candidate"
        CODE_PENDING = "CODE_PENDING", "Code pending"
        SHADOW = "SHADOW", "Shadow"
        CODE_ACTIVE = "CODE_ACTIVE", "Code active"
        REJECTED = "REJECTED", "Rejected"
        RETIRED = "RETIRED", "Retired"

    class SourceType(models.TextChoices):
        INVESTIGATION = "INVESTIGATION", "Investigation"
        FEEDBACK = "FEEDBACK", "Feedback"
        LEARNING_EVENT = "LEARNING_EVENT", "Learning event"

    class CodeStatus(models.TextChoices):
        CODE_ACTIVE = "CODE_ACTIVE", "Code active"
        PARTIAL_CODE = "PARTIAL_CODE", "Partial code"
        CODE_PENDING = "CODE_PENDING", "Code pending"
        SHADOW = "SHADOW", "Shadow"
        NOT_CODED = "NOT_CODED", "Not coded"

    experience_key = models.CharField(max_length=192, unique=True)
    title = models.CharField(max_length=255, db_index=True)
    domain = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DISCOVERED, db_index=True)
    source_type = models.CharField(max_length=32, choices=SourceType.choices, db_index=True)
    source_risk = models.ForeignKey("risks.Risk", null=True, blank=True, on_delete=models.SET_NULL)
    source_investigation = models.ForeignKey("investigations.Investigation", null=True, blank=True, on_delete=models.SET_NULL)
    hypothesis = models.TextField(default="")
    conclusion = models.TextField()
    applicable_scope = models.JSONField(default=dict)
    trigger_conditions = models.JSONField(default=list)
    required_evidence = models.JSONField(default=list)
    tool_sequence = models.JSONField(default=list)
    human_summary = models.TextField(default="")
    support_count = models.IntegerField(default=0)
    precision = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    code_status = models.CharField(max_length=32, choices=CodeStatus.choices, default=CodeStatus.NOT_CODED, db_index=True)
    target_claim = models.CharField(max_length=192, default="", db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "experiences"


class ExperienceEvidence(CreatedModel):
    class Relation(models.TextChoices):
        SUPPORT = "SUPPORT", "Support"
        COUNTEREXAMPLE = "COUNTEREXAMPLE", "Counterexample"
        CONTEXT = "CONTEXT", "Context"

    experience = models.ForeignKey(Experience, on_delete=models.CASCADE)
    evidence = models.ForeignKey("risks.Evidence", on_delete=models.CASCADE)
    relation = models.CharField(max_length=32, choices=Relation.choices, default=Relation.SUPPORT, db_index=True)
    weight = models.DecimalField(max_digits=5, decimal_places=4, default=1, validators=[MinValueValidator(0), MaxValueValidator(1)])

    class Meta:
        db_table = "experience_evidence"
        constraints = [models.UniqueConstraint(fields=["experience", "evidence", "relation"], name="experience_evidence_relation_unique")]


class CodeizationTask(EditableModel):
    class TaskType(models.TextChoices):
        RULE = "RULE", "Rule"
        PLUGIN = "PLUGIN", "Plugin"
        NEW_DATA = "NEW_DATA", "New data"

    class Status(models.TextChoices):
        CODE_PENDING = "CODE_PENDING", "Code pending"
        DEVELOPING = "DEVELOPING", "Developing"
        SHADOW = "SHADOW", "Shadow"
        CODE_ACTIVE = "CODE_ACTIVE", "Code active"
        REJECTED = "REJECTED", "Rejected"

    class ImplementationType(models.TextChoices):
        RULE = "RULE", "Rule"
        EXEC = "EXEC", "Exec"
        REST = "REST", "REST"
        MCP = "MCP", "MCP"

    experience = models.ForeignKey(Experience, on_delete=models.CASCADE)
    inspection_item = models.ForeignKey("inspections.InspectionItem", on_delete=models.CASCADE)
    target_capability_id = models.CharField(max_length=192, db_index=True)
    task_type = models.CharField(max_length=32, choices=TaskType.choices, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CODE_PENDING, db_index=True)
    title = models.CharField(max_length=255)
    target_claim = models.CharField(max_length=192, db_index=True)
    implementation_type = models.CharField(max_length=16, choices=ImplementationType.choices)
    specification = models.JSONField(default=dict)
    owner = models.CharField(max_length=128, default="")
    historical_support = models.IntegerField(default=0)
    precision = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    critical_false_positive = models.IntegerField(default=0)
    shadow_cases = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "codeization_tasks"
