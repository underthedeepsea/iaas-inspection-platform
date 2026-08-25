from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import CreatedModel, EditableModel, semantic_version_validator


class Investigation(EditableModel):
    class TriggerType(models.TextChoices):
        HUMAN = "HUMAN", "Human"
        AUTO = "AUTO", "Automatic"
        LEARNING = "LEARNING", "Learning"

    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        RUNNING = "RUNNING", "Running"
        RESOLVED = "RESOLVED", "Resolved"
        UNRESOLVED = "UNRESOLVED", "Unresolved"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    class EntryReason(models.TextChoices):
        CLAIM_GAP = "CLAIM_GAP", "Claim gap"
        CONFLICT = "CONFLICT", "Conflict"
        TREND_GAP = "TREND_GAP", "Trend gap"
        USER_QUESTION = "USER_QUESTION", "User question"
        LEARNING_EVENT = "LEARNING_EVENT", "Learning event"

    risk = models.ForeignKey("risks.Risk", null=True, blank=True, on_delete=models.SET_NULL)
    inspection_item_run = models.ForeignKey("inspections.InspectionItemRun", null=True, blank=True, on_delete=models.SET_NULL)
    trigger_type = models.CharField(max_length=32, choices=TriggerType.choices, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CREATED, db_index=True)
    entry_reason = models.CharField(max_length=64, choices=EntryReason.choices, db_index=True)
    missing_claim = models.CharField(max_length=192, null=True, blank=True, db_index=True)
    model_provider = models.CharField(max_length=32)
    model_name = models.CharField(max_length=128)
    max_rounds = models.IntegerField(default=3)
    rounds_used = models.IntegerField(default=0)
    max_tool_calls = models.IntegerField(default=5)
    tool_calls_used = models.IntegerField(default=0)
    conclusion = models.TextField(default="")
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Durable claim markers prevent concurrent idempotent requests from
    # starting the graph twice. Ordinary API retries never infer process death;
    # heartbeat inspection is reserved for explicit operational recovery.
    claim_token = models.UUIDField(null=True, blank=True, editable=False, db_index=True)
    claim_heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "investigations"


class InvestigationEvent(CreatedModel):
    class Status(models.TextChoices):
        INFO = "INFO", "Info"
        STARTED = "STARTED", "Started"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    investigation = models.ForeignKey(Investigation, on_delete=models.CASCADE)
    sequence = models.IntegerField()
    event_type = models.CharField(max_length=64, db_index=True)
    node_name = models.CharField(max_length=64, default="")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.INFO)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "investigation_events"
        constraints = [models.UniqueConstraint(fields=["investigation", "sequence"], name="investigation_event_sequence_unique")]


class Conversation(EditableModel):
    class ContextType(models.TextChoices):
        RISK = "RISK", "Risk"
        INSPECTION_ITEM = "INSPECTION_ITEM", "Inspection item"
        INVESTIGATION = "INVESTIGATION", "Investigation"
        EXPERIENCE = "EXPERIENCE", "Experience"
        RESOURCE_TYPE = "RESOURCE_TYPE", "Resource type"
        RESOURCE_RUN = "RESOURCE_RUN", "Resource run"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CLOSED = "CLOSED", "Closed"

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    context_type = models.CharField(max_length=32, choices=ContextType.choices, db_index=True)
    context_id = models.UUIDField(db_index=True)
    risk = models.ForeignKey("risks.Risk", null=True, blank=True, on_delete=models.SET_NULL)
    investigation = models.ForeignKey(Investigation, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "conversations"


class ConversationMessage(CreatedModel):
    class Role(models.TextChoices):
        USER = "USER", "User"
        ASSISTANT = "ASSISTANT", "Assistant"
        SYSTEM = "SYSTEM", "System"
        TOOL = "TOOL", "Tool"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.choices, db_index=True)
    content = models.TextField(default="")
    structured_content = models.JSONField(default=dict)
    model_provider = models.CharField(max_length=32, null=True, blank=True)
    model_name = models.CharField(max_length=128, null=True, blank=True)
    prompt_version = models.CharField(max_length=64, null=True, blank=True, validators=[semantic_version_validator])
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(null=True, blank=True)
    parent_message = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "conversation_messages"


class ToolCall(CreatedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        TIMEOUT = "TIMEOUT", "Timeout"
        REJECTED = "REJECTED", "Rejected"

    investigation = models.ForeignKey(Investigation, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.SET_NULL)
    assistant_message = models.ForeignKey(ConversationMessage, null=True, blank=True, on_delete=models.SET_NULL)
    capability_version = models.ForeignKey("capabilities.CapabilityVersion", on_delete=models.CASCADE)
    call_id = models.CharField(max_length=128, unique=True)
    tool_name = models.CharField(max_length=192, db_index=True)
    input_args = models.JSONField(default=dict)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    result_summary = models.TextField(default="")
    result_payload = models.JSONField(default=dict)
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    evidence = models.ForeignKey("risks.Evidence", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tool_calls"


class HumanFeedback(CreatedModel):
    class FeedbackType(models.TextChoices):
        HELPFUL = "HELPFUL", "Helpful"
        INCORRECT = "INCORRECT", "Incorrect"
        MISSING_EVIDENCE = "MISSING_EVIDENCE", "Missing evidence"
        WRONG_TOOL_PATH = "WRONG_TOOL_PATH", "Wrong tool path"
        CONFIRMED_ROOT_CAUSE = "CONFIRMED_ROOT_CAUSE", "Confirmed root cause"
        FALSE_POSITIVE = "FALSE_POSITIVE", "False positive"
        CUSTOM = "CUSTOM", "Custom"

    environment = models.ForeignKey("core.Environment", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    risk = models.ForeignKey("risks.Risk", null=True, blank=True, on_delete=models.SET_NULL)
    investigation = models.ForeignKey(Investigation, null=True, blank=True, on_delete=models.SET_NULL)
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.SET_NULL)
    message = models.ForeignKey(ConversationMessage, null=True, blank=True, on_delete=models.SET_NULL)
    feedback_type = models.CharField(max_length=40, choices=FeedbackType.choices, db_index=True)
    rating = models.SmallIntegerField(null=True, blank=True)
    comment = models.TextField(default="")
    confirmed_conclusion = models.TextField(default="")
    correction = models.JSONField(default=dict)
    create_experience = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "human_feedback"
        constraints = [
            models.CheckConstraint(
                check=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name="human_feedback_rating_between_one_and_five",
            ),
        ]
