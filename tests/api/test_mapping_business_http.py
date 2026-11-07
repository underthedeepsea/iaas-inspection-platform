"""Business contracts over a real HTTP server and the Django test database."""
import copy
import json
import urllib.error
import urllib.parse
import urllib.request

from django.test import LiveServerTestCase

from apps.core import mapping_services
from apps.core.models import Environment


class MappingBusinessHTTPTests(LiveServerTestCase):
    persisted = None
    query = staticmethod(urllib.parse.urlencode)

    def setUp(self):
        super().setUp()
        self.environments = {}
        for name, metadata in (
            ("mock", {"local_mapping": mapping_services.MOCK_METADATA}),
            ("empty", {"local_mapping": mapping_services.MOCK_METADATA}),
            ("plain", {}),
        ):
            environment = Environment.objects.create(
                name="Business " + name, slug="business-http-" + name, metadata=metadata
            )
            self.environments[name] = str(environment.pk)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        status, self.context = self.request("context/")
        self.assertEqual(status, 200, "real HTTP context setup")

    def request(self, path, data=None, headers=None, raw=None):
        body = raw
        if body is None and data is not None:
            body = json.dumps(data).encode("utf-8")
        request_headers = {} if body is None else {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(
            self.live_server_url + "/api/v1/mappings/" + path,
            data=body, headers=request_headers,
        )
        try:
            response = self._opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            try:
                payload = json.loads(response.read())
            except (ValueError, UnicodeError):
                payload = None
            return response.status, payload

    def event(self, name, condition):
        print(json.dumps({
            "assertion": "BUSINESS_HTTP:" + name,
            "status": "PASS" if condition else "FAIL",
        }), flush=True)

    def check(self, name, condition):
        self.event(self._testMethodName + ':' + name, condition)
        self.assertTrue(condition, name)

    def creation(self, suffix=''):
        uid='business-'+self._testMethodName+suffix
        approved_fields = {"host.cpu_busy_ratio", "gpu.temperature_celsius"}
        bindings = [binding for binding in self.context["catalog"] if binding["standard_field"] in approved_fields]
        self.assertEqual(len(bindings), 2, "context must provide both approved bindings once")
        self.assertEqual({binding["standard_field"] for binding in bindings}, approved_fields)
        content={'schema_version':self.context['schema_version'],'cluster':{'cluster_uid':uid,'monitor_cluster_id':uid+'-monitor','display_name':'Business draft'},'metrics':[{**binding,'labels':{'cluster':uid},'window_seconds':300,'step_seconds':60} for binding in bindings]}
        return {'environment_id':self.environments['mock'],'source_ref':'demo-monitor','cluster_uid':uid,'monitor_cluster_id':uid+'-monitor','content':content,'expected_head':0,'reason':'Business contract','actor_label':'self-described local test'}

    def scope(self, body):
        return {key:body[key] for key in ('environment_id','source_ref','cluster_uid')}

    def test_context_and_empty_scope(self):
        status,ctx=self.request('context/')
        self.check('explicit_mock_only',status==200 and self.environments['mock'] in {row['id'] for row in ctx['environments']} and self.environments['plain'] not in {row['id'] for row in ctx['environments']})
        self.check('no_owned_token_flow','csrf_token' not in ctx)
        status,data=self.request('bundles/?'+self.query({'environment_id':self.environments['empty'],'source_ref':'demo-monitor'}))
        self.check('empty_is_not_fixture',status==200 and data['items']==[])

    def test_full_lifecycle_conflict_and_rollback(self):
        body=self.creation();status,first=self.request('bundles/',body)
        self.check('create_full_draft',status==201 and first['content']==body['content'] and first['head_version']==1 and first['status']=='DRAFT' and first['validation']=='NOT_RUN')
        scope=self.scope(body);base='bundles/'+first['bundle_id']+'/'
        status,read=self.request(base+'?'+self.query(scope));self.check('read_hash_content',status==200 and read['content_hash']==first['content_hash'] and read['content']==body['content'])
        changed=copy.deepcopy(body['content']);changed['cluster']['display_name']='Edited server draft';changed['metrics'][0]['labels']['edition']='v2'
        edit={**scope,'content':changed,'expected_head':1,'reason':'Edit whole draft','actor_label':'self-described local test'}
        status,second=self.request(base+'revisions/',edit);self.check('append_v2',status==201 and second['head_version']==2 and second['content']==changed)
        status,conflict=self.request(base+'revisions/',edit);self.check('409_stale_head',status==409 and conflict['error']['code']=='HEAD_CONFLICT')
        status,read=self.request(base+'?'+self.query(scope));self.check('conflict_did_not_overwrite',status==200 and read['head_version']==2 and read['content']==changed)
        status,history=self.request(base+'revisions/?'+self.query(scope));self.check('immutable_history_and_count',status==200 and len(history['items'])==2 and history['items'][1]['content_hash']==first['content_hash'] and history['items'][1]['content']==body['content'])
        status,rolled=self.request(base+'rollback/',{**scope,'target_version':1,'expected_head':2,'reason':'Clone old draft','actor_label':'self-described local test'})
        self.check('rollback_new_v3_draft',status==201 and rolled['head_version']==3 and rolled['content']==body['content'] and rolled['content_hash']==first['content_hash'] and rolled['status']=='DRAFT' and rolled['validation']=='NOT_RUN')
        status,history=self.request(base+'revisions/?'+self.query(scope));self.check('rollback_parent_metadata',status==200 and len(history['items'])==3 and history['items'][0]['parent_revision'] is not None and history['items'][0]['rollback_from'] is not None)
        type(self).persisted={'base':base,'scope':scope,'content':rolled['content'],'hash':rolled['content_hash'],'head':3}

    def test_scope_refusals(self):
        body=self.creation();status,first=self.request('bundles/',body);self.check('scope_fixture_created',status==201)
        scope=self.scope(body);base='bundles/'+first['bundle_id']+'/'
        for name,changes in [('cross_environment',{'environment_id':self.environments['empty']}),('wrong_uid',{'cluster_uid':'wrong-uid'})]:
            status,_=self.request(base+'?'+self.query(scope|changes));self.check(name,status==403)
        for name,environment,source in [('nonmock',self.environments['plain'],'demo-monitor'),('unknown_source',self.environments['mock'],'other')]:
            status,_=self.request('bundles/?'+self.query({'environment_id':environment,'source_ref':source}));self.check(name,status==403)

    def test_complete_bounded_input_contract(self):
        original=self.creation()
        variants=[]
        bad=copy.deepcopy(original);bad['expected_head']=True;variants.append(('bool_head',bad,400))
        bad=copy.deepcopy(original);bad['unknown']=True;variants.append(('unknown_field',bad,400))
        bad=copy.deepcopy(original);bad['content']['metrics']=[];variants.append(('empty_metrics',bad,400))
        bad=copy.deepcopy(original);bad['content']['metrics'][0]['step_seconds']=0;variants.append(('zero_step',bad,400))
        bad=copy.deepcopy(original);bad['content']['metrics'][0]['source_unit']='bytes';variants.append(('wrong_unit',bad,400))
        bad=copy.deepcopy(original);bad['content']['cluster']['cluster_uid']='other';variants.append(('uid_mismatch',bad,403))
        bad=copy.deepcopy(original);bad['content']['metrics'][0]['conversion']=float('nan');variants.append(('nonfinite',bad,400))
        for name,body,expected in variants:
            with self.subTest(name=name):
                status,_=self.request('bundles/',body);self.check(name,status==expected)
        for name,headers,raw,expected in [('non_json',{'Content-Type':'text/plain'},b'{}',415),('invalid_json',{},b'{',400),('body_limit',{},b' '*65537,413)]:
            status,_=self.request('bundles/',original,headers,raw);self.check(name,status==expected)

    def test_reverse_identity_uniqueness_and_environment_isolation(self):
        body=self.creation();status,created=self.request('bundles/',body);self.check('first_identity',status==201)
        status,_=self.request('bundles/',body);self.check('same_uid_conflict',status==409)
        other=copy.deepcopy(body);other['cluster_uid']+='-other';other['content']['cluster']['cluster_uid']=other['cluster_uid']
        status,_=self.request('bundles/',other);self.check('same_monitor_conflict',status==409)
        status,separate=self.request('bundles/',body|{'environment_id':self.environments['empty']});self.check('cross_environment_positive',status==201 and separate['bundle_id']!=created['bundle_id'])

