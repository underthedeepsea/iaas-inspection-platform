"""Run-bound dashboard answers in existing conversation fields; GET never writes."""
import json
from contextlib import contextmanager
from copy import deepcopy
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.investigations.models import Conversation, ConversationMessage
from apps.inspections.models import InspectionRun
from apps.audits.models import AuditEvent
from .fact_projection import INTERPRETATIONS, allowed_interpretations, compose_grounded_explanation

TYPE = 'DASHBOARD_EXPLANATION_V1'

def validate_answer(run, answer):
    from .dashboard_explanation import frozen_explanation_context
    from apps.inspections.services.run_result import inspection_run_result
    if not isinstance(answer, dict) or answer.get('inspection_run_id') != str(run.pk):
        raise ValueError('answer run mismatch')
    if answer.get('ai_status') != 'ACCEPTED' or run.finished_at is None or run.status not in ('SUCCEEDED', 'PARTIAL'):
        raise ValueError('answer not accepted or run incomplete')
    report = answer.get('grounded_report') or {}
    if report.get('source') != 'CODE' or report.get('ai_status') != 'ACCEPTED':
        raise ValueError('invalid grounded protocol')
    context = frozen_explanation_context(run, inspection_run_result(run))
    if parse_datetime(answer.get('fact_cutoff') or '') != run.finished_at:
        raise ValueError('answer cutoff mismatch')
    facts = {str(row['id']): row for row in context['fact_report']['checks']}
    refs = answer.get('references')
    rows = report.get('checks')
    if not isinstance(refs, list) or not refs or not isinstance(rows, list) or not rows:
        raise ValueError('missing references')
    ids = [row.get('id') for row in rows]
    if len(ids) != len(set(ids)) or any(i not in facts for i in ids):
        raise ValueError('invalid grounded checks')
    if any(ref.get('type') != 'CHECK_RESULT' or ref.get('source') != 'CODE' or ref.get('id') not in facts for ref in refs):
        raise ValueError('invalid check reference')
    # Same CODE label used by prepare_dashboard_explanation, bound to frozen checks.
    for ref in refs:
        fact = facts[ref['id']]
        expected_label = f"{fact['asset_name']} · {fact['check']} · {fact['status']}"
        if ref.get('label') != expected_label:
            raise ValueError('reference label differs from frozen CODE')
    cited = {ref['id'] for ref in refs}
    accepted = 0
    for row in rows:
        if row.get('source') != 'CODE':
            raise ValueError('invalid fact source')
        ai = row.get('ai')
        if ai is None:
            continue
        keys = ai.get('keys')
        if row['id'] not in cited or ai.get('source') != 'AI' or ai.get('check_id') != row['id'] or not isinstance(keys, list) or not 1 <= len(keys) <= 2 or len(set(keys)) != len(keys):
            raise ValueError('invalid interpretation binding')
        allowed = allowed_interpretations(facts[row['id']])
        if any(key not in allowed for key in keys):
            raise ValueError('invalid interpretation key')
        if ai.get('impact') != '；'.join(INTERPRETATIONS[key][0] for key in keys) or ai.get('next_check') != '；'.join(INTERPRETATIONS[key][1] for key in keys):
            raise ValueError('invalid interpretation text')
        accepted += 1
    if not accepted or report.get('accepted_count') != accepted:
        raise ValueError('invalid accepted count')
    source = answer.get('source') or {}
    if source.get('type') != 'AI' or not source.get('model') or not source.get('provider'):
        raise ValueError('missing model provenance')
    # Re-render from frozen CODE and validated selection keys. Never trust persisted CODE text.
    selections = {row['id']: row['ai']['keys'] for row in rows if row.get('ai') is not None}
    compact = {'check_results': [{'id': ref['id']} for ref in refs],
        'selected_count': len(cited), 'omitted_count': context['fact_report']['check_count'] - len(cited),
        'summary': {'check_count': context['fact_report']['check_count']}, 'previous_run': None}
    canonical = compose_grounded_explanation(context['fact_report'], compact, json.dumps(selections))
    if canonical['ai_status'] != 'ACCEPTED' or report.get('checks') != canonical['checks']:
        raise ValueError('CODE checks differ from frozen rendering')
    if report.get('coverage_text') != canonical['coverage_text'] or report.get('text') != canonical['text'] or answer.get('answer') != canonical['text']:
        raise ValueError('CODE answer differs from frozen rendering')
    if report.get('comparison_text') not in (canonical['comparison_text'], '本次智能解读仅使用当前Run冻结事实，未读取上次运行或实时风险。'):
        raise ValueError('CODE comparison differs from frozen scope')
    return deepcopy(answer)


