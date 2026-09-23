"""One-shot explanation of a bounded, environment-scoped CODE snapshot."""
import json

from apps.inspections.models import InspectionRun
from apps.inspections.models import CheckResult
from apps.inspections.serializers import serialize_check_result
from apps.inspections.services.run_result import inspection_run_result
from apps.audits.services import record_event
from django.db.models import Q
from services.model_gateway.base import FinalAction, ModelRequest, LLMUnavailableError
from .compact_context import build_compact_explanation_context, validate_explanation_answer
from .prompts import load_explanation_prompt, prompt_metadata, render_explanation_system_prompt


COMPLETED_STATUSES = ('SUCCEEDED', 'PARTIAL')
LAUNCH_TYPES = {'LLM_RUNTIME'}


def latest_completed_launch_run(environment, *, before=None):
    runs = InspectionRun.objects.filter(environment=environment, status__in=COMPLETED_STATUSES, finished_at__isnull=False)
    if before:
        runs = runs.filter(created_at__lt=before.created_at)
    for run in runs.order_by('-created_at', '-pk').iterator():
        codes = set(((run.config_snapshot or {}).get('resolved_scope') or {}).get('resource_types') or [])
        if codes and codes <= LAUNCH_TYPES:
            return run
    return None


def explain_dashboard(run, question, *, gateway=None):
    prompt = load_explanation_prompt()
    context = inspection_run_result(run, check_limit=50, risk_limit=20)
    # The general result API sorts by rule. Fetch exceptional rows independently
    # so a late rule's FAIL is never hidden behind the first fifty PASS rows.
    scope = Q(pk__in=[])
    frozen_ids = set(((run.config_snapshot or {}).get('resolved_scope') or {}).get('asset_ids') or [])
    for item_run in run.item_runs.all():
        ids = set((item_run.asset_scope or {}).get('asset_ids') or [])
        if frozen_ids:
            ids &= frozen_ids
        scope |= Q(inspection_item_run=item_run, asset_id__in=ids)
    exceptional = CheckResult.objects.filter(
        scope, inspection_run=run, asset__environment_id=run.environment_id,
        status__in=('FAIL', 'ERROR', 'UNKNOWN'),
    ).select_related('asset', 'inspection_item_run__inspection_item').order_by('status', 'pk')[:8]
    known = {row['id'] for row in context['check_results']}
    context['check_results'].extend(serialize_check_result(row) for row in exceptional if str(row.pk) not in known)
    context['question'] = question
    context['inspection_run_id'] = str(run.pk)
    if '对比' in question or '上一次' in question:
        previous = latest_completed_launch_run(run.environment, before=run)
        if previous:
            prior = inspection_run_result(previous, check_limit=0, risk_limit=0)
            context['previous_run'] = {key: prior[key] for key in ('run', 'scope', 'summary', 'resource_summaries')}
        else:
            context['previous_run'] = None
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
        {key: row[key] for key in ('id', 'inspection_item_code', 'asset_id', 'asset_name', 'status', 'summary', 'observed_value', 'expected_value', 'evidence', 'source')}
        for row in context['check_results']
    ]
    compact = build_compact_explanation_context(context, question=question)
    references = [
        {'type': 'CHECK_RESULT', 'id': row['id'], 'label': f"{row['check']} · {row['status']}", 'source': 'CODE'}
        for row in compact['check_results']
    ]
    try:
        if gateway is None:
            from apps.conversations.services import _default_gateway
            gateway = _default_gateway()
        response = gateway.invoke(ModelRequest(messages=[
            {'role': 'system', 'content': render_explanation_system_prompt(prompt)},
            {'role': 'user', 'content': json.dumps(compact, ensure_ascii=False, separators=(',', ':'))},
        ], metadata={'purpose': 'dashboard_explanation'}))
        if not isinstance(response.action, FinalAction):
            raise LLMUnavailableError()
        validate_explanation_answer(response.action.summary, compact)
    except Exception:
        raise LLMUnavailableError('AI 解读暂不可用，请稍后重试。CODE 巡检结果已保留。') from None
    metadata = prompt_metadata(prompt)
    record_event(environment=run.environment, event_type='prompt.used', object_type='InspectionRun', object_id=run.pk,
                 payload={'prompt_key': metadata['key'], 'after_revision': metadata['revision'],
                          'after_hash': metadata['hash'], 'guard_version': metadata['guard_version']})
    return {'answer': response.action.summary, 'confidence': response.action.confidence,
            'inspection_run_id': str(run.pk), 'source': {'type': 'AI', 'provider': response.provider, 'model': response.model},
            'references': references, 'truncated': compact['truncated'], 'prompt': metadata}
