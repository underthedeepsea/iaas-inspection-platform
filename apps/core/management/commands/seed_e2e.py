import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.models import Environment


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

        from django.core.management import call_command
        call_command('seed_launch')
        self.stdout.write(self.style.SUCCESS(f"seeded {environment.slug} and {username}"))
