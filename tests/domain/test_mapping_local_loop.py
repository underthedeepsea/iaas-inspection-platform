"""New isolated-PG lifecycle cases; no production environment or model calls."""
import json,time,unittest
from datetime import timedelta
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from django.utils import timezone
from apps.core import mapping_loop as loop,mapping_services as store
from apps.core.models import Environment,MappingValidation,MappingActivation,MappingCollection


class MappingLocalLoopTests(SimpleTestCase):
    databases='__all__'
    sequence=0
    def setUp(self):
        type(self).sequence+=1
        self.env=Environment.objects.create(name='Loop mock',slug='loop-'+str(self.sequence),metadata={'local_mapping':store.MOCK_METADATA})
        metrics=[{'standard_field':key,'source_metric':spec[0],'source_type':'GAUGE','source_unit':spec[1],'output_unit':spec[2],'conversion':spec[3],'labels':{},'window_seconds':300,'step_seconds':60}for key,spec in store.FIELD_SPECS.items()]
        self.content={'schema_version':store.SCHEMA_VERSION,'cluster':{'cluster_uid':'cluster-'+str(self.sequence),'monitor_cluster_id':'monitor-'+str(self.sequence),'display_name':'Synthetic loop'},'metrics':metrics}
        self.bundle=store.create_bundle(environment_id=self.env.pk,source_ref='demo-monitor',cluster_uid=self.content['cluster']['cluster_uid'],monitor_cluster_id=self.content['cluster']['monitor_cluster_id'],content=self.content,expected_head=0,reason='Initial',actor_label='self-described test')
        self.scope={'bundle_id':self.bundle.pk,'environment_id':self.env.pk,'source_ref':'demo-monitor','cluster_uid':self.bundle.cluster_uid}
        end=int(time.time())//60*60-60;self.window={'start':end-300,'end':end,'step':60,'seed':1,'fixture':'complete'}
    def receipt(self,**changes):return loop.validate(scope=self.scope,expected_head=1,kind='MOCK',**(self.window|changes))
    def activation(self,receipt,**changes):
        args={'scope':self.scope,'expected_head':1,'expected_active':0,'content_hash':self.bundle.head_revision.content_hash,'validation_id':receipt.pk,'idempotency_key':'activate','reason':'Activate synthetic','actor_label':'self-described test'};args.update(changes);return loop.activate(**args)
    def test_structure_is_not_mock_validation(self):
        row=loop.validate(scope=self.scope,expected_head=1,kind='STRUCTURE',**self.window)
        self.assertEqual(row.result['status'],'CONFIG_VALID')
        with self.assertRaises(loop.ValidationRejected):self.activation(row)
        self.assertEqual(MappingActivation.objects.filter(bundle=self.bundle).count(),0)
    def test_activation_exact_binding_atomic_idempotency(self):
        row=self.receipt();self.assertEqual(row.result['status'],'MOCK_VERIFIED');self.assertEqual(row.result['mapped_values'],{'host.cpu_busy_ratio':0.41,'gpu.temperature_celsius':41.0})
        event=self.activation(row);again=self.activation(row);self.assertEqual(event.pk,again.pk)
        self.bundle.refresh_from_db();self.assertEqual(self.bundle.active_revision_id,self.bundle.head_revision_id)
        self.assertEqual(MappingActivation.objects.filter(bundle=self.bundle).count(),1)
        with self.assertRaises(store.MappingConflict):self.activation(row,reason='Changed same key')
        with self.assertRaises(store.MappingConflict):self.activation(row,idempotency_key='other',expected_active=0)
        with self.assertRaises(loop.ValidationRejected):self.activation(row,idempotency_key='missing',expected_active=1,validation_id=None)
    def test_expired_or_changed_contract_receipt_rejected(self):
        row=self.receipt()
        with patch('apps.core.mapping_loop.timezone.now',return_value=row.valid_until):
            with self.assertRaises(loop.ValidationRejected):self.activation(row)
        with patch('apps.core.mapping_loop.versions',return_value={'changed':'contract'}):
            with self.assertRaises(loop.ValidationRejected):self.activation(row)
        self.bundle.refresh_from_db();self.assertIsNone(self.bundle.active_revision_id)
    def test_mock_missing_wrong_unit_and_no_data_never_activate(self):
        for fixture in ['missing','wrong-unit','no-data']:
            with self.subTest(fixture=fixture):
                row=self.receipt(fixture=fixture);self.assertEqual(row.result['status'],'FAILED')
                with self.assertRaises(loop.ValidationRejected):self.activation(row,idempotency_key=fixture)
        self.assertFalse(MappingCollection.objects.filter(bundle=self.bundle).exists())
    def test_new_head_and_rollback_do_not_reuse_old_receipt_or_active(self):
        row=self.receipt();event=self.activation(row)
        changed=json.loads(json.dumps(self.content));changed['cluster']['display_name']='Changed'
        store.append_revision(**self.scope,content=changed,expected_head=1,reason='Edit',actor_label='self')
        self.bundle.refresh_from_db()
        with self.assertRaises(loop.ValidationRejected):self.activation(row,expected_head=2,expected_active=1,content_hash=self.bundle.head_revision.content_hash,idempotency_key='stale')
        rolled=store.rollback_revision(**self.scope,target_version=1,expected_head=2,reason='Rollback',actor_label='self')
        self.bundle.refresh_from_db();self.assertEqual(rolled.version,3);self.assertEqual(self.bundle.active_revision_id,event.revision_id)
    def test_collect_old_ingest_exact_run_and_existing_report(self):
        from apps.inspections.models import InspectionItem,ResourceType,InspectionItemResourceType,CheckResult,InspectionRun,ResourceInspectionSummary
        from apps.inspections.rules.registry import RULES,get_code_plugin
        codes=[code for code in RULES if get_code_plugin(code).input_source=='HARDWARE_SNAPSHOT']
        self.assertTrue(codes,'Existing hardware code plugin must be registered')
        item,_=InspectionItem.objects.get_or_create(code=codes[0],defaults={'name':'Existing hardware plugin','domain':'HARDWARE','version':'1.0.0','enabled':True})
        if not item.enabled:item.enabled=True;item.save(update_fields=['enabled'])
        for code in ['HOST','GPU_POOL']:
            resource=ResourceType.objects.get(code=code);InspectionItemResourceType.objects.get_or_create(inspection_item=item,resource_type=resource)
        row=self.receipt();event=self.activation(row)
        with patch('apps.inspections.services.trigger.freeze_external_inputs',side_effect=AssertionError('latest-input path forbidden')):
            batch=loop.collect(scope=self.scope,expected_active=1,idempotency_key='collect')
        self.assertEqual(batch.status,'RUN_CREATED',batch.error_code);self.assertIsNotNone(batch.run_id)
        again=loop.collect(scope=self.scope,expected_active=1,idempotency_key='collect');self.assertEqual(batch.pk,again.pk)
        with self.assertRaises(store.MappingConflict):loop.collect(scope=self.scope,expected_active=2,idempotency_key='collect')
        from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
        start_manual_inspection_run(batch.run_id)
        run=InspectionRun.objects.get(pk=batch.run_id)
        self.assertEqual(run.config_snapshot['trigger_options']['ai_mode'],'DISABLED')
        frozen=run.config_snapshot['input']['snapshots'];self.assertEqual(sorted(value['snapshot_id']for value in frozen.values()),sorted(batch.evidence['snapshot_ids']))
        self.assertEqual(run.config_snapshot['mapping_inputs']['batch_id'],str(batch.pk));self.assertEqual(batch.evidence['baseline_status'],'NOT_READY')
        self.assertTrue(CheckResult.objects.filter(inspection_run=run).exists());self.assertTrue(ResourceInspectionSummary.objects.filter(inspection_run=run).exists())
        self.assertEqual(run.status,'PARTIAL')
        for value in frozen.values():
            missing=[point for component in value['payload']['metrics'].values()for point in component['values'].values()if point['quality']!='VALID']
            self.assertTrue(missing);self.assertTrue(all(point['value']is None for point in missing))
        type(self).chain={'batch_id':str(batch.pk),'run_id':str(run.pk),'revision_id':str(batch.revision_id),'activation_id':str(event.pk),'validation_id':str(row.pk),'snapshot_ids':batch.evidence['snapshot_ids'],'asset_ids':batch.evidence['asset_ids'],'run_status':run.status,'mapping_inputs':run.config_snapshot['mapping_inputs']}
    def test_api_structure_receipt_mock_receipt_and_activation(self):
        client=Client();base='/api/v1/mappings/bundles/'+str(self.bundle.pk)+'/'
        scope={key:str(value)for key,value in self.scope.items()if key!='bundle_id'}
        body={**scope,'expected_head':1,'kind':'MOCK',**self.window}
        response=client.post(base+'validate/',data=json.dumps(body),content_type='application/json',HTTP_HOST='localhost');self.assertEqual(response.status_code,200)
        validation=response.json()['validation_id']
        activation={**scope,'expected_head':1,'expected_active':0,'content_hash':self.bundle.head_revision.content_hash,'validation_id':validation,'idempotency_key':'api-activation','reason':'API activation','actor_label':'self'}
        response=client.post(base+'activate/',data=json.dumps(activation),content_type='application/json',HTTP_HOST='localhost');self.assertEqual(response.status_code,200)
        activation['idempotency_key']='bad-api';activation['validation_id']=None;activation['expected_active']=1
        response=client.post(base+'activate/',data=json.dumps(activation),content_type='application/json',HTTP_HOST='localhost');self.assertEqual(response.status_code,422)
