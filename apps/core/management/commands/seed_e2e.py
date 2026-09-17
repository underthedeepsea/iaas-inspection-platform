import os

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
        from django.core.management import call_command
        call_command('seed_launch')
        self.stdout.write(self.style.SUCCESS(f"seeded {environment.slug}"))
