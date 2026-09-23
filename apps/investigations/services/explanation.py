"""One-shot, read-only explanation of persisted deterministic check facts."""
import json

from django.db import transaction
from django.db.models import Case, Count, When, Value, IntegerField
from django.utils import timezone

from apps.inspections.models import CheckResult, Finding, InspectionRun, ResourceInspectionSummary
from apps.investigations.models import Investigation
from apps.risks.models import Evidence, Risk, RiskObservation
from services.model_gateway.base import FinalAction, ModelRequest
from .compact_context import build_compact_explanation_context, validate_explanation_answer
from .prompts import load_explanation_prompt, prompt_metadata, render_explanation_system_prompt


MAX_CHECKS = 50


def _check(row):
    return {'id':str(row.pk), 'check':row.inspection_item_run.inspection_item.code, 'asset_id':str(row.asset_id), 'status':row.status, 'summary':row.summary, 'observed':row.observed_value, 'expected':row.expected_value, 'evidence':row.evidence, 'checked_at':row.checked_at.isoformat()}


def build_resource_run_context(*, resource_type_code, inspection_run_id):
    summary = ResourceInspectionSummary.objects.select_related('inspection_run').get(inspection_run_id=inspection_run_id, resource_type__code=resource_type_code)
    run = summary.inspection_run
    item_runs = [row for row in run.item_runs.select_related('inspection_item') if resource_type_code in (row.asset_scope or {}).get('resource_types', [])]
    # Older summaries predate per-item resource codes. Bindings still constrain those records.
    if not item_runs:
        item_runs = list(run.item_runs.filter(inspection_item__resource_types__resource_type__code=resource_type_code).distinct())
    asset_ids = {pk for row in item_runs for pk in (row.asset_scope or {}).get('asset_ids', [])}
    checks = CheckResult.objects.filter(inspection_run=run, inspection_item_run__in=item_runs, asset_id__in=asset_ids).select_related('inspection_item_run__inspection_item').order_by('inspection_item_run__inspection_item__code','asset_id')
    status_counts = dict(checks.order_by().values('status').annotate(count=Count('pk')).values_list('status', 'count'))
    total_checks = sum(status_counts.values())
    rows = list(checks.annotate(priority=Case(
        When(status='FAIL', then=Value(0)), When(status='ERROR', then=Value(1)),
        When(status='UNKNOWN', then=Value(2)), default=Value(3), output_field=IntegerField(),
    )).order_by('priority', 'inspection_item_run__inspection_item__code', 'asset_id')[:MAX_CHECKS])
    previous = ResourceInspectionSummary.objects.filter(resource_type__code=resource_type_code, inspection_run__environment_id=run.environment_id, inspection_run__created_at__lt=run.created_at).order_by('-inspection_run__created_at').first()
    prior = []
    if previous:
        prior = [_check(row) for row in CheckResult.objects.filter(inspection_run_id=previous.inspection_run_id, inspection_item_run__inspection_item_id__in=[r.inspection_item_id for r in item_runs], asset_id__in=asset_ids).select_related('inspection_item_run__inspection_item').order_by('inspection_item_run__inspection_item__code','asset_id')[:MAX_CHECKS]]
    risk_ids = RiskObservation.objects.filter(inspection_run=run, inspection_item_run__in=item_runs, detected=True).values_list('risk_id',flat=True)
    return {
        'inspection_run_id':str(run.pk), 'resource_type':resource_type_code,
        'check_results':[_check(row) for row in rows], 'previous_check_results':prior,
        'findings':list(Finding.objects.filter(inspection_item_run__in=item_runs, asset_id__in=asset_ids).values('finding_code','title','severity','value')[:MAX_CHECKS]),
        'risks':[{'id':str(r.pk),'title':r.title,'severity':r.severity,'status':r.status} for r in Risk.objects.filter(pk__in=risk_ids, primary_asset_id__in=asset_ids)[:MAX_CHECKS]],
        'evidence':[{'id':str(e.pk),'summary':e.summary} for e in Evidence.objects.filter(inspection_run=run, inspection_item_run__in=item_runs)[:MAX_CHECKS]],
        'summary': {'check_count': total_checks, 'status_counts': {status: status_counts.get(status, 0) for status in CheckResult.Status.values}},
        'truncated':total_checks > MAX_CHECKS,
    }


def build_resource_type_context(*, environment_id, resource_type_code, date_from=None, date_to=None):
    summaries = ResourceInspectionSummary.objects.filter(inspection_run__environment_id=environment_id, resource_type__code=resource_type_code)
    if date_from:
        summaries = summaries.filter(inspection_run__run_date__gte=date_from)
    if date_to:
        summaries = summaries.filter(inspection_run__run_date__lte=date_to)
    latest = summaries.order_by('-inspection_run__created_at').first()
    if latest is None:
        raise ValueError('请先完成一次资源巡检')
    return build_resource_run_context(resource_type_code=resource_type_code, inspection_run_id=latest.inspection_run_id)


def explain(investigation, context, *, gateway=None):
    prompt = load_explanation_prompt()
    compact = build_compact_explanation_context(context)
    with transaction.atomic():
        current = Investigation.objects.select_for_update().get(pk=investigation.pk)
        if current.status != 'CREATED':
            return current
        current.status, current.started_at = 'RUNNING', timezone.now()
        current.max_rounds, current.max_tool_calls = 1, 0
        current.save()
    checks = context.get('check_results', [])
    sufficient = any(row['status'] in {'PASS','FAIL'} for row in checks)
    gaps = ['部分检查证据不足'] if any(row['status'] in {'UNKNOWN','ERROR'} for row in checks) else []
    if not checks:
        gaps.append('本轮没有逐对象检查结果')
    if compact['truncated']:
        gaps.append(f"省略了 {compact['omitted_count']} 条检查明细；汇总计数保留")
    result = {'evidence_gaps':gaps, 'check_result_ids':[row['id'] for row in compact['check_results']], 'root_cause_candidates':[], 'comparisons':[], 'priority_actions':[], 'prompt': prompt_metadata(prompt)}
    try:
        if sufficient:
            if gateway is None:
                from apps.conversations.services import _default_gateway
                gateway = _default_gateway()
            response = gateway.invoke(ModelRequest(messages=[{'role':'system','content':render_explanation_system_prompt(prompt)}, {'role':'user','content':json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}], metadata={'purpose':'inspection_explanation'}))
            current.rounds_used = 1
            current.model_provider, current.model_name = response.provider, response.model
            if isinstance(response.action, FinalAction):
                validate_explanation_answer(response.action.summary, compact)
                current.conclusion, current.confidence = response.action.summary, response.action.confidence
                current.status = 'UNRESOLVED' if gaps else 'RESOLVED'
            else:
                current.status, current.conclusion = 'UNRESOLVED', '现有证据不足以完成解释'
                result['evidence_gaps'].append('模型请求了额外证据，首期不执行工具调查')
        else:
            current.status, current.conclusion = 'UNRESOLVED', '证据不足，无法解释确定性结论'
    except Exception:
        current.status, current.conclusion = 'FAILED', 'AI 分析暂不可用'
        result['error_code'] = 'LLM_UNAVAILABLE'
    current.result, current.finished_at = result, timezone.now()
    current.save()
    return current
