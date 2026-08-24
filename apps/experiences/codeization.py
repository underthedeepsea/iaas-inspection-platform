"""Locked state transitions for Experience-to-Code."""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.inspections.models import InspectionItem
from apps.learning.models import CodeizationTask, Experience

from .services import ExperienceError, _model, _require_actor, canonical_claim


_VERSION_RE = re.compile(r"\A\d+\.\d+\.\d+\Z")


def move_to_shadow(
    first=None,
    second=None,
    third=None,
    *,
    actor=None,
    actor_user=None,
    task=None,
    capability_version=None,
    version=None,
):
    """Atomically move CODE_PENDING and its candidate version to SHADOW."""

    actor, task, capability_version = _parse_transition_args(
        first,
        second,
        third,
        actor=actor,
        actor_user=actor_user,
        task=task,
        capability_version=capability_version,
        version=version,
    )
    _require_actor(actor)
    task = _model(task, CodeizationTask, "task")
    with transaction.atomic():
        task = CodeizationTask.objects.select_for_update().select_related("experience").get(pk=task.pk)
        experience = Experience.objects.select_for_update().get(pk=task.experience_id)
        item = InspectionItem.objects.select_for_update().get(pk=task.inspection_item_id)
        if item.enabled is not True:
            raise ExperienceError("inspection item is disabled")
        capability, version_row = _locked_capability_version(task, capability_version)
        _validate_candidate(task, capability, version_row)
        if task.status == CodeizationTask.Status.SHADOW:
            if version_row.status != CapabilityVersion.Status.SHADOW:
                raise ExperienceError("shadow task must have a shadow capability version")
            return task
        if task.status != CodeizationTask.Status.CODE_PENDING:
            raise ExperienceError("only CODE_PENDING tasks can enter SHADOW")
        if experience.status != Experience.Status.CODE_PENDING:
            raise ExperienceError("experience must be CODE_PENDING before SHADOW")
        version_row.status = CapabilityVersion.Status.SHADOW
        version_row.save(update_fields=["status"])
        _disable_resolvers(item, task.target_claim)
        _ensure_binding(item, version_row, task.target_claim, enabled=True)
        task.status = CodeizationTask.Status.SHADOW
        task.started_at = task.started_at or timezone.now()
        task.save(update_fields=["status", "started_at", "updated_at"])
        experience.status = Experience.Status.SHADOW
        experience.code_status = Experience.CodeStatus.SHADOW
        experience.save(update_fields=["status", "code_status", "updated_at"])
        item.code_status = InspectionItem.CodeStatus.SHADOW
        item.resolved_claims = [claim for claim in (item.resolved_claims or []) if claim != task.target_claim]
        item.save(update_fields=["code_status", "resolved_claims", "updated_at"])
        return task


