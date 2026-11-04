"""One-shot, read-only explanation of persisted deterministic check facts."""
import json

from django.db import transaction
from django.utils import timezone

from apps.inspections.models import ResourceInspectionSummary
from apps.investigations.models import Investigation
from services.model_gateway.base import FinalAction, ModelRequest
from .compact_context import build_compact_explanation_context
from .fact_projection import project_report, interpretation_choices, compose_grounded_explanation
from .prompts import load_explanation_prompt, prompt_metadata, render_explanation_system_prompt



def build_resource_run_context(*, resource_type_code, inspection_run_id):
    summary = ResourceInspectionSummary.objects.select_related('inspection_run').get(inspection_run_id=inspection_run_id, resource_type__code=resource_type_code)
    run = summary.inspection_run
    from apps.inspections.services.run_result import resource_run_facts
    report, checks = resource_run_facts(run, resource_type_code)
    previous = ResourceInspectionSummary.objects.filter(resource_type__code=resource_type_code,
        inspection_run__environment_id=run.environment_id, inspection_run__created_at__lt=run.created_at).order_by('-inspection_run__created_at').first()
    return {'inspection_run_id': str(run.pk), 'resource_type': resource_type_code,
            'check_results': checks, 'fact_report': report,
            'summary': {'check_count': report['check_count'], 'status_counts': report['status_counts']},
            'previous_run': {'run': {'id': str(previous.inspection_run_id)}, 'summary': {'status': previous.status}} if previous else None,
            'truncated': False}


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
    report = context.get('fact_report') or project_report(context.get('check_results') or [], run_id=context.get('inspection_run_id'))
    choices = interpretation_choices(report, compact)
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
    result = {'evidence_gaps':gaps, 'input_limits': [], 'check_result_ids':[row['id'] for row in compact['check_results']], 'root_cause_candidates':[], 'comparisons':[], 'priority_actions':[], 'fact_report': report, 'prompt': prompt_metadata(prompt)}
    if compact['truncated']:
        result['input_limits'].append(f"AI输入因预算省略 {compact['omitted_count']} 条检查；CODE完整事实保留。")
    try:
        if sufficient:
            if gateway is None:
                from apps.conversations.services import _default_gateway
                gateway = _default_gateway()
            response = gateway.invoke(ModelRequest(messages=[{'role':'system','content':render_explanation_system_prompt(prompt, choices=choices)}, {'role':'user','content':json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}], metadata={'purpose':'inspection_explanation'}))
            current.rounds_used = 1
            current.model_provider, current.model_name = response.provider, response.model
            if isinstance(response.action, FinalAction):
                grounded = compose_grounded_explanation(report, compact, response.action.summary)
                result['grounded_report'] = grounded
                result['ai_status'] = grounded['ai_status']
                result['priority_actions'] = [{'title': row['asset_name'], 'action': row['ai']['next_check']} for row in grounded['checks'] if row['ai']]
                current.conclusion = grounded['text']
                current.confidence = response.action.confidence if grounded['ai_status'] == 'ACCEPTED' else None
                current.status = 'UNRESOLVED' if gaps or grounded['ai_status'] != 'ACCEPTED' else 'RESOLVED'
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
