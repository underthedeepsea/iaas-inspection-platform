"""No network: routing structure and in-memory redirect/ownership contracts."""
import os,unittest,json
from unittest.mock import patch
import httpx
from services.model_gateway.ollama import OllamaProvider
from services.model_gateway.base import ModelRequest,LLMUnavailableError
class LoopbackTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{'OLLAMA_BASE_URL':'http://127.0.0.1:11434','OLLAMA_MODEL':'local','LLM_TIMEOUT_SECONDS':'3','HTTP_PROXY':'http://127.0.0.1:7897','ALL_PROXY':'http://127.0.0.1:7897','NO_PROXY':''});self.env.start()
 def tearDown(self):self.env.stop()
 def request(self,purpose='dashboard_explanation'):return ModelRequest(messages=[],metadata={'purpose':purpose})
 def test_exact_purposes_use_proxy_free_owned_client_and_close(self):
  for purpose in ('dashboard_explanation','inspection_explanation'):
   provider=OllamaProvider()
   with provider._chat_client(self.request(purpose)) as client:
    self.assertFalse(client._trust_env);self.assertFalse(client.follow_redirects)
    transport=client._transport_for_url(httpx.URL('http://127.0.0.1:11434/api/chat'))
    self.assertEqual(type(transport._pool).__name__,'ConnectionPool')
   self.assertTrue(client.is_closed)
 def test_other_purpose_alias_port_and_path_preserve_existing_proxy_client(self):
  for base,purpose in [('http://127.0.0.1:11434','other'),('http://localhost:11434','dashboard_explanation'),('http://127.0.0.1:11435','dashboard_explanation'),('http://127.0.0.1:11434/path','dashboard_explanation')]:
   with patch.dict(os.environ,{'OLLAMA_BASE_URL':base}):
    provider=OllamaProvider();self.assertFalse(provider._direct_inspection_chat(self.request(purpose)))
    with provider._chat_client(self.request(purpose)) as client:self.assertIs(client,httpx)
  with httpx.Client() as existing:
   self.assertEqual(type(existing._transport_for_url(httpx.URL('http://127.0.0.1:11434/api/chat'))._pool).__name__,'HTTPProxy')
 def test_redirect_has_one_hop_for_invoke_and_stream_and_does_not_close_injected_client(self):
  for stream in (False,True):
   calls=[]
   def handler(request):calls.append(str(request.url));return httpx.Response(307,headers={'Location':'https://not-authorized.invalid/collect'},request=request)
   with httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
    provider=OllamaProvider(client=client)
    with self.assertRaises(LLMUnavailableError):
     if stream:list(provider.stream_events(self.request()))
     else:provider.invoke(self.request())
    self.assertEqual(calls,['http://127.0.0.1:11434/api/chat']);self.assertFalse(client.is_closed)
 def test_success_injected_client_payload_and_parse_remain_unchanged(self):
  payload={}
  def handler(request):
   payload.update(json.loads(request.content));return httpx.Response(200,json={'message':{'content':'{"action":"FINAL","answer":{"summary":"controlled","confidence":0.5}}'}},request=request)
  with httpx.Client(transport=httpx.MockTransport(handler)) as client:
   result=OllamaProvider(http_client=client).invoke(self.request())
   self.assertEqual(result.action.summary,'controlled');self.assertEqual(payload['format'],'json');self.assertFalse(payload['think']);self.assertEqual(payload['options']['num_predict'],1536);self.assertFalse(client.is_closed)
