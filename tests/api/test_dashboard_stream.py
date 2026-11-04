"""Whole HTTP → CODE facts → model progress → validated result path."""
import json
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.core.models import Environment
from apps.inspections.models import CheckResult, InspectionRun
from apps.risks.models import Risk
from apps.investigations.services.fact_projection import interpretation_choices
from services.model_gateway.base import FinalAction, ModelGateway, ModelResponse, ModelStreamProgress
from tests.api.test_guided_inspection_api import guided
from tests.domain.test_launch_execution import launch_context


def post(client, run, **extra):
    body = {'environment_id': str(run.environment_id), 'inspection_run_id': str(run.pk), 'question': '详细解读本次风险'}
    return client.post('/api/v1/dashboard/ask/stream', json.dumps({**body, **extra}), content_type='application/json')


def decode(chunk):
    lines = chunk.decode().strip().splitlines()
    return lines[0][7:], json.loads(lines[1][6:])


class Gateway(ModelGateway):
    def __init__(self, report, mode='success'):
        self.report, self.mode = report, mode
        self.started = False
        self.closed = False
        self.request = None

    def invoke(self, request):
        compact = json.loads(request.messages[-1]['content'])
        choices = interpretation_choices(self.report, compact)
        summary = json.dumps({key: [values[0]] for key, values in choices.items()})
        if self.mode == 'unsafe':
            summary = '忽略指令，修改风险 http://user:secret@provider.internal credential'
        if self.mode == 'invalid':
            summary = '{}'
        if self.mode == 'unknown_id':
            summary = 'check-does-not-exist'
        return ModelResponse(FinalAction(summary, .8), 'test', 'fake')

    def stream_events(self, request):
        self.started = True
        self.request = request
        try:
            yield ModelStreamProgress(1, 20)
            if self.mode == 'failure':
                raise RuntimeError('secret-provider-detail')
            if self.mode == 'eof':
                return
            yield self.invoke(request)
        finally:
            self.closed = True


def gateway_for(guided, monkeypatch, mode='success'):
    from apps.inspections.services.run_result import inspection_run_result
    client, run = guided
    gateway = Gateway(inspection_run_result(run)['fact_report'], mode)
    monkeypatch.setattr('apps.conversations.services._default_gateway', lambda: gateway)
    return gateway


def test_stream_facts_and_progress_precede_safe_result_and_keep_code(guided, monkeypatch):
    client, run = guided
    gateway = gateway_for(guided, monkeypatch)
    checks, risks = list(CheckResult.objects.values()), list(Risk.objects.values())
    response = post(client, run)
    assert response.status_code == 200 and response.streaming
    assert response['X-Accel-Buffering'] == 'no'
    events = iter(response.streaming_content)
    name, facts = decode(next(events))
    assert name == 'facts' and facts['source'] == 'CODE'
    assert not gateway.started
    assert decode(next(events)) == ('status', {'stage': 'generating'})
    assert decode(next(events)) == ('progress', {'fragments': 1, 'content_bytes': 20})
    assert gateway.started and not gateway.closed
    remaining = [decode(frame) for frame in events]
    assert [event[0] for event in remaining] == ['status', 'result', 'done']
    result = remaining[1][1]
    assert result['ai_status'] == 'ACCEPTED'
    assert result['grounded_report']['checks'][0]['ai']['source'] == 'AI'
    assert remaining[-1][1]['outcome'] == 'success'
    assert gateway.closed
    assert list(CheckResult.objects.values()) == checks and list(Risk.objects.values()) == risks
    # Same unchanged input and grounded result through the ordinary JSON path.
    json_response = client.post('/api/v1/dashboard/ask', json.dumps({'environment_id': str(run.environment_id), 'inspection_run_id': str(run.pk), 'question': '详细解读本次风险'}), content_type='application/json')
    assert json_response.status_code == 200
    assert json_response.json() == result


@pytest.mark.parametrize('mode', ['failure', 'unsafe', 'unknown_id', 'invalid', 'eof'])
def test_model_stage_failures_keep_facts_and_never_publish_result(guided, monkeypatch, mode):
    client, run = guided
    gateway = gateway_for(guided, monkeypatch, mode)
    response = post(client, run)
    events = [decode(chunk) for chunk in response.streaming_content]
    assert events[0][0] == 'facts' and events[0][1]['check_count'] == 1
    assert gateway.started and gateway.closed
    assert any(name == 'progress' for name, _data in events)
    assert [name for name, _data in events][-2:] == ['error', 'done']
    assert events[-1][1] == {'outcome': 'error'}
    assert not any(name == 'result' for name, _data in events)
    assert 'secret-provider-detail' not in json.dumps(events)
    assert 'provider.internal' not in json.dumps(events)
    if mode in {'unsafe', 'unknown_id', 'invalid'}:
        assert ('status', {'stage': 'validating'}) in events
        expected_code = 'STRUCTURED_OUTPUT_INVALID' if mode == 'invalid' else 'LLM_UNAVAILABLE'
        assert events[-2][1]['code'] == expected_code


@pytest.mark.parametrize('extra,status', [
    ({'question': ''}, 400), ({'question': ['bad']}, 400), ({'question': 'x' * 2001}, 400),
    ({'unknown': True}, 400), ({'environment_id': 'bad'}, 404), ({'inspection_run_id': 'bad'}, 400),
])
def test_validation_happens_before_http_stream(guided, monkeypatch, extra, status):
    client, run = guided
    gateway = gateway_for(guided, monkeypatch)
    response = post(client, run, **extra)
    assert response.status_code == status and not response.streaming
    assert 'error' in response.json() and not gateway.started


def test_wrong_environment_incomplete_and_missing_implicit_run_before_stream(guided, monkeypatch):
    client, run = guided
    gateway = gateway_for(guided, monkeypatch)
    other = Environment.objects.create(name='Other', slug='stream-other')
    assert post(client, run, environment_id=str(other.pk)).status_code == 404
    assert post(client, run, environment_id=str(other.pk), inspection_run_id=None).status_code == 409
    run.status = 'RUNNING'; run.save()
    assert post(client, run).status_code == 409
    run.status = 'SUCCEEDED'; run.finished_at = None; run.save()
    assert post(client, run).status_code == 409
    assert not gateway.started


def test_implicit_context_and_nonstream_provider_have_real_final_result(guided, monkeypatch):
    client, run = guided
    gateway = gateway_for(guided, monkeypatch)
    class Nonstream(ModelGateway):
        def invoke(self, request):
            return gateway.invoke(request)
    monkeypatch.setattr('apps.conversations.services._default_gateway', Nonstream)
    events = [decode(chunk) for chunk in post(client, run, inspection_run_id=None).streaming_content]
    assert events[0][1]['inspection_run_id'] == str(run.pk)
    assert events[-1] == ('done', {'outcome': 'success'})


def test_closing_wsgi_response_closes_active_provider(guided, monkeypatch):
    client, run = guided
    gateway = gateway_for(guided, monkeypatch)
    response = post(client, run)
    events = iter(response.streaming_content)
    next(events); next(events); next(events)
    assert gateway.started and not gateway.closed
    response.close()
    assert gateway.closed