def save_answer(run, answer, *, generated_at=None, execution_id=None, audit_id=None, source_metadata=None, usage=None, usage_source=None):
    """Internal only: serialize writers on the existing run, deduplicate execution."""
    validated = validate_answer(run, answer)
    generated = generated_at or timezone.now()
    if isinstance(generated, str):
        generated = parse_datetime(generated)
    if generated is None or timezone.is_naive(generated):
        raise ValueError('invalid generation time')
    with transaction.atomic():
        # Only this authorized write transaction overrides a readonly session.
        if connection.vendor == 'postgresql' and not connection.in_atomic_block:
            raise ValueError('missing transaction')
        # The outer caller establishes READ WRITE before any SELECT in this transaction.
        locked = InspectionRun.objects.select_for_update().get(pk=run.pk, environment_id=run.environment_id)
        messages = ConversationMessage.objects.filter(conversation__environment_id=locked.environment_id,
            conversation__context_type=Conversation.ContextType.RESOURCE_RUN, conversation__context_id=locked.pk,
            role=ConversationMessage.Role.ASSISTANT, structured_content__type=TYPE)
        if execution_id:
            existing = messages.filter(structured_content__execution_id=execution_id).first()
            if existing:
                return existing
        if audit_id and not AuditEvent.objects.filter(pk=audit_id, environment_id=run.environment_id,
            object_type='InspectionRun', object_id=str(run.pk), event_type='prompt.used').exists():
            raise ValueError('audit does not belong to run')
        conversation = Conversation.objects.filter(environment_id=run.environment_id, context_type=Conversation.ContextType.RESOURCE_RUN,
            context_id=run.pk, title='本轮智能解读').order_by('created_at').first()
        if conversation is None:
            conversation = Conversation.objects.create(environment_id=run.environment_id, context_type=Conversation.ContextType.RESOURCE_RUN,
                context_id=run.pk, title='本轮智能解读')
        data = {'type': TYPE, 'environment_id': str(run.environment_id), 'inspection_run_id': str(run.pk),
            'answer': validated, 'generated_at': generated.isoformat(), 'execution_id': execution_id,
            'audit_id': str(audit_id) if audit_id else None, 'source_metadata': source_metadata or {}, 'usage': dict(usage) if usage is not None else None, 'usage_source': usage_source}
        return ConversationMessage.objects.create(conversation=conversation, role=ConversationMessage.Role.ASSISTANT,
            content=validated['answer'], structured_content=data, model_provider=validated['source']['provider'],
            model_name=validated['source']['model'], prompt_version=None,
            input_tokens=int((usage or {}).get('prompt_tokens', (usage or {}).get('input_tokens')) or 0), output_tokens=int((usage or {}).get('completion_tokens', (usage or {}).get('output_tokens')) or 0))


def serialize_message(message):
    data = message.structured_content
    return {'status': 'SAVED', 'answer': data['answer'], 'saved': {
        'message_id': str(message.pk), 'conversation_id': str(message.conversation_id),
        'environment_id': data['environment_id'], 'inspection_run_id': data['inspection_run_id'],
        'created_at': message.created_at.isoformat(), 'generated_at': data['generated_at'],
        'execution_id': data.get('execution_id'), 'audit_id': data.get('audit_id'),
        'source_metadata': data.get('source_metadata', {})}}


def latest_answer(run):
    messages = ConversationMessage.objects.filter(conversation__environment_id=run.environment_id,
        conversation__context_type=Conversation.ContextType.RESOURCE_RUN, conversation__context_id=run.pk,
        role=ConversationMessage.Role.ASSISTANT, structured_content__type=TYPE).order_by('-created_at', '-pk')
    for message in messages:
        data = message.structured_content
        if data.get('environment_id') != str(run.environment_id) or data.get('inspection_run_id') != str(run.pk):
            continue
        try:
            validate_answer(run, data.get('answer'))
        except (ValueError, TypeError, KeyError):
            continue
        return serialize_message(message)
    return {'status': 'EMPTY', 'answer': None, 'saved': None}


@contextmanager
def explanation_write_transaction():
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ WRITE')
        yield
