"""Register the real inference performance launch rule without touching history."""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.inspections.models import InspectionItem, InspectionItemResourceType, ResourceType


RETIRED_CODES = (
    "topology.control_plane_anti_affinity",
    "llm.ttft_slo",
    "llm.queue_backlog",
)


class Command(BaseCommand):
    help = "Configure the real inference performance plugin and retire demo bindings."

    @transaction.atomic
    def handle(self, *args, **options):
        old_items = InspectionItem.objects.filter(code__in=RETIRED_CODES)
        old_bindings = InspectionItemResourceType.objects.filter(inspection_item__code__in=RETIRED_CODES)
        self.stdout.write(f"Retiring {old_items.count()} demo items and {old_bindings.count()} bindings")
        old_items.update(enabled=False)
        old_bindings.update(enabled=False)
        resource, _ = ResourceType.objects.get_or_create(
            code="LLM_RUNTIME", defaults={"name": "LLM 运行时", "enabled": True},
        )
        resource.asset_selector = {
            "asset_types": ["LLM_INSTANCE"],
            "labels": {"input_source": "INFERENCE_SNAPSHOT"},
        }
        resource.save(update_fields=["asset_selector", "updated_at"])
        item, _ = InspectionItem.objects.update_or_create(
            code="llm.performance_profile",
            defaults={
                "name": "推理性能画像",
                "domain": "llm",
                "execution_mode": "CODE_ONLY",
                "code_status": "CODE_ACTIVE",
                "default_severity": "P2",
                "rule_config": {},
                "enabled": True,
                "llm_responsibilities": [],
            },
        )
        InspectionItemResourceType.objects.update_or_create(
            resource_type=resource,
            inspection_item=item,
            defaults={"enabled": True},
        )
        self.stdout.write(self.style.SUCCESS("Configured inference performance plugin"))

        for code,kind,title in [('GPU_POOL','GPU','GPU 资源'),('HOST','HOST','主机基础环境')]:
            resource, _ = ResourceType.objects.update_or_create(code=code, defaults={
                'name':title,'enabled':True,'asset_selector':{'asset_types':[kind], 'labels':{'input_source':'HARDWARE_SNAPSHOT'}}})
            item, _ = InspectionItem.objects.update_or_create(code=f'hardware.{kind.lower()}_health', defaults={
                'name':title+'健康巡检','domain':'hardware','execution_mode':'CODE_ONLY','code_status':'CODE_ACTIVE',
                'default_severity':'P2','rule_config':{},'enabled':True,'llm_responsibilities':[]})
            InspectionItemResourceType.objects.update_or_create(resource_type=resource,inspection_item=item,defaults={'enabled':True})
