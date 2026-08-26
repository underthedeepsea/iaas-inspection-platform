import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.models import Environment
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
                "execution_mode": InspectionItem.ExecutionMode.CODE_ONLY,
                "code_status": InspectionItem.CodeStatus.CODE_ACTIVE,
                "required_claims": ["llm.performance.status"],
                "resolved_claims": ["llm.performance.status"],
                "code_coverage_percent": 100,
                "enabled": True,
            },
        )
        InspectionItemResourceType.objects.update_or_create(
            resource_type=resource_type,
            inspection_item=item,
            defaults={"enabled": True},
        )
        self.stdout.write(self.style.SUCCESS(f"seeded {environment.slug} and {username}"))
