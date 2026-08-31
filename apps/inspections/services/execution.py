"""Code-first execution for the Task 4 deterministic mock scenarios."""

from dataclasses import dataclass
import uuid

from django.db import transaction
from django.utils import timezone

from apps.assets.models import Asset
from apps.inspections.models import (
    Finding,
    InspectionItem,
    InspectionItemRun,
    InspectionRun,
    MockChange,
    MockEvent,
    MockLog,
    MockMetric,
)
from apps.inspections.services.coverage import ClaimCoverage, compute_claim_coverage
from apps.inspections.services.findings import FindingSpec, persist_findings
from apps.inspections.services.scope import resolve_item_asset_scope
from services.plugin_runtime.registry import CapabilityRegistry


@dataclass(frozen=True)
class _ScenarioResult:
    code_claims: tuple
    findings: tuple
    missing_data: tuple
    data_valid: bool


def execute_inspection_item(
    inspection_run,
    inspection_item,
    dataset=None,
    *,
    registry=None,
    observed_at=None,
):
    """Run one inspection item and persist its run plus deterministic findings.

    The function deliberately has no LLM or risk-correlation path.  It reads
    only Task 4's persisted mock rows, computes Claim coverage, and records an
    explicit AI admission status for the later investigation stage.
    """

    dataset = dataset or inspection_run.dataset
    if dataset is None:
        raise ValueError("inspection_run must reference a mock dataset")
    registry = registry or CapabilityRegistry()
    started_at = observed_at or timezone.now()

    with transaction.atomic():
        item_run, _ = InspectionItemRun.objects.select_for_update().get_or_create(
            inspection_run=inspection_run,
            inspection_item=inspection_item,
        )
        item_run.status = InspectionItemRun.Status.RUNNING
        item_run.ai_admission_status = InspectionItemRun.AIAdmissionStatus.NOT_EVALUATED
        item_run.started_at = started_at
        item_run.error_code = None
        item_run.error_message = None
        item_run.save(
            update_fields=[
                "status",
                "ai_admission_status",
                "started_at",
                "error_code",
                "error_message",
            ]
        )

        scenario_result = _run_deterministic_detector(dataset, inspection_item)
        coverage = compute_claim_coverage(
            inspection_item,
            code_claims=scenario_result.code_claims,
            registry=registry,
            data_valid=scenario_result.data_valid,
        )
        admission_status = _admission_status(coverage)
        finished_at = timezone.now()
        if item_run.asset_scope and "asset_ids" in item_run.asset_scope:
            asset_scope = item_run.asset_scope
        else:
            asset_scope = resolve_item_asset_scope(inspection_run, inspection_item)
            if asset_scope is None:
                asset_scope = _asset_scope(dataset)
        summary = _summary(dataset, scenario_result, coverage)

        item_run.status = InspectionItemRun.Status.SUCCEEDED
        item_run.ai_admission_status = admission_status
        item_run.asset_scope = asset_scope
        item_run.summary = summary
        item_run.finished_at = finished_at
        item_run.save(
            update_fields=[
                "status",
                "ai_admission_status",
                "asset_scope",
                "summary",
                "finished_at",
            ]
        )

        persist_findings(item_run, scenario_result.findings)
        _update_item_coverage(inspection_item, coverage)
        _update_run_counts(inspection_run)

    return item_run


def execute_inspection_run(
    inspection_run,
    inspection_items=None,
    dataset=None,
    *,
    registry=None,
):
    """Execute enabled items in a run, keeping run aggregation deterministic."""

    requested_by_id = not isinstance(inspection_run, InspectionRun)
    if requested_by_id:
        inspection_run = InspectionRun.objects.select_related("dataset").get(
            pk=uuid.UUID(str(inspection_run))
        )
    dataset = dataset or inspection_run.dataset
    items = inspection_items
    if items is None:
        resolved_scope = (inspection_run.config_snapshot or {}).get("resolved_scope")
        if isinstance(resolved_scope, dict) and "inspection_item_ids" in resolved_scope:
            items = InspectionItem.objects.filter(
                pk__in=resolved_scope.get("inspection_item_ids") or []
            ).order_by("code", "created_at", "pk")
        else:
            items = InspectionItem.objects.filter(enabled=True).order_by("code", "created_at")
    results = [
        execute_inspection_item(
            inspection_run,
            item,
            dataset,
            registry=registry,
        )
        for item in items
    ]
    _update_run_counts(inspection_run)
    inspection_run.refresh_from_db()
    return inspection_run if requested_by_id else results


