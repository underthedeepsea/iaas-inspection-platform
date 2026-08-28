import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.models import Environment
from apps.capabilities.models import Capability, CapabilityVersion, InspectionCapabilityBinding
from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType


class Command(BaseCommand):
    help = "Create the small deterministic fixture used by the real browser smoke test."

    def handle(self, *args, **options):
        environment, _ = Environment.objects.update_or_create(
            slug=os.getenv("E2E_ENV_SLUG", "e2e"),
            defaults={
                "name": os.getenv("E2E_ENV_NAME", "E2E 环境"),
                "environment_type": Environment.EnvironmentType.TEST,
                "is_active": True,
            },
        )
        user_model = get_user_model()
        username = os.getenv("E2E_USERNAME", "e2e")
        user, _ = user_model.objects.get_or_create(username=username)
        user.is_active = True
        user.set_password(os.getenv("E2E_PASSWORD", "e2e-password"))
        user.save(update_fields=["password", "is_active"])
        for role in ("viewer", "operator"):
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)

        resource_type = ResourceType.objects.get(code="LLM_RUNTIME", enabled=True)
        item, _ = InspectionItem.objects.update_or_create(
            code="e2e.llm.scheduler",
            defaults={
                "name": "LLM 调度压力",
                "domain": "LLM",
                "execution_mode": InspectionItem.ExecutionMode.AI_INVESTIGATION,
                "code_status": InspectionItem.CodeStatus.NOT_CODED,
                "required_claims": ["llm.performance.root_cause"],
                "resolved_claims": [],
                "llm_responsibilities": ["确认调度压力的根因"],
                "code_coverage_percent": 0,
                "enabled": True,
            },
        )
        InspectionItemResourceType.objects.update_or_create(
            resource_type=resource_type,
            inspection_item=item,
            defaults={"enabled": True},
        )
        capability, _ = Capability.objects.update_or_create(
            capability_id="e2e.llm.scheduler.pressure",
            defaults={
                "name": "E2E LLM 调度压力证据",
                "description": "Deterministic read-only evidence for browser acceptance tests.",
                "domain": "LLM",
                "status": Capability.Status.ACTIVE,
                "owner": "e2e",
                "read_only": True,
            },
        )
        version, _ = CapabilityVersion.objects.update_or_create(
            capability=capability,
            version="1.0.0",
            defaults={
                "implementation_type": CapabilityVersion.ImplementationType.RULE,
                "status": CapabilityVersion.Status.ACTIVE,
                "manifest": {
                    "rule": {
                        "all": [{"field": "asset_id", "equals": "llm-0"}],
                        "result": {
                            "matched": True,
                            "status": "pressure-confirmed",
                            "source": "e2e-deterministic",
                        },
                    }
                },
                "semantic_tags": ["e2e", "llm", "read-only"],
                "subjects": ["llm-0"],
                "resolves": ["llm.performance.root_cause"],
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string"}},
                    "required": ["asset_id"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "matched": {"type": "boolean"},
                        "result": {"type": "object"},
                    },
                    "required": ["matched", "result"],
                    "additionalProperties": False,
                },
            },
        )
        if capability.current_version_id != version.pk:
            capability.current_version = version
            capability.save(update_fields=["current_version", "updated_at"])
        InspectionCapabilityBinding.objects.update_or_create(
            inspection_item=item,
            capability_version=version,
            role=InspectionCapabilityBinding.Role.RESOLVER,
            claim="llm.performance.root_cause",
            defaults={"priority": 10, "required": True, "enabled": True},
        )
        self.stdout.write(self.style.SUCCESS(f"seeded {environment.slug} and {username}"))
