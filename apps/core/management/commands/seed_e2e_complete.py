"""Populate a complete, deterministic inspection demo for the E2E environment."""

from datetime import date, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Environment
from apps.inspections.models import (
    InspectionItem,
    InspectionItemResourceType,
    InspectionRun,
    ResourceType,
)
from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
from apps.inspections.services.trigger import create_manual_inspection_run


RUN_PLAN = (
    ('CONTROL_PLANE',),
    ('LLM_RUNTIME',),
    ('CONTROL_PLANE', 'LLM_RUNTIME'),
)

class Command(BaseCommand):
    help = "Populate a complete deterministic inspection demo for an E2E environment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--environment",
            default="e2e",
            help="Environment slug or UUID (default: e2e).",
        )
        parser.add_argument(
            "--base-date",
            help="First demo snapshot date in YYYY-MM-DD format (default: two days ago).",
        )

    def handle(self, *args, **options):
        call_command("seed_e2e")
        environment = self._environment(options["environment"])
        base_date = self._base_date(options.get("base_date"))
        self._ensure_items()

        for offset, resource_types in enumerate(RUN_PLAN):
            run_date = base_date + timedelta(days=offset)
            run = self._run(environment, run_date, resource_types)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{run_date.isoformat()} {'+'.join(resource_types)} "
                    f"{run.status} risks={run.risk_count} run={run.pk}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"complete E2E demo ready: {environment.slug}, "
                f"{base_date.isoformat()} to "
                f"{(base_date + timedelta(days=len(RUN_PLAN) - 1)).isoformat()}"
            )
        )

    def _environment(self, value):
        try:
            return Environment.objects.get(slug=value)
        except Environment.DoesNotExist:
            try:
                return Environment.objects.get(pk=value)
            except (Environment.DoesNotExist, ValueError, TypeError) as error:
                raise CommandError(f"environment not found: {value}") from error

    def _base_date(self, value):
        if not value:
            return timezone.localdate() - timedelta(days=2)
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise CommandError("base-date must be YYYY-MM-DD") from error

    def _ensure_items(self):
        call_command('seed_launch')

    def _run(self, environment, run_date, resource_types):
        resource_types = tuple(resource_types)
        existing = self._existing_run(environment, run_date, resource_types)
        if existing is not None:
            if existing.status in {
                InspectionRun.Status.SUCCEEDED,
                InspectionRun.Status.PARTIAL,
                InspectionRun.Status.FAILED,
            } and existing.finished_at is not None:
                return existing
            return start_manual_inspection_run(existing.pk)

        run = create_manual_inspection_run(
            environment=environment,
            resource_type_codes=list(resource_types),
            run_date=run_date,
        )
        return start_manual_inspection_run(run.pk)

    def _existing_run(self, environment, run_date, resource_types):
        expected = list(resource_types)
        for run in InspectionRun.objects.filter(
            environment=environment,
            run_date=run_date,
            trigger_type=InspectionRun.TriggerType.MANUAL,
        ).order_by("-created_at", "-pk"):
            requested = ((run.config_snapshot or {}).get("requested_scope") or {}).get(
                "resource_types"
            )
            if requested == expected:
                return run
        return None
