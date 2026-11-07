"""Boundary-only SimpleTestCase suite; runner supplies dummy DB settings."""
import json
from unittest.mock import patch
from django.db import OperationalError
from django.test import RequestFactory, SimpleTestCase
from apps.core import mapping_api as api


class MappingBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post(self, **kwargs):
        options = {"HTTP_HOST": "127.0.0.1:8000", "HTTP_ORIGIN": "http://127.0.0.1:8000"}
        options.update(kwargs)
        return self.factory.post("/api/v1/mappings/bundles/", data="{}", content_type="application/json", **options)

    def test_non_json(self):
        request = self.factory.post('/x', data='{}', content_type='text/plain', HTTP_HOST='localhost', HTTP_ORIGIN='http://localhost')
        self.assertEqual(api.bundles(request).status_code, 415)

    def test_body_limit(self):
        request = self.post(); request.META['CONTENT_LENGTH'] = '65537'
        self.assertEqual(api.bundles(request).status_code, 413)

    def test_unknown_query(self):
        request = self.factory.get('/x?unknown=1', HTTP_HOST='localhost')
        self.assertEqual(api.bundles(request).status_code, 400)

    def test_repeated_query(self):
        request = self.factory.get('/x?environment_id=x&environment_id=y&source_ref=demo-monitor', HTTP_HOST='localhost')
        self.assertEqual(api.bundles(request).status_code, 400)

    def test_missing_storage_safe503(self):
        request = self.factory.get('/x', HTTP_HOST='localhost')
        with patch.object(api.Environment.objects, 'filter', side_effect=OperationalError('not disclosed')):
            response = api.context(request)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('not disclosed', response.content.decode())