def activate_codeization_task(
    first=None,
    second=None,
    third=None,
    *,
    actor=None,
    actor_user=None,
    task=None,
    capability_version=None,
    version=None,
):
    """Atomically make one exact SHADOW capability the authoritative resolver."""

    actor, task, capability_version = _parse_transition_args(
        first,
        second,
        third,
        actor=actor,
        actor_user=actor_user,
        task=task,
        capability_version=capability_version,
        version=version,
    )
    _require_actor(actor)
    task = _model(task, CodeizationTask, "task")
    with transaction.atomic():
        task = CodeizationTask.objects.select_for_update().get(pk=task.pk)
        experience = Experience.objects.select_for_update().get(pk=task.experience_id)
        item = InspectionItem.objects.select_for_update().get(pk=task.inspection_item_id)
        if item.enabled is not True:
            raise ExperienceError("inspection item is disabled")
        capability, version_row = _locked_capability_version(task, capability_version)
        _validate_version_identity(task, capability, version_row)
        _validate_read_only(capability, version_row)
        if task.status == CodeizationTask.Status.CODE_ACTIVE:
            if version_row.status == CapabilityVersion.Status.ACTIVE and capability.current_version_id == version_row.pk:
                return task
            raise ExperienceError("active task cannot be rebound to another version")
        if task.status != CodeizationTask.Status.SHADOW:
            raise ExperienceError("only SHADOW tasks can become CODE_ACTIVE")
        if experience.status != Experience.Status.SHADOW:
            raise ExperienceError("experience must be SHADOW before code activation")
        if version_row.status != CapabilityVersion.Status.SHADOW:
            raise ExperienceError("capability version must pass through SHADOW before ACTIVE")

        old_versions = list(
            CapabilityVersion.objects.select_for_update().filter(
                capability=capability,
                status=CapabilityVersion.Status.ACTIVE,
            ).exclude(pk=version_row.pk)
        )
        for old_version in old_versions:
            old_version.status = CapabilityVersion.Status.RETIRED
            old_version.retired_at = timezone.now()
            old_version.save(update_fields=["status", "retired_at"])
        _disable_resolvers(item, task.target_claim)
        version_row.status = CapabilityVersion.Status.ACTIVE
        version_row.activated_at = timezone.now()
        version_row.save(update_fields=["status", "activated_at"])
        capability.current_version = version_row
        capability.status = Capability.Status.ACTIVE
        capability.read_only = True
        capability.save(update_fields=["current_version", "status", "read_only", "updated_at"])
        _ensure_binding(item, version_row, task.target_claim, enabled=True)

        resolved = list(dict.fromkeys([*(item.resolved_claims or []), task.target_claim]))
        item.resolved_claims = resolved
        item.code_status = InspectionItem.CodeStatus.CODE_ACTIVE
        required = list(dict.fromkeys(item.required_claims or []))
        covered = len(set(required) & set(resolved))
        item.code_coverage_percent = 100 if not required else covered * 100 / len(required)
        item.execution_mode = (
            InspectionItem.ExecutionMode.CODE_ONLY
            if not required or covered == len(required)
            else InspectionItem.ExecutionMode.CODE_FIRST_AI_FALLBACK
        )
        item.save(
            update_fields=[
                "resolved_claims",
                "code_status",
                "code_coverage_percent",
                "execution_mode",
                "updated_at",
            ]
        )
        task.status = CodeizationTask.Status.CODE_ACTIVE
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        experience.status = Experience.Status.CODE_ACTIVE
        experience.code_status = Experience.CodeStatus.CODE_ACTIVE
        experience.save(update_fields=["status", "code_status", "updated_at"])
        return task


def transition_codeization_task(
    first=None,
    second=None,
    third=None,
    *,
    actor=None,
    actor_user=None,
    task=None,
    to_status=None,
    capability_version=None,
    version=None,
):
    """Dispatch only the legal CODE_PENDING -> SHADOW -> CODE_ACTIVE edges."""

    actor, task, supplied_version, supplied_status = _parse_transition_args(
        first,
        second,
        third,
        actor=actor,
        actor_user=actor_user,
        task=task,
        capability_version=capability_version,
        version=version,
        include_status=True,
    )
    capability_version = capability_version or supplied_version
    to_status = to_status or supplied_status
    if to_status is None:
        raise ExperienceError("target task status is required")
    to_status = to_status.value if hasattr(to_status, "value") else to_status
    if to_status == CodeizationTask.Status.SHADOW:
        return move_to_shadow(
            actor,
            task,
            capability_version or version,
            actor_user=actor_user,
        )
    if to_status == CodeizationTask.Status.CODE_ACTIVE:
        return activate_codeization_task(
            actor,
            task,
            capability_version or version,
            actor_user=actor_user,
        )
    raise ExperienceError("illegal codeization task transition")


def _parse_transition_args(
    first,
    second,
    third,
    *,
    actor,
    actor_user,
    task,
    capability_version,
    version,
    include_status=False,
):
    """Accept actor-first and task-first service call shapes."""

    status = None
    if isinstance(first, CodeizationTask):
        task = task or first
        if isinstance(second, CodeizationTask):
            raise ExperienceError("task is supplied more than once")
        if isinstance(second, (CodeizationTask.Status, str)):
            status = second
            capability_version = capability_version or third
        else:
            capability_version = capability_version or second or third
    elif first is not None:
        actor = actor or first
        task = task or second
        if isinstance(third, (CodeizationTask.Status, str)):
            status = third
        else:
            capability_version = capability_version or third
    else:
        status = second if isinstance(second, (CodeizationTask.Status, str)) else None
        capability_version = capability_version or (third if status is not None else second)
    return_values = (actor or actor_user, task, capability_version or version)
    return (*return_values, status) if include_status else return_values


