import os
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import Environment
from apps.inference_performance.schemas import parse_snapshot_request
from apps.inference_performance.services.ingest import ingest_snapshot


def _performance_input(environment, end):
    return {
        "source": "e2e-browser-fixture",
        "environment_id": str(environment.pk),
        "engine": {
            "engine_id": f"e2e-browser-{environment.pk}",
            "engine_type": "vllm",
            "model_name": "Qwen3.5-4B",
        },
        "sample": {
            "sample_id": f"e2e-browser-{environment.pk}-{end.isoformat()}",
            "window_start": (end - timedelta(minutes=1)).isoformat(),
            "window_end": end.isoformat(),
            "ttft": {"avg_ms": 100, "p90_ms": 200, "p95_ms": 1200, "p99_ms": 1300, "e2e_ratio": 0.2},
            "tpot": {"avg_ms": 10, "p90_ms": 15, "p95_ms": 20, "p99_ms": 30},
            "e2e": {"avg_ms": 1000, "p90_ms": 1500, "p95_ms": 2000, "p99_ms": 2500},
            "traffic": {"qps": 5, "qpm": 300},
            "throughput": {"generation_tps": 1000, "prompt_tps": 2000},
            "cache": {"kv_cache_hit_rate": 0.6},
            "requests": {"running": 3, "waiting": 40},
        },
    }


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
        call_command("seed_launch")
        # Two contiguous observations confirm the existing fixed TTFT/queue limits.
        # Ingest owns stable asset creation and evaluation; the browser triggers runs.
        now = timezone.now().replace(second=0, microsecond=0)
        for end in (now - timedelta(minutes=1), now):
            ingest_snapshot(parse_snapshot_request(_performance_input(environment, end)))
        self.stdout.write(self.style.SUCCESS(f"seeded {environment.slug}"))
