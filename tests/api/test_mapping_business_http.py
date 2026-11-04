"""Business contract suite configured by the isolated real-network HTTP worker."""
import copy
import unittest


class MappingBusinessHTTPTests(unittest.TestCase):
    # Worker injects actual urllib HTTP transport and explicit new-test-DB fixtures.
    persisted = None

    def check(self, name, condition):
        self.event(self._testMethodName + ':' + name, condition)
        self.assertTrue(condition, name)

    def creation(self, suffix=''):
        uid='business-'+self._testMethodName+suffix
        content={'schema_version':self.context['schema_version'],'cluster':{'cluster_uid':uid,'monitor_cluster_id':uid+'-monitor','display_name':'Business draft'},'metrics':[{**binding,'labels':{'cluster':uid},'window_seconds':300,'step_seconds':60} for binding in self.context['catalog']]}
        return {'environment_id':self.environments['mock'],'source_ref':'demo-monitor','cluster_uid':uid,'monitor_cluster_id':uid+'-monitor','content':content,'expected_head':0,'reason':'Business contract','actor_label':'self-described local test'}

    def scope(self, body):
        return {key:body[key] for key in ('environment_id','source_ref','cluster_uid')}

    def test_context_and_empty_scope(self):
        status,ctx=self.request('context/')
        self.check('explicit_mock_only',status==200 and self.environments['mock'] in {row['id'] for row in ctx['environments']} and self.environments['plain'] not in {row['id'] for row in ctx['environments']})
        self.check('two_bindings_and_no_owned_token_flow',len(ctx['catalog'])==2 and ctx['unimplemented_fields']==35 and 'csrf_token' not in ctx)
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

    def test_activation_is_always_unavailable(self):
        body=self.creation();status,created=self.request('bundles/',body);self.check('activation_fixture',status==201)
        status,result=self.request('bundles/'+created['bundle_id']+'/activate/',self.scope(body));self.check('refused',status==403 and result['error']['code']=='ACTIVATION_UNAVAILABLE')
