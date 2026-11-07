"""One-shot explanation of a bounded, environment-scoped CODE snapshot."""
import json
from copy import deepcopy

from apps.inspections.models import InspectionRun
from apps.inspections.services.run_result import inspection_run_result
from apps.audits.services import record_event
from services.model_gateway.base import FinalAction, ModelRequest, LLMUnavailableError
from .compact_context import build_compact_explanation_context
from .fact_projection import interpretation_choices, compose_grounded_explanation, project_report
from .prompts import load_explanation_prompt, prompt_metadata, render_explanation_system_prompt


COMPLETED_STATUSES = ('SUCCEEDED', 'PARTIAL')
LAUNCH_TYPES = {'LLM_RUNTIME', 'GPU_POOL', 'HOST'}


def latest_completed_launch_run(environment, *, before=None):
    runs = InspectionRun.objects.filter(environment=environment, status__in=COMPLETED_STATUSES, finished_at__isnull=False)
    if before:
        runs = runs.filter(created_at__lt=before.created_at)
    for run in runs.order_by('-created_at', '-pk').iterator():
        codes = set(((run.config_snapshot or {}).get('resolved_scope') or {}).get('resource_types') or [])
        if codes and codes <= LAUNCH_TYPES:
            return run
    return None


def frozen_explanation_context(run, original):
    context = deepcopy(original)
    if str(context.get('run', {}).get('id')) != str(run.pk):
        raise ValueError('explanation run mismatch')
    context['previous_run'] = None
    context['risks'] = []
    context['resource_summaries'] = []
    for row in context.get('check_results', []):
        row['risk_references'] = []
    context['fact_report'] = project_report(context.get('check_results', []), run_id=run.pk,
        frozen_input=(getattr(run, 'config_snapshot', None) or {}).get('input'))
    context['fact_report']['risk_state_note'] = '仅本轮冻结检查事实；不含实时风险状态或上次运行。'
    context['fact_report']['fact_cutoff'] = original.get('run', {}).get('finished_at') or original.get('run', {}).get('started_at')
    return context


def prepare_dashboard_explanation(run, question, *, context=None):
    """Build exactly the shared one-shot input, without invoking a model."""
    prompt = load_explanation_prompt()
    context = frozen_explanation_context(run, context if context is not None else inspection_run_result(run))
    context['question'] = question
    context['inspection_run_id'] = str(run.pk)
    # Keep evidence and citation IDs; omit duplicated API/presentation metadata.
    context['run'] = {key: context['run'][key] for key in ('id', 'run_date', 'status')}
    context['resource_summaries'] = [
        {key: row[key] for key in ('resource_type', 'assets_total', 'assets_covered', 'health_score', 'risk_count')}
        for row in context['resource_summaries']
    ]
    context['risks'] = [
        {key: row[key] for key in ('id', 'title', 'severity', 'status', 'primary_asset_id')}
        for row in context['risks']
    ]
    context['check_results'] = [
        {key: row[key] for key in ('id', 'inspection_item_code', 'asset_id', 'asset_name', 'status', 'summary', 'observed_value', 'expected_value', 'evidence', 'source', 'checked_at', 'risk_references')}
        for row in context['check_results']
    ]
    compact = build_compact_explanation_context(context, question=question)
    choices = interpretation_choices(context['fact_report'], compact)
    references = [
        {'type': 'CHECK_RESULT', 'id': row['id'], 'label': f"{row['asset_name']} · {row['check']} · {row['status']}", 'source': 'CODE'}
        for row in compact['check_results']
    ]
    request = ModelRequest(messages=[
        {'role': 'system', 'content': render_explanation_system_prompt(prompt, choices=choices) + '\n本次仅本轮冻结事实；Run/事实截止：' + str(run.pk) + ' / ' + str(context['fact_report'].get('fact_cutoff') or '未记录')},
        {'role': 'user', 'content': json.dumps(compact, ensure_ascii=False, separators=(',', ':'))},
    ], metadata={'purpose': 'dashboard_explanation'})
    return context, compact, references, prompt, request


def finish_dashboard_explanation(run, prepared, response):
    """Use the existing FINAL, safety and constrained selection checks."""
    context, compact, references, prompt, _request = prepared
    try:
        if not isinstance(response.action, FinalAction):
            raise LLMUnavailableError()
        grounded = compose_grounded_explanation(context['fact_report'], compact, response.action.summary)
    except Exception as cause:
        failure = LLMUnavailableError('AI 解读暂不可用，请稍后重试。CODE 巡检结果已保留。')
        failure.explanation_stage = 'grounding_validation'
        failure.explanation_cause_type = type(cause).__name__
        raise failure from None
    grounded['comparison_text'] = '本次智能解读仅使用当前Run冻结事实，未读取上次运行或实时风险。'
    metadata = prompt_metadata(prompt)
    try:
        audit = record_event(environment=run.environment, event_type='prompt.used', object_type='InspectionRun', object_id=run.pk,
                     payload={'prompt_key': metadata['key'], 'after_revision': metadata['revision'],
                              'after_hash': metadata['hash'], 'guard_version': metadata['guard_version']})
    except Exception as failure:
        failure.explanation_stage = 'audit_record'
        raise
    result = {'answer': grounded['text'], 'grounded_report': grounded, 'ai_status': grounded['ai_status'],
            'confidence': response.action.confidence if grounded['ai_status'] == 'ACCEPTED' else None,
            'inspection_run_id': str(run.pk), 'source': {'type': 'AI', 'provider': response.provider, 'model': response.model},
            'references': references, 'truncated': compact['truncated'], 'selected_count': compact['selected_count'],
            'omitted_count': compact['omitted_count'], 'check_count': compact['summary']['check_count'], 'prompt': metadata,
            'fact_cutoff': context['fact_report'].get('fact_cutoff'), 'scope_note': '仅本轮冻结事实；不含上次运行或实时风险'}
    if result['ai_status'] == 'ACCEPTED':
        from .saved_explanations import save_answer, serialize_message
        message = save_answer(run, result, audit_id=audit.pk, usage=getattr(response, 'usage', None), usage_source=response.metadata)
        result['saved'] = serialize_message(message)['saved']
    return result



def explain_dashboard(run, question, *, gateway=None):
    prepared = prepare_dashboard_explanation(run, question)
    try:
        if gateway is None:
            from apps.conversations.services import _default_gateway
            gateway = _default_gateway()
        response = gateway.invoke(prepared[-1])
    except Exception:
        raise LLMUnavailableError('AI 解读暂不可用，请稍后重试。CODE 巡检结果已保留。') from None
    return finish_dashboard_explanation(run, prepared, response)
