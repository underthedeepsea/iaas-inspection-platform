"""Narrow trace repair and active/admission TTL distinction; isolated PG only."""
import json
from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone
from tests.domain.test_mapping_local_loop import MappingLocalLoopTests
from apps.core import mapping_loop as loop,mapping_services as store


class MappingActivationFixTests(MappingLocalLoopTests):
    def seed_plugin(self):
        from apps.inspections.models import InspectionItem,ResourceType,InspectionItemResourceType
        from apps.inspections.rules.registry import RULES,get_code_plugin
        codes=[code for code in RULES if get_code_plugin(code).input_source=='HARDWARE_SNAPSHOT']
        self.assertTrue(codes)
        item,_=InspectionItem.objects.get_or_create(code=codes[0],defaults={'name':'Existing hardware plugin','domain':'HARDWARE','version':'1.0.0','enabled':True})
        if not item.enabled:item.enabled=True;item.save(update_fields=['enabled'])
        for code in ['HOST','GPU_POOL']:
            InspectionItemResourceType.objects.get_or_create(inspection_item=item,resource_type=ResourceType.objects.get(code=code))

    def test_activation_ttl_before_equal_after(self):
        row=self.receipt()
        with patch('apps.core.mapping_loop.timezone.now',return_value=row.valid_until-timedelta(microseconds=1)):
            self.assertIsNotNone(self.activation(row))
        for label,now in [('equal',row.valid_until),('after',row.valid_until+timedelta(microseconds=1))]:
            with self.subTest(boundary=label),patch('apps.core.mapping_loop.timezone.now',return_value=now):
                with self.assertRaises(loop.ValidationRejected):self.activation(row,expected_active=1,idempotency_key=label)

    def test_expired_active_collects_fresh_exact_inputs_with_quality_and_scope(self):
        self.seed_plugin()
        old_now=timezone.now()-timedelta(minutes=11)
        old_end=int(old_now.timestamp())//60*60-60
        self.window.update(start=old_end-300,end=old_end)
        with patch('apps.core.mapping_loop.timezone.now',return_value=old_now):
            row=self.receipt();event=self.activation(row)
        self.assertLess(row.valid_until,timezone.now())
        with self.assertRaises(loop.ValidationRejected):self.activation(row,expected_active=1,idempotency_key='late-reactivation')
        with patch('apps.inspections.services.trigger.freeze_external_inputs',side_effect=AssertionError('latest path forbidden')):
            batch=loop.collect(scope=self.scope,expected_active=1,idempotency_key='live-after-expiry')
        self.assertEqual(batch.status,'RUN_CREATED',batch.error_code)
        self.assertGreater(batch.binding['end'],row.binding['end']+600)
        self.assertLessEqual(timezone.now().timestamp()-batch.binding['end'],61)
        self.assertNotEqual(batch.evidence['raw_hash'],row.result['raw_hash'])
        self.assertEqual(batch.evidence['activation_validation_raw_hash'],row.result['raw_hash'])
        self.assertEqual(batch.evidence['mapped_values'],{'host.cpu_busy_ratio':0.41,'gpu.temperature_celsius':41.0})
        from apps.inspections.services.manual_orchestrator import start_manual_inspection_run
        from apps.inspections.models import InspectionRun,CheckResult,ResourceInspectionSummary
        start_manual_inspection_run(batch.run_id);run=InspectionRun.objects.get(pk=batch.run_id)
        self.assertEqual(run.status,'PARTIAL');self.assertEqual(run.config_snapshot['trigger_options']['ai_mode'],'DISABLED')
        self.assertTrue(CheckResult.objects.filter(inspection_run=run).exists());self.assertTrue(ResourceInspectionSummary.objects.filter(inspection_run=run).exists())
        frozen=run.config_snapshot['input']['snapshots']
        self.assertEqual(sorted(value['snapshot_id']for value in frozen.values()),sorted(batch.evidence['snapshot_ids']))
        self.assertEqual({value['payload']['kind']for value in frozen.values()},{'HOST','GPU'})
        for value in frozen.values():
            self.assertTrue(all(point['value']is None for component in value['payload']['metrics'].values()for point in component['values'].values()if point['quality']!='VALID'))
        from apps.inspections.services.inference_freeze import freeze_exact_hardware_inputs
        for override in [{'batch_id':'wrong-batch'},{'revision_id':'wrong-revision'}]:
            with self.subTest(override=override),self.assertRaises(ValueError):
                freeze_exact_hardware_inputs(batch.evidence['snapshot_ids'],environment_id=self.env.pk,provenance=batch.evidence|override,as_of=timezone.now())
        with self.assertRaises(store.MappingConflict):loop.collect(scope=self.scope,expected_active=2,idempotency_key='switched')
        with patch('apps.core.mapping_loop.versions',return_value={'invalid':'policy'}):
            with self.assertRaises(loop.ValidationRejected):loop.collect(scope=self.scope,expected_active=1,idempotency_key='bad-policy')
        self.env.is_active=False;self.env.save(update_fields=['is_active'])
        with self.assertRaises(store.MappingScopeError):loop.collect(scope=self.scope,expected_active=1,idempotency_key='disabled-environment')
        self.env.is_active=True;self.env.save(update_fields=['is_active'])
        changed=json.loads(json.dumps(self.content));changed['cluster']['display_name']='New draft'
        store.append_revision(**self.scope,content=changed,expected_head=1,reason='Draft',actor_label='self')
        store.rollback_revision(**self.scope,target_version=1,expected_head=2,reason='Rollback draft',actor_label='self')
        self.bundle.refresh_from_db();self.assertEqual(self.bundle.active_revision_id,event.revision_id)
        self.assertEqual(InspectionRun.objects.get(pk=run.pk).config_snapshot['input'],run.config_snapshot['input'])
        type(self).expiry_chain={'batch_id':str(batch.pk),'run_id':str(run.pk),'activation_id':str(event.pk),'validation_id':str(row.pk),'validation_valid_until':row.valid_until.isoformat(),'receipt_window':row.binding,'fresh_window':batch.binding,'snapshot_ids':batch.evidence['snapshot_ids'],'run_status':run.status,'frozen_mapping':run.config_snapshot['mapping_inputs']}
