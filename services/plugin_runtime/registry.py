from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.inspections.models import InspectionItem


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

        versions = CapabilityVersion.objects.select_related("capability").filter(
            capability__capability_id=capability_id,
            capability__status=Capability.Status.ACTIVE,
            status=CapabilityVersion.Status.ACTIVE,
        )
        if claim:
            versions = versions.filter(resolves__contains=[claim])
        return versions.order_by("created_at").first()

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
