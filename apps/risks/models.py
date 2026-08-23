from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import CreatedModel, EditableModel
from apps.inspections.models import Severity


class Risk(EditableModel):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        PERSISTING = "PERSISTING", "Persisting"
        WORSENED = "WORSENED", "Worsened"
        INVESTIGATING = "INVESTIGATING", "Investigating"
        LOCATED = "LOCATED", "Located"
        PENDING_ACTION = "PENDING_ACTION", "Pending action"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        PENDING_REVERIFY = "PENDING_REVERIFY", "Pending reverification"
        RECOVERED = "RECOVERED", "Recovered"
        IGNORED = "IGNORED", "Ignored"
        FALSE_POSITIVE = "FALSE_POSITIVE", "False positive"

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    inspection_item = models.ForeignKey("inspections.InspectionItem", on_delete=models.CASCADE)
    primary_asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL)
    risk_key = models.CharField(max_length=192, db_index=True)
    fingerprint = models.CharField(max_length=128)
    title = models.CharField(max_length=255, db_index=True)
    domain = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=8, choices=Severity.choices, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW, db_index=True)
    current_conclusion = models.TextField(default="")
    impact_summary = models.TextField(default="")
    recommendation = models.TextField(default="")
    first_seen_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(db_index=True)
    recovered_at = models.DateTimeField(null=True, blank=True, db_index=True)
    occurrence_count = models.IntegerField(default=1)
    duration_days = models.IntegerField(default=1)
    llm_involved_last = models.BooleanField(default=False, db_index=True)
    current_investigation = models.ForeignKey("investigations.Investigation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "risks"
        constraints = [models.UniqueConstraint(fields=["environment", "fingerprint"], name="risk_environment_fingerprint_unique")]


class RiskObservation(CreatedModel):
    risk = models.ForeignKey(Risk, on_delete=models.CASCADE)
    inspection_run = models.ForeignKey("inspections.InspectionRun", on_delete=models.CASCADE)
    inspection_item_run = models.ForeignKey("inspections.InspectionItemRun", on_delete=models.CASCADE)
    observed_at = models.DateTimeField(db_index=True)
    detected = models.BooleanField(default=True, db_index=True)
    severity = models.CharField(max_length=8, choices=Severity.choices)
    status_after = models.CharField(max_length=32, choices=Risk.Status.choices)
    finding_count = models.IntegerField(default=0)
    evidence_count = models.IntegerField(default=0)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "risk_observations"
        constraints = [models.UniqueConstraint(fields=["risk", "inspection_run"], name="risk_observation_risk_run_unique")]


class RiskStatusHistory(CreatedModel):
    class Source(models.TextChoices):
        SYSTEM = "SYSTEM", "System"
        HUMAN = "HUMAN", "Human"
        REVERIFY = "REVERIFY", "Reverify"

    risk = models.ForeignKey(Risk, on_delete=models.CASCADE)
    from_status = models.CharField(max_length=32, choices=Risk.Status.choices, null=True, blank=True)
    to_status = models.CharField(max_length=32, choices=Risk.Status.choices, db_index=True)
    reason = models.TextField(default="")
    source = models.CharField(max_length=32, choices=Source.choices, db_index=True)
    actor_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    inspection_run = models.ForeignKey("inspections.InspectionRun", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "risk_status_history"


class Evidence(CreatedModel):
    class EvidenceType(models.TextChoices):
        METRIC = "METRIC", "Metric"
        LOG = "LOG", "Log"
        EVENT = "EVENT", "Event"
        TOPOLOGY = "TOPOLOGY", "Topology"
        TOOL_RESULT = "TOOL_RESULT", "Tool result"
        CHANGE = "CHANGE", "Change"

    inspection_run = models.ForeignKey("inspections.InspectionRun", null=True, blank=True, on_delete=models.SET_NULL)
    inspection_item_run = models.ForeignKey("inspections.InspectionItemRun", null=True, blank=True, on_delete=models.SET_NULL)
    risk = models.ForeignKey(Risk, null=True, blank=True, on_delete=models.SET_NULL)
    investigation = models.ForeignKey("investigations.Investigation", null=True, blank=True, on_delete=models.SET_NULL)
    asset = models.ForeignKey("assets.Asset", null=True, blank=True, on_delete=models.SET_NULL)
    evidence_type = models.CharField(max_length=32, choices=EvidenceType.choices, db_index=True)
    evidence_key = models.CharField(max_length=192, db_index=True)
    summary = models.TextField()
    payload = models.JSONField(default=dict)
    source = models.CharField(max_length=128, db_index=True)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=1, validators=[MinValueValidator(0), MaxValueValidator(1)])
    materiality = models.DecimalField(max_digits=5, decimal_places=4, default=0, validators=[MinValueValidator(0), MaxValueValidator(1)])
    raw_ref = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "evidence"
