from django.conf import settings
from django.db import models

from apps.core.models import CreatedModel


class AuditEvent(CreatedModel):
    environment = models.ForeignKey("core.Environment", null=True, blank=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64, db_index=True)
    object_id = models.CharField(max_length=128, db_index=True)
    trace_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_events"
