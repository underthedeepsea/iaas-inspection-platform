"""Create one test-only real-schema inference sample and inspection Run."""

from datetime import date, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import Environment
from apps.inference_performance.schemas import parse_snapshot_request
from apps.inference_performance.services.ingest import ingest_snapshot
from apps.inspections.models import InspectionRun
from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
from apps.inspections.services.trigger import create_manual_inspection_run


def _sample(environment, end):
    sample_id = f"e2e-{environment.pk}-{end.strftime('%Y%m%d%H%M')}"
    return {
        'source': 'e2e-real-schema', 'environment_id': str(environment.pk),
        'engine': {'engine_id': f'e2e-{environment.pk}', 'engine_type': 'vllm', 'model_name': 'Qwen3.5-4B'},
        'sample': {
            'sample_id': sample_id, 'window_start': (end - timedelta(minutes=1)).isoformat(), 'window_end': end.isoformat(),
            'ttft': {'avg_ms': 300, 'p90_ms': 700, 'p95_ms': 1200, 'p99_ms': 1600, 'e2e_ratio': 0.2},
            'tpot': {'avg_ms': 10, 'p90_ms': 20, 'p95_ms': 30, 'p99_ms': 40},
            'e2e': {'avg_ms': 1000, 'p90_ms': 2000, 'p95_ms': 3000, 'p99_ms': 4000},
            'traffic': {'qps': 5, 'qpm': 300},
            'throughput': {'generation_tps': 1000, 'prompt_tps': 2000},
            'cache': {'kv_cache_hit_rate': 0.6},
            'requests': {'running': 3, 'waiting': 1},
        },
    }


class Command(BaseCommand):
    help = 'Populate an E2E TEST environment from the real inference snapshot schema.'

    def add_arguments(self, parser):
        parser.add_argument('--environment', default='e2e', help='Environment slug or UUID.')
        parser.add_argument('--base-date', help='Legacy argument; must be today because real snapshots are current observations.')

    def handle(self, *args, **options):
        call_command('seed_e2e')
        value = options['environment']
        try:
            environment = Environment.objects.get(slug=value)
        except Environment.DoesNotExist:
            try:
                environment = Environment.objects.get(pk=value)
            except (Environment.DoesNotExist, ValueError, TypeError) as error:
                raise CommandError(f'environment not found: {value}') from error
        if environment.environment_type != Environment.EnvironmentType.TEST:
            raise CommandError('seed_e2e_complete requires a TEST environment')
        today = timezone.localdate()
        if options.get('base_date'):
            try:
                requested = date.fromisoformat(options['base_date'])
            except ValueError as error:
                raise CommandError('base-date must be YYYY-MM-DD') from error
            if requested != today:
                raise CommandError('real inference E2E snapshots must use the current date')
        now = timezone.now().replace(second=0, microsecond=0)
        for end in (now - timedelta(minutes=1), now):
            ingest_snapshot(parse_snapshot_request(_sample(environment, end)))
        existing = InspectionRun.objects.filter(
            environment=environment, run_date=today, trigger_type=InspectionRun.TriggerType.MANUAL,
            config_snapshot__requested_scope__resource_types=['LLM_RUNTIME'],
        ).order_by('-created_at').first()
        run = existing or create_manual_inspection_run(environment=environment, resource_type_codes=['LLM_RUNTIME'], run_date=today)
        if run.finished_at is None:
            run = start_manual_inspection_run(run.pk)
        self.stdout.write(self.style.SUCCESS(f'real inference E2E ready: run={run.pk} status={run.status} risks={run.risk_count}'))
