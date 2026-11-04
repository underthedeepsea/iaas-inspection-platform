"""SSE transport for the unchanged, constrained dashboard explanation."""
import json
import logging

from apps.inspections.services.run_result import inspection_run_result
from services.model_gateway.base import ModelResponse, ModelStreamProgress, StructuredOutputInvalidError
from .dashboard_explanation import prepare_dashboard_explanation, finish_dashboard_explanation, frozen_explanation_context


logger = logging.getLogger(__name__)

def _event(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n".encode('utf-8')


def stream_dashboard_explanation(run, question, *, gateway=None):
    """Own and close the provider iterator, including WSGI generator close.

    CODE facts precede model setup and survive every model terminal outcome.
    WSGI may discover a client disconnect only after the next provider chunk.
    """
    events = None
    stage = 'frozen_facts'
    try:
        context = frozen_explanation_context(run, inspection_run_result(run))
        yield _event('facts', context['fact_report'])
        yield _event('status', {'stage': 'generating'})
        stage = 'prepare'
        prepared = prepare_dashboard_explanation(run, question, context=context)
        stage = 'model_setup'
        if gateway is None:
            from apps.conversations.services import _default_gateway
            gateway = _default_gateway()
        stage = 'provider_stream'
        events = iter(gateway.stream_events(prepared[-1]))
        response = None
        for value in events:
            if response is not None:
                raise ValueError('unexpected event after result')
            if isinstance(value, ModelStreamProgress):
                yield _event('progress', {'fragments': value.fragments, 'content_bytes': value.content_bytes})
            elif isinstance(value, ModelResponse):
                response = value
            else:
                raise ValueError('invalid provider stream event')
        if response is None:
            raise ValueError('missing provider result')
        yield _event('status', {'stage': 'validating'})
        stage = 'grounded_finish'
        result = finish_dashboard_explanation(run, prepared, response)
        if result['ai_status'] != 'ACCEPTED':
            yield _event('error', {'code': 'STRUCTURED_OUTPUT_INVALID',
                                  'message': 'AI 解读未通过受约束协议，CODE 巡检事实已保留。请重试。'})
            yield _event('done', {'outcome': 'error'})
            return
        yield _event('result', result)
        yield _event('done', {'outcome': 'success'})
    except Exception as failure:
        stage = getattr(failure, 'explanation_stage', stage)
        if isinstance(failure, StructuredOutputInvalidError):
            stage = 'provider_output_validation'
        cause = failure.__cause__ or failure
        sqlstate = getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None)
        # Never log the exception text: it may contain provider URLs or output.
        logger.warning('dashboard_explanation_failed stage=%s type=%s sqlstate=%s',
                       stage, getattr(failure, 'explanation_cause_type', type(failure).__name__), sqlstate)
        messages = {
            'frozen_facts': '读取本轮冻结检查事实失败。',
            'prepare': '准备本轮解读失败，尚未进入模型流。',
            'model_setup': '现有模型入口初始化失败。',
            'provider_stream': '模型流未能完整结束或返回有效结果。',
            'provider_output_validation': '模型输出未通过既有结构协议。',
            'grounding_validation': '输出未通过本轮事实绑定校验。',
            'grounded_finish': '本轮解读组合未能完成。',
            'audit_record': '解读使用记录未能完成，结果未交付。',
        }
        yield _event('error', {'code': 'LLM_UNAVAILABLE', 'stage': stage,
                              'message': messages.get(stage, '本轮解读未能完成。') + 'CODE 巡检事实已保留。'})
        yield _event('done', {'outcome': 'error'})
    finally:
        if events is not None:
            close = getattr(events, 'close', None)
            if close is not None:
                close()
