"""Direct view calls with ordinary mocked repositories; no HTTP or database."""
import json
import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev')
os.environ.setdefault('LOCAL_BACKGROUND_WORKER_ENABLED','false')
import django
django.setup()
from apps.hardware_health import profile_api as api


def request(body, environment='env', method='PATCH'):
    return SimpleNamespace(method=method,GET={'environment_id':environment} if environment else {},body=json.dumps(body).encode())

class ApiBoundaryTests(TestCase):
    def test_patch_preserves_other_labels_and_is_environment_cluster_scoped(self):
        cluster=SimpleNamespace(pk='cluster',labels={'other':'preserve'},save=MagicMock())
        with patch.object(api,'resolve_environment',return_value='resolved-env'),patch.object(api,'writable',return_value=True),patch.object(api.Asset,'objects') as manager,patch.object(api.transaction,'atomic',return_value=nullcontext()):
            manager.select_for_update.return_value.filter.return_value.first.return_value=cluster
            response=api.cluster_deployment(request({'control_plane_deployment':'MIXED'}),'cluster')
            manager.select_for_update.return_value.filter.assert_called_once_with(environment='resolved-env',asset_type='CLUSTER',pk='cluster')
            self.assertEqual(response.status_code,200)
            self.assertEqual(cluster.labels,{'other':'preserve','control_plane_deployment':'MIXED'})
            cluster.save.assert_called_once_with(update_fields=['labels'])
    def test_readonly_patch_returns_refusal_without_any_asset_write(self):
        with patch.object(api,'resolve_environment',return_value='env'),patch.object(api,'writable',return_value=False),patch.object(api.Asset,'objects') as manager:
            response=api.cluster_deployment(request({'control_plane_deployment':'DEDICATED'}),'cluster')
            self.assertEqual(response.status_code,403);manager.select_for_update.assert_not_called()
            self.assertIn('READ_ONLY',response.content.decode())
    def test_extra_fields_and_unknown_deployment_rejected(self):
        with patch.object(api,'resolve_environment',return_value='env'),patch.object(api.Asset,'objects') as manager:
            for body in [{'control_plane_deployment':'UNKNOWN'},{'control_plane_deployment':'MIXED','labels':{}},{'control_plane_deployment':None},{'control_plane_deployment':[]},{'control_plane_deployment':{}}]:
                self.assertEqual(api.cluster_deployment(request(body),'cluster').status_code,400)
            manager.select_for_update.assert_not_called()
    def test_missing_environment_and_wrong_method_rejected(self):
        self.assertEqual(api.cluster_deployment(request({},environment=None),'cluster').status_code,400)
        self.assertEqual(api.cluster_deployment(request({},method='POST'),'cluster').status_code,405)
    def test_get_is_readonly_projection_and_exposes_capability(self):
        with patch.object(api,'resolve_environment',return_value='env'),patch.object(api,'writable',return_value=False),patch.object(api.Asset,'objects'),patch.object(api.HardwareSnapshot,'objects'),patch.object(api.InferencePerformanceSnapshot,'objects'):
            response=api.profiles(SimpleNamespace(method='GET',GET={'environment_id':'env','resource_type':'HOST'}))
            self.assertEqual(response.status_code,200)
            data=json.loads(response.content)
            self.assertFalse(data['deployment_edit']['writable']);self.assertEqual(data['clusters'],[])

    def test_portrait_get_validates_pair_and_forwards_selected_identity(self):
        with patch.object(api,'resolve_environment',return_value='env'),patch.object(api,'writable',return_value=False),patch.object(api.Asset,'objects'),patch.object(api.HardwareSnapshot,'objects'),patch.object(api.InferencePerformanceSnapshot,'objects'),patch.object(api,'build_profile',return_value={'clusters':[]}) as build:
            response=api.profiles(SimpleNamespace(method='GET',GET={'environment_id':'env','view':'portraits','kind':'llm','id':'["source","engine/model"]'}))
            self.assertEqual(response.status_code,200)
            self.assertTrue(build.call_args.kwargs['portrait_mode'])
            self.assertEqual(build.call_args.kwargs['detail_id'],'["source","engine/model"]')
            response=api.profiles(SimpleNamespace(method='GET',GET={'environment_id':'env','view':'portraits','kind':'node'}))
            self.assertEqual(response.status_code,400)