def _locked_capability_version(task, supplied):
    if supplied is None:
        raise ExperienceError("the exact capability version is required")
    try:
        capability = Capability.objects.select_for_update().get(
            capability_id=task.target_capability_id,
        )
    except Capability.DoesNotExist:
        raise ExperienceError("target capability does not exist") from None
    version_query = CapabilityVersion.objects.select_for_update().select_related("capability")
    if isinstance(supplied, CapabilityVersion):
        try:
            version_row = version_query.get(pk=supplied.pk)
        except (CapabilityVersion.DoesNotExist, TypeError, ValueError):
            raise ExperienceError("capability version does not exist") from None
    elif isinstance(supplied, str) and "." in supplied:
        try:
            version_row = version_query.get(capability=capability, version=supplied.strip())
        except CapabilityVersion.DoesNotExist:
            raise ExperienceError("capability version does not exist") from None
    else:
        try:
            version_row = version_query.get(pk=supplied)
        except (CapabilityVersion.DoesNotExist, TypeError, ValueError):
            raise ExperienceError("capability version does not exist") from None
    if version_row.capability_id != capability.pk:
        raise ExperienceError("capability version does not belong to task capability")
    return capability, version_row


def _validate_candidate(task, capability, version):
    _validate_version_identity(task, capability, version)
    _validate_read_only(capability, version)
    if version.status != CapabilityVersion.Status.CANDIDATE:
        raise ExperienceError("only a candidate capability version can enter SHADOW")


def _validate_version_identity(task, capability, version):
    if not _VERSION_RE.fullmatch(version.version or ""):
        raise ExperienceError("capability version must use numeric x.x.x format")
    if capability.status != Capability.Status.ACTIVE:
        raise ExperienceError("target capability is not active")
    claim = canonical_claim(task.target_claim)
    if claim != task.target_claim or claim not in (version.resolves or []):
        raise ExperienceError("capability version does not resolve the exact task claim")
    if version.implementation_type != task.implementation_type:
        raise ExperienceError("capability implementation type does not match task")


def _validate_read_only(capability, version):
    if capability.read_only is not True:
        raise ExperienceError("codeization requires a read-only capability")
    manifest = version.manifest or {}
    security = manifest.get("security") if isinstance(manifest, dict) else None
    if isinstance(security, dict) and security.get("read_only") is False:
        raise ExperienceError("capability manifest is not read-only")
    if isinstance(manifest, dict) and manifest.get("read_only") is False:
        raise ExperienceError("capability manifest is not read-only")


def _disable_resolvers(item, claim):
    InspectionCapabilityBinding.objects.filter(
        inspection_item=item,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
    ).update(enabled=False)


def _ensure_binding(item, version, claim, *, enabled):
    binding, _created = InspectionCapabilityBinding.objects.get_or_create(
        inspection_item=item,
        capability_version=version,
        role=InspectionCapabilityBinding.Role.RESOLVER,
        claim=claim,
        defaults={"enabled": enabled},
    )
    if binding.enabled != enabled:
        binding.enabled = enabled
        binding.save(update_fields=["enabled"])
    return binding


# Readable aliases for callers that name the two lifecycle edges directly.
promote_to_shadow = move_to_shadow
activate_task = activate_codeization_task
activate_capability = activate_codeization_task
transition_task = transition_codeization_task
promote_capability_version = move_to_shadow
activate_capability_version = activate_codeization_task


__all__ = [
    "activate_capability",
    "activate_codeization_task",
    "activate_task",
    "move_to_shadow",
    "promote_to_shadow",
    "promote_capability_version",
    "activate_capability_version",
    "transition_task",
    "transition_codeization_task",
]
