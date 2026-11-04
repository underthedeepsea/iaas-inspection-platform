"""Frozen required coverage, execution and risk separation; isolated PG fixtures."""
import copy,json,uuid
from datetime import timezone as utc
from django.utils import timezone
from new_fix_cases import MappingActivationFixTests
from apps.inspections.services.mapping_coverage import mapping_input_quality
from apps.core.mapping_loop import versions


class MappingPartialStatusTests(MappingActivationFixTests):
    def full_fixture_run(self):
        """Test-only complete existing hardware schema; no product whitelist expansion."""
        self.seed_plugin()
        from apps.hardware_health.schemas import FIELDS,parse_request
        from apps.hardware_health.services import ingest
        from apps.inspections.services.trigger import create_manual_inspection_run
        batch_id=str(uuid.uuid4());revision=self.bundle.head_revision
        start=timezone.datetime.fromtimestamp(self.window['start'],tz=utc.utc).isoformat();end=timezone.datetime.fromtimestamp(self.window['end'],tz=utc.utc).isoformat()
        snapshots=[]
        for family,kind in [('host','HOST'),('gpu','GPU')]:
            points={}
            for field in FIELDS[family]:
                value=[]if field=='xid_events'else 0 if field.startswith('ecc_')else 0.99 if field=='cpu_busy_ratio'else 0.2 if field.endswith('_ratio')else 120 if field=='temperature_celsius'else 1000 if field.endswith('total_bytes')else 300
                point={'value':value,'quality':'VALID','collected_at':start}
                if field.startswith('ecc_'):point.update(source_metric='test-only-complete-fixture',semantics='SINGLE_BIT'if field=='ecc_sbe_delta'else'DOUBLE_BIT',scope='DRAM')
                points[field]=point
            payload={'source':'demo-monitor','environment_id':str(self.env.pk),'sample_id':f'mapping:{batch_id}:{kind}','window_start':start,'window_end':end,'host_id':self.bundle.monitor_cluster_id+'-full-fixture','config_id':str(revision.pk),'kind':kind,'identity':{}if kind=='HOST'else{'gpu_uuid':self.bundle.cluster_uid+'-full-fixture','model':'SYNTHETIC_TEST_ONLY'},'metrics':{family:{'identity':{},'values':points}},'bindings':{'complete':False,'engines':[]}}
            parse_request(payload);snapshots.append(ingest(payload)[0])
        provenance={'batch_id':batch_id,'revision_id':str(revision.pk),'content_hash':revision.content_hash,'validation_id':str(uuid.uuid4()),'activation_id':str(uuid.uuid4()),'source_ref':'demo-monitor','environment_id':str(self.env.pk),'window_start':snapshots[0].window_start.isoformat(),'window_end':snapshots[0].window_end.isoformat(),'snapshot_ids':[str(row.pk)for row in snapshots],'asset_ids':[str(row.asset_id)for row in snapshots],'versions':versions(),'baseline_status':'NOT_READY','fixture':'TEST_ONLY_COMPLETE_HARDWARE_SCHEMA'}
        return create_manual_inspection_run(environment=self.env,resource_type_codes=['HOST','GPU_POOL'],ai_mode='DISABLED',explicit_hardware_snapshot_ids=provenance['snapshot_ids'],mapping_inputs=provenance)

    def test_schema_required_partial_complete_and_invalid_bindings(self):
        from apps.hardware_health.schemas import FIELDS
        run=self.full_fixture_run();quality=mapping_input_quality(run)
        self.assertEqual(quality['required_fields'],len(FIELDS['host'])+len(FIELDS['gpu']))
        self.assertEqual(quality['valid_fields'],quality['required_fields']);self.assertEqual(quality['status'],'COMPLETE')
        partial=copy.deepcopy(run.config_snapshot)
        for snapshot in partial['input']['snapshots'].values():
            for component in snapshot['payload']['metrics'].values():
                first=next(iter(component['values'].values()));first.update(value=None,quality='MISSING')
        run.config_snapshot=partial;quality=mapping_input_quality(run)
        self.assertEqual(quality['status'],'PARTIAL');self.assertLess(quality['coverage'],1);self.assertEqual(quality['missing_count'],2)
        run.config_snapshot=copy.deepcopy(partial);run.config_snapshot['mapping_inputs']['content_hash']='0'*64
        self.assertIn('EXPLICIT_BINDING_MISMATCH',mapping_input_quality(run)['binding_errors'])
        run.config_snapshot=copy.deepcopy(partial);next(iter(run.config_snapshot['input']['snapshots'].values()))['environment_id']=str(uuid.uuid4())
        self.assertIn('SNAPSHOT_SCOPE_WINDOW_REVISION_MISMATCH',mapping_input_quality(run)['binding_errors'])
        run.config_snapshot=copy.deepcopy(partial);run.config_snapshot['mapping_inputs']['snapshot_ids']=[str(uuid.uuid4())]
        self.assertIn('SNAPSHOT_SET_MISMATCH',mapping_input_quality(run)['binding_errors'])

    def test_complete_run_report_persisted_quality_and_risk_separate(self):
        from apps.inspections.services.manual_orchestrator import start_manual_inspection_run,_finish_run
        from apps.inspections.services.run_result import inspection_run_result
        from apps.inspections.models import InspectionRun,CheckResult,ResourceInspectionSummary
        run=self.full_fixture_run();start_manual_inspection_run(run.pk);run.refresh_from_db()
        self.assertEqual(run.status,'SUCCEEDED');self.assertEqual(run.config_snapshot['mapping_quality']['status'],'COMPLETE')
        before=list(CheckResult.objects.filter(inspection_run=run).order_by('pk').values('id','status','evidence'))
        report=inspection_run_result(run);self.assertEqual(report['mapping_input_quality']['coverage'],1)
        self.assertEqual(report['mapping_inputs']['snapshot_ids'],run.config_snapshot['mapping_inputs']['snapshot_ids'])
        _finish_run(run);run=InspectionRun.objects.get(pk=run.pk)
        after=list(CheckResult.objects.filter(inspection_run=run).order_by('pk').values('id','status','evidence'));self.assertEqual(before,after)
        self.assertEqual(inspection_run_result(run)['mapping_input_quality'],report['mapping_input_quality'])
        self.assertTrue(ResourceInspectionSummary.objects.filter(inspection_run=run,status='SUCCEEDED').exists())
        type(self).full_report_evidence={'run_id':str(run.pk),'status':run.status,'quality':report['mapping_input_quality'],'check_statuses':[row['status']for row in before],'report_keys':list(report),'risk_evidence_unchanged':before==after,'snapshot_ids':run.config_snapshot['mapping_inputs']['snapshot_ids']}

    def test_failed_mapping_is_never_upgraded(self):
        from apps.inspections.services.manual_orchestrator import _finish_run
        run=self.full_fixture_run();run.status='FAILED';run.save(update_fields=['status']);_finish_run(run);run.refresh_from_db()
        self.assertEqual(run.status,'FAILED');self.assertEqual(run.config_snapshot['mapping_quality']['status'],'COMPLETE')

    def test_non_mapping_default_status_and_projection_unchanged(self):
        from apps.inspections.models import InspectionRun
        from apps.inspections.services.manual_orchestrator import _finish_run
        from apps.inspections.services.run_result import inspection_run_result
        run=InspectionRun.objects.create(environment=self.env,run_date=timezone.localdate(),trigger_type='MANUAL',status='RUNNING',config_snapshot={})
        self.assertIsNone(mapping_input_quality(run));_finish_run(run);run.refresh_from_db();self.assertEqual(run.status,'SUCCEEDED')
        self.assertNotIn('mapping_quality',run.config_snapshot);self.assertNotIn('mapping_input_quality',inspection_run_result(run))
