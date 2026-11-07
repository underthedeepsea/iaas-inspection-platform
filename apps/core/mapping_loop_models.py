"""Append-only receipts/events and mutable collection job; service-owned invariants."""
from django.core.exceptions import ValidationError
from django.db import models
from .models import CreatedModel
from .mapping_models import ProtectedMappingQuerySet


class AuditRecord(CreatedModel):
    objects = ProtectedMappingQuerySet.as_manager()
    class Meta:
        abstract = True
    def save(self,*args,**kwargs):
        if not self._state.adding or kwargs.get('force_update') or kwargs.get('update_fields') is not None:
            raise ValidationError('Mapping audit records are append-only.')
        kwargs['force_insert']=True
        super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):
        raise ValidationError('Mapping audit records are append-only.')


class MappingValidation(AuditRecord):
    bundle=models.ForeignKey('core.MappingBundle',on_delete=models.PROTECT)
    revision=models.ForeignKey('core.MappingRevision',on_delete=models.PROTECT)
    kind=models.CharField(max_length=16)
    content_hash=models.CharField(max_length=64)
    binding=models.JSONField()
    result=models.JSONField()
    valid_until=models.DateTimeField()


class MappingActivation(AuditRecord):
    bundle=models.ForeignKey('core.MappingBundle',on_delete=models.PROTECT)
    revision=models.ForeignKey('core.MappingRevision',on_delete=models.PROTECT)
    previous_revision=models.ForeignKey('core.MappingRevision',on_delete=models.PROTECT,null=True,related_name='+')
    validation=models.ForeignKey(MappingValidation,on_delete=models.PROTECT)
    idempotency_key=models.CharField(max_length=128)
    request_hash=models.CharField(max_length=64)
    reason=models.CharField(max_length=512)
    actor_label=models.CharField(max_length=128)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['bundle','idempotency_key'],name='mapping_activation_key')]


class MappingCollection(CreatedModel):
    environment=models.ForeignKey('core.Environment',on_delete=models.PROTECT)
    bundle=models.ForeignKey('core.MappingBundle',on_delete=models.PROTECT)
    activation=models.ForeignKey(MappingActivation,on_delete=models.PROTECT)
    revision=models.ForeignKey('core.MappingRevision',on_delete=models.PROTECT)
    idempotency_key=models.CharField(max_length=128)
    request_hash=models.CharField(max_length=64)
    binding=models.JSONField()
    evidence=models.JSONField(default=dict)
    status=models.CharField(max_length=16,default='CREATED')
    error_code=models.CharField(max_length=64,blank=True)
    run=models.ForeignKey('inspections.InspectionRun',on_delete=models.PROTECT,null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['environment','idempotency_key'],name='mapping_collection_environment_key')]


class MappingEnableEvent(AuditRecord):
    bundle = models.ForeignKey('core.MappingBundle', on_delete=models.PROTECT)
    enabled = models.BooleanField()
    previous_enabled = models.BooleanField()
    revision = models.ForeignKey('core.MappingRevision', on_delete=models.PROTECT, null=True)
    validation = models.ForeignKey(MappingValidation, on_delete=models.PROTECT, null=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    reason = models.CharField(max_length=512)
    actor_label = models.CharField(max_length=128, help_text='Self-described local label; not authenticated identity.')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['bundle', 'idempotency_key'], name='mapping_enable_event_key')]
