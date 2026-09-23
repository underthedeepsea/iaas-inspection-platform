from django.core.management.base import BaseCommand
from django.db import transaction

from apps.inference_performance.models import InferencePerformanceSnapshot
from apps.inference_performance.services.assets import get_or_create_inference_asset


class Command(BaseCommand):
    help = "Link historical inference snapshots to stable LLM assets (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise ValueError("batch-size must be positive")
        queryset = InferencePerformanceSnapshot.objects.filter(asset__isnull=True).order_by("pk")
        total = queryset.count()
        self.stdout.write(f"unlinked_snapshots={total} mode={'apply' if options['apply'] else 'dry-run'}")
        if not options["apply"]:
            return
        linked = 0
        cursor = None
        while True:
            page = queryset.filter(pk__gt=cursor) if cursor is not None else queryset
            rows = list(page[:batch_size])
            if not rows:
                break
            with transaction.atomic():
                for row in rows:
                    asset = get_or_create_inference_asset(
                        environment=row.environment, engine_id=row.engine_id,
                        engine_type=row.engine_type, model_name=row.model_name,
                    )
                    linked += InferencePerformanceSnapshot.objects.filter(pk=row.pk, asset__isnull=True).update(asset=asset)
            cursor = rows[-1].pk
        self.stdout.write(f"linked_snapshots={linked}")
