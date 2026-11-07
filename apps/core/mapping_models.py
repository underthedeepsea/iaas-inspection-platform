"""Draft storage only. All supported writes go through mapping_services.

ORM guards reject ordinary updates/deletes and bulk writes. They are not database
triggers: raw SQL, a base manager, or a database owner can bypass them. Cross-row
head/parent/scope invariants are enforced by the transaction service, not SQL.
"""
from django.core.exceptions import ValidationError
from django.db import models

from .models import CreatedModel


class ProtectedMappingQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use the mapping revision service; updates are prohibited.")

    def delete(self):
        raise ValidationError("Mapping history cannot be deleted.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Bulk mapping writes are prohibited.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Bulk mapping writes are prohibited.")


class MappingBundle(CreatedModel):
    environment = models.ForeignKey("core.Environment", on_delete=models.PROTECT)
    source_ref = models.CharField(max_length=32)
    cluster_uid = models.CharField(max_length=128)
    monitor_cluster_id = models.CharField(max_length=128)
    enabled = models.BooleanField(default=True)
    head_version = models.PositiveIntegerField(default=0)
    head_revision = models.ForeignKey(
        "core.MappingRevision", null=True, blank=True, on_delete=models.PROTECT,
        related_name="headed_bundles",
    )
    active_revision = models.ForeignKey("core.MappingRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="active_bundles")
    latest_validation = models.ForeignKey("core.MappingValidation", null=True, blank=True, on_delete=models.PROTECT, related_name="validated_bundle_heads")
    objects = ProtectedMappingQuerySet.as_manager()

    class Meta:
        db_table = "mapping_bundles"
        constraints = [
            models.UniqueConstraint(fields=["environment", "source_ref", "cluster_uid"], name="mapping_bundle_scope_uid"),
            models.UniqueConstraint(fields=["environment", "source_ref", "monitor_cluster_id"], name="mapping_bundle_scope_monitor"),
            models.CheckConstraint(check=models.Q(source_ref="demo-monitor"), name="mapping_bundle_demo_source"),
            models.CheckConstraint(check=(models.Q(head_version=0, head_revision__isnull=True) | models.Q(head_version__gte=1, head_revision__isnull=False)), name="mapping_bundle_head_shape"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            for field in ("environment_id", "source_ref", "cluster_uid", "monitor_cluster_id"):
                if getattr(old, field) != getattr(self, field):
                    raise ValidationError("Mapping identity is immutable.")
        else:
            # Prevent a caller-supplied existing UUID from becoming an UPDATE.
            kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Mapping history cannot be deleted.")


class MappingRevision(CreatedModel):
    bundle = models.ForeignKey(MappingBundle, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    schema_version = models.CharField(max_length=32)
    canonical_json = models.TextField()
    content_hash = models.CharField(max_length=64)
    parent_revision = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    rollback_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="rollback_children")
    reason = models.CharField(max_length=512)
    actor_label = models.CharField(max_length=128, help_text="Self-described local label; not authenticated identity.")
    objects = ProtectedMappingQuerySet.as_manager()

    class Meta:
        db_table = "mapping_revisions"
        constraints = [
            models.UniqueConstraint(fields=["bundle", "version"], name="mapping_revision_sequence"),
            models.CheckConstraint(check=models.Q(version__gte=1), name="mapping_revision_positive"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or kwargs.get("force_update") or kwargs.get("update_fields") is not None:
            raise ValidationError("Mapping revisions are append-only.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Mapping revisions are append-only.")
