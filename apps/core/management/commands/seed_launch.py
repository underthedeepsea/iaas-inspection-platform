"""Configure exactly the two resources and three deterministic MVP rules."""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType


RULE_CONFIGS = [
    ('CONTROL_PLANE', 'topology.control_plane_anti_affinity', '控制面反亲和', 'topology', {}),
    ('LLM_RUNTIME', 'llm.ttft_slo', 'TTFT P95', 'llm', {'metric':'ttft_ms','percentile':95,'threshold_ms':180,'min_samples':3}),
    ('LLM_RUNTIME', 'llm.queue_backlog', 'Queue Backlog', 'llm', {'metric':'queue_depth','threshold':10,'consecutive_points':3}),
]


class Command(BaseCommand):
    help = 'Configure v0.2 launch resources and deterministic rules; retain deferred data.'

    @transaction.atomic
    def handle(self, *args, **options):
        for code in ['CONTROL_PLANE','LLM_RUNTIME']:
            InspectionItemResourceType.objects.filter(resource_type__code=code).exclude(inspection_item__code__in=[r[1] for r in RULE_CONFIGS if r[0] == code]).update(enabled=False)
        for resource_code, code, name, domain, config in RULE_CONFIGS:
            resource = ResourceType.objects.get(code=resource_code)
            item, _ = InspectionItem.objects.update_or_create(code=code,defaults={'name':name,'domain':domain,'execution_mode':'CODE_ONLY','code_status':'CODE_ACTIVE','default_severity':'P2','rule_config':config,'enabled':True,'llm_responsibilities':[]})
            InspectionItemResourceType.objects.update_or_create(resource_type=resource,inspection_item=item,defaults={'enabled':True})
        self.stdout.write(self.style.SUCCESS('Configured 2 launch resources and 3 deterministic rules'))
