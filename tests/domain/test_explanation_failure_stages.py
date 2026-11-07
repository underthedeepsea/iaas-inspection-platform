"""Controlled failures verify classification/redaction only; not real provider acceptance."""
import json,os,unittest
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev')
os.environ.setdefault('LOCAL_BACKGROUND_WORKER_ENABLED','false')
import django;django.setup()
from apps.investigations.services import dashboard_stream as stream
from services.model_gateway.base import StructuredOutputInvalidError,ModelResponse,FinalAction
from tests.domain import test_run_bound_explanation as bound_tests
class StageTests(unittest.TestCase):
 def setUp(self):self.run=SimpleNamespace(pk='run-current',environment='env',config_snapshot={});self.context=bound_tests.BoundExplanationTests().context()
 def decode(self,chunks):return [(chunk.decode().splitlines()[0][7:],json.loads(chunk.decode().splitlines()[1][6:])) for chunk in chunks]
 def test_prepare_failure_never_invokes_gateway_and_no_raw_exception_leaks(self):
  gateway=SimpleNamespace(stream_events=lambda request:(_ for _ in ()).throw(AssertionError('must not invoke')))
  with patch.object(stream,'inspection_run_result',return_value=self.context),patch.object(stream,'prepare_dashboard_explanation',side_effect=RuntimeError('secret-url-token-content')),self.assertLogs(stream.logger,level='WARNING') as logs:
   events=self.decode(stream.stream_dashboard_explanation(self.run,'解释',gateway=gateway))
  error=next(data for kind,data in events if kind=='error');self.assertEqual(error['stage'],'prepare');self.assertEqual(events[-1],('done',{'outcome':'error'}));self.assertNotIn('secret-url',json.dumps(events)+str(logs.output));self.assertIn('type=RuntimeError',str(logs.output))
 def test_frozen_read_failure_has_distinct_phase(self):
  with patch.object(stream,'inspection_run_result',side_effect=RuntimeError('private')):
   error=self.decode(stream.stream_dashboard_explanation(self.run,'解释'))[0][1];self.assertEqual(error['stage'],'frozen_facts')
 def test_stream_failure_and_structure_failure_stay_rejected(self):
  for failure,stage in [(RuntimeError('private-provider'),'provider_stream'),(StructuredOutputInvalidError('private-output'),'provider_output_validation')]:
   gateway=SimpleNamespace(stream_events=lambda request:(_ for _ in ()).throw(failure))
   with patch.object(stream,'inspection_run_result',return_value=self.context),patch.object(stream,'prepare_dashboard_explanation',return_value=(None,)),self.assertLogs(stream.logger,level='WARNING'):
    events=self.decode(stream.stream_dashboard_explanation(self.run,'解释',gateway=gateway));self.assertEqual(events[-2][1]['stage'],stage);self.assertFalse(any(k=='result' for k,v in events))
 def test_audit_failure_is_not_swallowed_or_presented_as_accepted(self):
  failure=RuntimeError('private audit endpoint');failure.explanation_stage='audit_record'
  gateway=SimpleNamespace(stream_events=lambda request:iter([ModelResponse(FinalAction('{}',.5),'test','controlled')]))
  with patch.object(stream,'inspection_run_result',return_value=self.context),patch.object(stream,'prepare_dashboard_explanation',return_value=(None,)),patch.object(stream,'finish_dashboard_explanation',side_effect=failure),self.assertLogs(stream.logger,level='WARNING'):
   events=self.decode(stream.stream_dashboard_explanation(self.run,'解释',gateway=gateway));self.assertEqual(events[-2][1]['stage'],'audit_record');self.assertFalse(any(k=='result' for k,v in events))

 def test_real_finish_boundary_retains_required_audit_failure_stage(self):
  from apps.investigations.services import dashboard_explanation as explanation
  failure=RuntimeError('private audit details')
  prepared=({'fact_report':{}},{'summary':{'check_count':1}},[],object(),None)
  response=ModelResponse(FinalAction('{}',.5),'test','controlled')
  with patch.object(explanation,'compose_grounded_explanation',return_value={'text':'controlled'}),patch.object(explanation,'prompt_metadata',return_value={'key':'k','revision':1,'hash':'h','guard_version':'1'}),patch.object(explanation,'record_event',side_effect=failure) as audit:
   with self.assertRaises(RuntimeError) as caught:explanation.finish_dashboard_explanation(self.run,prepared,response)
   self.assertIs(caught.exception,failure);self.assertEqual(caught.exception.explanation_stage,'audit_record');audit.assert_called_once()

 def test_grounding_failure_retains_only_safe_cause_type(self):
  from apps.investigations.services import dashboard_explanation as explanation
  response=SimpleNamespace(action=None)
  with self.assertRaises(Exception) as caught:explanation.finish_dashboard_explanation(self.run,({}, {}, [], None, None),response)
  self.assertEqual(caught.exception.explanation_stage,'grounding_validation')
  self.assertEqual(caught.exception.explanation_cause_type,'LLMUnavailableError')
