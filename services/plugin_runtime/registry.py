from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.inspections.models import InspectionItem


class CapabilityRegistry:
    def resolve(self, claim):
        return self._resolve(
            claim,
            version_status=CapabilityVersion.Status.ACTIVE,
            code_status=InspectionItem.CodeStatus.CODE_ACTIVE,
        )

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
