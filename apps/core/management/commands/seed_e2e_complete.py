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


ITEMS = {
    "CONTROL_PLANE": {
        "code": "topology.control_plane_anti_affinity",
        "name": "控制面反亲和",
        "domain": "topology",
        "description": "检查控制面工作负载是否分散到不同主机。",
        "required_claims": ["topology.control_plane_anti_affinity"],
        "execution_mode": InspectionItem.ExecutionMode.CODE_ONLY,
        "code_status": InspectionItem.CodeStatus.CODE_ACTIVE,
        "default_severity": "P2",
    },
    "KVM_CLUSTER": {
        "code": "e2e.kvm.cluster_baseline",
        "name": "KVM 集群基线",
        "domain": "kvm",
        "description": "检查 KVM 集群的基础资源指标。",
        "required_claims": [],
        "execution_mode": InspectionItem.ExecutionMode.CODE_ONLY,
        "code_status": InspectionItem.CodeStatus.CODE_ACTIVE,
        "default_severity": "P3",
    },
    "K8S_CLUSTER": {
        "code": "e2e.k8s.cluster_baseline",
        "name": "Kubernetes 集群基线",
        "domain": "kubernetes",
        "description": "检查 Kubernetes 集群的基础资源指标。",
        "required_claims": [],
        "execution_mode": InspectionItem.ExecutionMode.CODE_ONLY,
        "code_status": InspectionItem.CodeStatus.CODE_ACTIVE,
        "default_severity": "P3",
    },
    "LLM_RUNTIME": {
        "code": "e2e.llm.scheduler",
        "name": "LLM 调度压力",
        "domain": "LLM",
        "description": "检查推理延迟、队列深度和 GPU 利用率变化。",
        "required_claims": ["llm.performance.root_cause"],
        "execution_mode": InspectionItem.ExecutionMode.AI_INVESTIGATION,
        "code_status": InspectionItem.CodeStatus.NOT_CODED,
        "default_severity": "P2",
    },
    "GPU_POOL": {
        "code": "e2e.gpu.pool_baseline",
        "name": "GPU 资源基线",
        "domain": "gpu",
        "description": "检查 GPU 资源的利用率和容量基线。",
        "required_claims": [],
        "execution_mode": InspectionItem.ExecutionMode.CODE_ONLY,
        "code_status": InspectionItem.CodeStatus.CODE_ACTIVE,
        "default_severity": "P3",
    },
    "HOST": {
        "code": "e2e.host.baseline",
        "name": "主机基础环境",
        "domain": "host",
        "description": "检查主机 CPU、内存、网络和容量基线。",
        "required_claims": [],
        "execution_mode": InspectionItem.ExecutionMode.CODE_ONLY,
        "code_status": InspectionItem.CodeStatus.CODE_ACTIVE,
        "default_severity": "P3",
    },
}


RUN_PLAN = (
    ("CONTROL_PLANE",),
    ("KVM_CLUSTER",),
    ("K8S_CLUSTER",),
    ("GPU_POOL",),
    ("HOST",),
    ("CONTROL_PLANE", "LLM_RUNTIME"),
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
            help="First demo snapshot date in YYYY-MM-DD format (default: tomorrow).",
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
            return timezone.localdate() + timedelta(days=1)
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise CommandError("base-date must be YYYY-MM-DD") from error

    def _ensure_items(self):
        for resource_type_code, config in ITEMS.items():
            resource_type = ResourceType.objects.get(code=resource_type_code, enabled=True)
            defaults = {
                **config,
                "enabled": True,
                "resolved_claims": [],
                "llm_responsibilities": [],
                "code_coverage_percent": 0,
            }
            item, _ = InspectionItem.objects.update_or_create(
                code=config["code"],
                defaults=defaults,
            )
            InspectionItemResourceType.objects.update_or_create(
                resource_type=resource_type,
                inspection_item=item,
                defaults={"enabled": True},
            )

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