def _run_deterministic_detector(dataset, inspection_item):
    events = list(
        MockEvent.objects.filter(dataset=dataset)
        .select_related("asset")
        .order_by("ts", "id")
    )
    logs = list(
        MockLog.objects.filter(dataset=dataset)
        .select_related("asset")
        .order_by("ts", "id")
    )
    metrics = list(
        MockMetric.objects.filter(dataset=dataset)
        .select_related("asset")
        .order_by("metric_name", "ts", "id")
    )
    missing_data = _missing_data(dataset, metrics)
    data_valid = dataset.status == dataset.Status.READY and not missing_data
    scenario = dataset.scenario

    if not data_valid:
        event = next((row for row in events if row.event_type == "DATA_QUALITY"), None)
        if event is None:
            event = logs[-1] if logs else None
        observed = getattr(event, "ts", timezone.now())
        asset = getattr(event, "asset", None)
        return _ScenarioResult(
            code_claims=(),
            findings=(
                FindingSpec(
                    finding_code="DATA_INCOMPLETE",
                    title="巡检数据不完整",
                    category="data_quality",
                    severity=inspection_item.default_severity,
                    materiality=1.0,
                    status=Finding.Status.INVALID,
                    value={"missing_data": list(missing_data)},
                    source_type=Finding.SourceType.EVENT,
                    observed_at=observed,
                    asset=asset,
                ),
            ),
            missing_data=tuple(missing_data),
            data_valid=False,
        )

    if scenario == "control_plane_anti_affinity":
        return _control_plane_result(events, inspection_item)
    if scenario == "llm_scheduler_pressure":
        return _llm_pressure_result(events, metrics, inspection_item)
    if scenario == "mixed_resource_inspection":
        return _mixed_resource_result(events, metrics, inspection_item)
    return _ScenarioResult(code_claims=(), findings=(), missing_data=(), data_valid=True)


def _mixed_resource_result(events, metrics, inspection_item):
    """Keep mixed-scenario findings on the item that owns each claim."""

    code = str(inspection_item.code).lower()
    claims = {
        str(claim).lower()
        for claim in (inspection_item.required_claims or [])
        if isinstance(claim, str)
    }
    targets = set()
    if "anti_affinity" in code or any("anti_affinity" in claim for claim in claims):
        targets.add("control")
    if "llm" in code or any("llm" in claim or "performance" in claim for claim in claims):
        targets.add("llm")

    results = []
    if "control" in targets:
        results.append(_control_plane_result(events, inspection_item))
    if "llm" in targets:
        results.append(_llm_pressure_result(events, metrics, inspection_item))
    if not results:
        return _ScenarioResult(code_claims=(), findings=(), missing_data=(), data_valid=True)

    return _ScenarioResult(
        code_claims=tuple(dict.fromkeys(claim for result in results for claim in result.code_claims)),
        findings=tuple(finding for result in results for finding in result.findings),
        missing_data=tuple(dict.fromkeys(data for result in results for data in result.missing_data)),
        data_valid=all(result.data_valid for result in results),
    )


def _control_plane_result(events, inspection_item):
    event = next(
        (
            row
            for row in events
            if row.event_type == "TOPOLOGY_RISK" and row.reason == "ANTI_AFFINITY_VIOLATION"
        ),
        None,
    )
    if event is None:
        return _ScenarioResult(code_claims=(), findings=(), missing_data=(), data_valid=True)
    claims = tuple(
        claim
        for claim in inspection_item.required_claims
        if "anti_affinity" in claim or "anti-affinity" in claim
    )
    return _ScenarioResult(
        code_claims=claims,
        findings=(
            FindingSpec(
                finding_code="CONTROL_PLANE_ANTI_AFFINITY",
                title="控制面反亲和违规",
                category="topology",
                severity="P2",
                materiality=0.95,
                value=dict(event.attributes),
                source_type=Finding.SourceType.EVENT,
                observed_at=event.ts,
                asset=event.asset,
            ),
        ),
        missing_data=(),
        data_valid=True,
    )


