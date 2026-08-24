import re

from django.db import transaction
from jsonschema import SchemaError, ValidationError, validate

from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.inspections.models import InspectionItem

from .errors import PluginExecutionError, ReadOnlyCapabilityError
from .executor import ExecutionOrigin, InputValidationError


_SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}")
_SENSITIVE_IDENTIFIER_PARTS = (
    "accesskey",
    "apikey",
    "authorization",
    "credential",
    "endpoint",
    "idtoken",
    "password",
    "passwd",
    "privatekey",
    "raw",
    "secret",
    "token",
    "uri",
    "url",
)


class CapabilityRegistry:
    def resolve(self, claim):
        return self._resolve(
            claim,
            version_status=CapabilityVersion.Status.ACTIVE,
            code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        )

    def resolve_capability(self, capability_id, *, claim=None):
        """Resolve an active capability version for an LLM tool request.

        Formal code resolver lookup intentionally remains separate from this
        path: a Claim Gap may be backed by an active read-only capability that
        is not itself a ``CODE_ACTIVE`` inspection binding yet.
        """

        capability_id = _safe_identifier(capability_id)
        claim = _safe_identifier(claim)
        if not capability_id or not claim:
            return None
        capability = (
            Capability.objects.select_related("current_version")
            .filter(
                capability_id=capability_id,
                status=Capability.Status.ACTIVE,
                read_only=True,
            )
            .first()
        )
        version = capability.current_version if capability else None
        if (
            version is None
            or version.capability_id != capability.id
            or version.status != CapabilityVersion.Status.ACTIVE
            or claim not in (version.resolves or [])
        ):
            return None
        return version

    def execute_readonly(
        self,
        capability_id,
        *,
        claim,
        payload,
        executor,
        origin,
    ):
        """Re-authorize and dispatch while capability/version rows are locked."""

        if origin is not ExecutionOrigin.LLM:
            raise PluginExecutionError("LLM execution origin is required")
        capability_id = _safe_identifier(capability_id)
        claim = _safe_identifier(claim)
        if not capability_id or not claim:
            raise PluginExecutionError("a claim is required for capability execution")
        with transaction.atomic():
            capability = (
                Capability.objects.select_for_update()
                .filter(capability_id=capability_id)
                .first()
            )
            if capability is None or capability.status != Capability.Status.ACTIVE:
                raise PluginExecutionError("capability is not active")
            if capability.read_only is not True:
                raise ReadOnlyCapabilityError("LLM execution requires a read-only capability")
            version_id = capability.current_version_id
            version = (
                CapabilityVersion.objects.select_for_update()
                .select_related("capability")
                .filter(pk=version_id)
                .first()
                if version_id
                else None
            )
            if (
                version is None
                or version.capability_id != capability.id
                or version.status != CapabilityVersion.Status.ACTIVE
                or claim not in (version.resolves or [])
            ):
                raise PluginExecutionError("current capability version is not eligible")
            try:
                validate(payload, version.input_schema)
            except (ValidationError, SchemaError, TypeError) as exc:
                detail = getattr(exc, "message", "input schema validation failed")
                raise InputValidationError(f"input schema validation failed: {detail}") from exc
            return version, executor.execute(version, payload, origin=origin)

    def resolve_shadow(self, claim):
        return self._resolve(
            claim,
            version_status=CapabilityVersion.Status.SHADOW,
            code_status=InspectionItem.CodeStatus.SHADOW,
        )

    @staticmethod
    def _resolve(claim, *, version_status, code_status):
        binding = (
            InspectionCapabilityBinding.objects.select_related("capability_version")
            .filter(
                claim=claim,
                role=InspectionCapabilityBinding.Role.RESOLVER,
                enabled=True,
                inspection_item__enabled=True,
                inspection_item__code_status=code_status,
                capability_version__status=version_status,
                capability_version__capability__status=Capability.Status.ACTIVE,
                capability_version__resolves__contains=[claim],
            )
            .order_by("priority", "created_at")
            .first()
        )
        return binding.capability_version if binding else None


def _safe_identifier(value):
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(candidate):
        return ""
    canonical = "".join(character for character in candidate.lower() if character.isalnum())
    if any(
        canonical == part
        or canonical.startswith(part)
        or canonical.endswith(part)
        for part in _SENSITIVE_IDENTIFIER_PARTS
    ):
        return ""
    return candidate
