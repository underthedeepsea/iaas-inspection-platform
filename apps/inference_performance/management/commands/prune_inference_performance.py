from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...models import InferencePerformanceSnapshot


class Command(BaseCommand):
    help = "Delete inference performance snapshots older than the configured retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1:
            raise CommandError("--days must be at least 1")
        deleted, _ = InferencePerformanceSnapshot.objects.filter(window_end__lt=timezone.now() - timedelta(days=days)).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} inference performance snapshots and related rows."))