def _llm_pressure_result(events, metrics, inspection_item):
    series = {
        metric_name: [
            point.value
            for point in metrics
            if point.asset.external_key == "llm-0" and point.metric_name == metric_name
        ]
        for metric_name in ("ttft_ms", "queue_depth", "gpu_util_percent")
    }
    pressure = all(series.values()) and all(
        before < after
        for before, after in zip(series["ttft_ms"], series["ttft_ms"][1:])
    ) and all(
        before < after
        for before, after in zip(series["queue_depth"], series["queue_depth"][1:])
    ) and all(
        before > after
        for before, after in zip(series["gpu_util_percent"], series["gpu_util_percent"][1:])
    )
    event = next(
        (
            row
            for row in events
            if row.event_type == "PERFORMANCE_DEGRADATION"
            and row.reason == "SCHEDULER_PRESSURE"
        ),
        None,
    )
    if not pressure or event is None:
        return _ScenarioResult(code_claims=(), findings=(), missing_data=(), data_valid=True)
    claims = tuple(
        claim
        for claim in inspection_item.required_claims
        if claim in {"llm.performance.status", "performance.status"}
        or (claim.endswith(".status") and "performance" in claim)
    )
    return _ScenarioResult(
        code_claims=claims,
        findings=(
            FindingSpec(
                finding_code="LLM_PERFORMANCE_DEGRADED",
                title="LLM 性能退化",
                category="performance",
                severity="P2",
                materiality=0.9,
                value={
                    "signals": list(event.attributes.get("signals", [])),
                    "ttft_ms": {"first": series["ttft_ms"][0], "last": series["ttft_ms"][-1]},
                    "queue_depth": {
                        "first": series["queue_depth"][0],
                        "last": series["queue_depth"][-1],
                    },
                    "gpu_util_percent": {
                        "first": series["gpu_util_percent"][0],
                        "last": series["gpu_util_percent"][-1],
                    },
                },
                source_type=Finding.SourceType.EVENT,
                observed_at=event.ts,
                asset=event.asset,
            ),
        ),
        missing_data=(),
        data_valid=True,
    )


def _missing_data(dataset, metrics):
    required_metrics = {
        "llm_scheduler_pressure": ("ttft_ms", "queue_depth", "gpu_util_percent"),
        "mixed_resource_inspection": ("ttft_ms", "queue_depth", "gpu_util_percent"),
        "data_incomplete": ("queue_depth",),
    }.get(dataset.scenario, ())
    present_metrics = {
        (metric.asset.external_key, metric.metric_name)
        for metric in metrics
    }
    missing = [
        metric_name
        for metric_name in required_metrics
        if ("llm-0", metric_name) not in present_metrics
    ]
    if dataset.status != dataset.Status.READY:
        missing.append("dataset")
    return tuple(dict.fromkeys(missing))


def _admission_status(coverage):
    if not coverage.data_valid:
        return InspectionItemRun.AIAdmissionStatus.DATA_INVALID
    if coverage.ai_eligible:
        return InspectionItemRun.AIAdmissionStatus.AI_ELIGIBLE
    return InspectionItemRun.AIAdmissionStatus.NO_AI


def _summary(dataset, scenario_result, coverage: ClaimCoverage):
    summary = coverage.as_summary()
    summary.update(
        {
            "scenario": dataset.scenario,
            "data_valid": scenario_result.data_valid,
            "missing_data": list(scenario_result.missing_data),
            "finding_count": len(scenario_result.findings),
        }
    )
    return summary


def _asset_scope(dataset):
    asset_ids = set()
    for evidence_model in (MockMetric, MockLog, MockEvent, MockChange):
        asset_ids.update(
            evidence_model.objects.filter(
                dataset_id=dataset.pk,
                asset_id__isnull=False,
            ).values_list("asset_id", flat=True)
        )
    return {
        "asset_keys": list(
            Asset.objects.filter(id__in=asset_ids)
            .order_by("external_key")
            .values_list("external_key", flat=True)
        )
    }


def _frozen_asset_scope(inspection_run, inspection_item=None):
    if inspection_item is not None:
        return resolve_item_asset_scope(inspection_run, inspection_item)
    resolved_scope = (inspection_run.config_snapshot or {}).get("resolved_scope")
    if not isinstance(resolved_scope, dict) or "asset_ids" not in resolved_scope:
        return None
    return {
        "asset_ids": [str(value) for value in resolved_scope.get("asset_ids") or []],
        "resource_types": list(resolved_scope.get("resource_types") or []),
    }


def _update_item_coverage(inspection_item, coverage):
    inspection_item.resolved_claims = list(coverage.resolved_claims)
    inspection_item.code_coverage_percent = coverage.code_coverage_percent
    inspection_item.save(update_fields=["resolved_claims", "code_coverage_percent", "updated_at"])


def _update_run_counts(inspection_run):
    item_runs = InspectionItemRun.objects.filter(inspection_run=inspection_run)
    total = item_runs.count()
    successful = item_runs.filter(status=InspectionItemRun.Status.SUCCEEDED).count()
    failed = item_runs.filter(status=InspectionItemRun.Status.FAILED).count()
    InspectionRun.objects.filter(pk=inspection_run.pk).update(
        total_items=total,
        success_items=successful,
        failed_items=failed,
    )


__all__ = [
    "execute_inspection_item",
    "execute_inspection_run",
]
