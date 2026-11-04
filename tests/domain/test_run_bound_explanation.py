"""Pure copied contexts and mocked prompt store; never opens database or invokes LLM."""
import os,json,unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev')
os.environ.setdefault('LOCAL_BACKGROUND_WORKER_ENABLED','false')
import django
django.setup()
from apps.investigations.services.dashboard_explanation import frozen_explanation_context,prepare_dashboard_explanation
from apps.investigations.services.dashboard_stream import stream_dashboard_explanation
class BoundExplanationTests(unittest.TestCase):
 def context(self):
  return {'run':{'id':'run-current','run_date':'2026-10-30','status':'SUCCEEDED','finished_at':'2026-10-30T03:00:00Z'},'summary':{'check_count':1},'resource_summaries':[],'risks':[{'id':'live-risk','title':'today','severity':'P1','status':'RECOVERED','primary_asset_id':'a'}],'previous_run':{'run':{'id':'previous'}},'fact_report':{'checks':[]},'check_results':[{'id':'c','inspection_item_code':'hardware.host_health','asset_id':'a','asset_name':'host','status':'UNKNOWN','summary':'快照对象身份不符','observed_value':{},'expected_value':{},'evidence':{'reason_code':'IDENTITY_MISMATCH'},'source':{},'checked_at':'2026-10-30T02:59:00Z','risk_references':[{'id':'live-risk','status':'RECOVERED'}]}]}
 def test_freeze_copy_strips_live_risks_previous_and_reprojects_without_mutating_api(self):
  original=self.context();saved=deepcopy(original);run=SimpleNamespace(pk='run-current',config_snapshot={})
  result=frozen_explanation_context(run,original)
  self.assertEqual(original,saved);self.assertIsNone(result['previous_run']);self.assertEqual(result['risks'],[]);self.assertEqual(result['fact_report']['checks'][0]['risks'],[])
  self.assertEqual(result['fact_report']['fact_cutoff'],'2026-10-30T03:00:00Z')
  self.assertEqual(result['check_results'][0]['summary'],'快照对象身份不符')
 def test_model_input_is_bound_even_for_comparison_question_and_has_cutoff(self):
  run=SimpleNamespace(pk='run-current',config_snapshot={})
  with patch('apps.investigations.services.dashboard_explanation.load_explanation_prompt',return_value=object()),patch('apps.investigations.services.dashboard_explanation.render_explanation_system_prompt',return_value='guard'),patch('apps.investigations.services.dashboard_explanation.latest_completed_launch_run') as previous:
   prepared=prepare_dashboard_explanation(run,'对比上一次',context=self.context());request=prepared[-1];wire=json.dumps(request.messages,ensure_ascii=False)
   self.assertIn('2026-10-30T03:00:00Z',wire);self.assertIn('run-current',wire);self.assertNotIn('live-risk',wire);self.assertNotIn('RECOVERED',wire);previous.assert_not_called()
   self.assertEqual(prepared[2][0]['id'],'c')
 def test_wrong_run_rejected(self):
  with self.assertRaises(ValueError):frozen_explanation_context(SimpleNamespace(pk='other'),self.context())
 def test_stream_first_fact_is_frozen_even_when_provider_fails(self):
  with patch('apps.investigations.services.dashboard_stream.inspection_run_result',return_value=self.context()):
   stream=stream_dashboard_explanation(SimpleNamespace(pk='run-current',config_snapshot={}), '解释')
   first=next(stream).decode();self.assertNotIn('RECOVERED',first);self.assertNotIn('live-risk',first);self.assertIn('run-current',first);stream.close()
