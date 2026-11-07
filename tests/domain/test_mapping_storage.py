"""Pure tests only; run with dedicated dummy database settings, never product config."""
import copy
import hashlib
import json
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.core.mapping_services import (
    MOCK_METADATA, SCHEMA_VERSION, MappingConflict, MappingInputError, MappingScopeError,
    _append, _write_input, check_mock_environment, create_bundle, validate_content, validate_version,
)
from apps.core.models import MappingBundle, MappingRevision


def package():
    return {"schema_version": SCHEMA_VERSION, "cluster": {"cluster_uid": "mock-a", "monitor_cluster_id": "monitor-a", "display_name": "模拟集群"}, "metrics": [{"standard_field": "host.cpu_busy_ratio", "source_metric": "demo.host.cpu_busy", "source_type": "GAUGE", "source_unit": "percent", "output_unit": "ratio", "conversion": "DIVIDE_100", "labels": {"cluster": "mock-a"}, "window_seconds": 300, "step_seconds": 60}]}


class MappingStoragePureTests(SimpleTestCase):
    def validate(self, data):
        return validate_content(data, cluster_uid="mock-a", monitor_cluster_id="monitor-a")

    def rejected(self, data):
        with self.assertRaises(MappingInputError):
            self.validate(data)

    def test_full_package_and_hash_preserved(self):
        data = package()
        detached, canonical, digest = self.validate(data)
        self.assertEqual(detached, data)
        self.assertEqual(json.loads(canonical), data)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)
        detached["metrics"].clear()
        self.assertEqual(len(data["metrics"]), 1)

    def test_key_order_is_canonical(self):
        data = package()
        self.assertEqual(self.validate(data)[1:], self.validate(dict(reversed(list(data.items()))))[1:])

    def test_gpu_representative_binding(self):
        data = package()
        data["metrics"][0].update(standard_field="gpu.temperature_celsius", source_metric="demo.gpu.temperature", source_unit="celsius", output_unit="celsius", conversion="IDENTITY")
        self.assertEqual(self.validate(data)[0], data)

    def test_unknown_package_fields(self):
        for key in ("active", "url", "source_ref", "script"):
            data = package(); data[key] = "injected"
            self.rejected(data)

    def test_unknown_nested_fields(self):
        for section in ("cluster", "metric"):
            data = package()
            (data["cluster"] if section == "cluster" else data["metrics"][0])["script"] = "exec"
            self.rejected(data)

    def test_missing_fields(self):
        for key in package():
            data = package(); del data[key]
            self.rejected(data)

    def test_schema_version_rejected(self):
        data = package(); data["schema_version"] = "snapshot-v1"
        self.rejected(data)

    def test_cross_cluster_uid_rejected(self):
        data = package(); data["cluster"]["cluster_uid"] = "other"
        with self.assertRaises(MappingScopeError): self.validate(data)

    def test_monitor_identity_rejected(self):
        data = package(); data["cluster"]["monitor_cluster_id"] = "other"
        with self.assertRaises(MappingScopeError): self.validate(data)

    def test_scope_tokens_reject_urls_paths_scripts(self):
        for value in ("https://host", "/tmp/a", "<script>", "bad\n", "a" * 129):
            with self.assertRaises(MappingInputError):
                validate_content(package(), cluster_uid=value, monitor_cluster_id="monitor-a")

    def test_metrics_collection_bounds_and_duplicates(self):
        for metrics in ([], {}, [package()["metrics"][0]] * 38, package()["metrics"] * 2):
            data = package(); data["metrics"] = metrics
            self.rejected(data)

    def test_unknown_standard_field(self):
        data = package(); data["metrics"][0]["standard_field"] = "demo.cpu"
        self.rejected(data)

    def test_conversion_and_source_whitelist(self):
        for key, value in (("conversion", "*100"), ("source_metric", "http://real"), ("source_unit", "seconds"), ("output_unit", "bytes"), ("source_type", "COUNTER")):
            data = package(); data["metrics"][0][key] = value
            self.rejected(data)

    def test_nonfinite_values(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            data = package(); data["metrics"][0]["conversion"] = value
            self.rejected(data)

    def test_numeric_string_and_bool_window_rejected(self):
        for key in ("window_seconds", "step_seconds"):
            for value in (True, False, "60", 60.0, 0, -1, 3601):
                data = package(); data["metrics"][0][key] = value
                self.rejected(data)

    def test_step_larger_than_window(self):
        data = package(); data["metrics"][0]["step_seconds"] = 301
        self.rejected(data)

    def test_labels_structured_and_bounded(self):
        for labels in ("cluster=mock-a", {"x": "https://real"}, {str(i): "x" for i in range(17)}, {"x": True}):
            data = package(); data["metrics"][0]["labels"] = labels
            self.rejected(data)

    def test_display_name_bounds_and_scripts(self):
        for value in ("", "x" * 129, "<script>alert(1)</script>", "https://real", "bad\n"):
            data = package(); data["cluster"]["display_name"] = value
            self.rejected(data)

    def test_explicit_mock_marker_acceptance(self):
        for env_type in ("DEV", "TEST", "PROD_SIM"):
            env = SimpleNamespace(environment_type=env_type, is_active=True, metadata={"local_mapping": copy.deepcopy(MOCK_METADATA)})
            check_mock_environment(env, "demo-monitor")

    def test_dev_test_are_not_mock_by_default(self):
        for env_type in ("DEV", "TEST", "PROD_SIM"):
            with self.assertRaises(MappingScopeError):
                check_mock_environment(SimpleNamespace(environment_type=env_type, is_active=True, metadata={}), "demo-monitor")

    def test_inactive_wrong_type_source_marker(self):
        valid = dict(environment_type="TEST", is_active=True, metadata={"local_mapping": MOCK_METADATA})
        for change in ({"is_active": False}, {"environment_type": "PROD"}, {"metadata": []}, {"metadata": {"local_mapping": {"mode": "MOCK", "source_ref": "other"}}}, {"metadata": {"local_mapping": True}}):
            with self.assertRaises(MappingScopeError):
                check_mock_environment(SimpleNamespace(**(valid | change)), "demo-monitor")
        with self.assertRaises(MappingScopeError): check_mock_environment(SimpleNamespace(**valid), "production")

    def test_expected_head_exact_integer(self):
        for value in (True, False, -1, 1.0, "1", None, 2147483647):
            with self.assertRaises(MappingInputError): validate_version(value)
        self.assertEqual(validate_version(0), 0)
        self.assertEqual(validate_version(1, minimum=1), 1)
        with self.assertRaises(MappingInputError): validate_version(0, minimum=1)

    def test_actor_and_reason_are_bounded_self_descriptions(self):
        _write_input(0, "初始草稿", "local user")
        for reason, actor in (("", "a"), ("x" * 513, "a"), ("r", "x" * 129), ("r", "<script>")):
            with self.assertRaises(MappingInputError): _write_input(0, reason, actor)

    def test_create_bool_head_rejected_before_database(self):
        with self.assertRaises(MappingInputError):
            create_bundle(environment_id="never-connect", source_ref="demo-monitor", cluster_uid="mock-a", monitor_cluster_id="monitor-a", content=package(), expected_head=True, reason="r", actor_label="a")

    def test_stale_head_rejected_before_write(self):
        with self.assertRaises(MappingConflict) as raised:
            _append(SimpleNamespace(head_version=3), package(), 2, "r", "a")
        self.assertEqual(raised.exception.current_head, 3)

    def test_revision_update_delete_guards_without_database(self):
        revision = MappingRevision()
        revision._state.adding = False
        with self.assertRaises(ValidationError): revision.save()
        with self.assertRaises(ValidationError): revision.delete()
        with self.assertRaises(ValidationError): MappingBundle().delete()

    def test_queryset_mutation_guards_without_database(self):
        for model in (MappingBundle, MappingRevision):
            for mutate in (lambda: model.objects.all().update(reason="x"), lambda: model.objects.all().delete(), lambda: model.objects.bulk_create([]), lambda: model.objects.bulk_update([], ["id"])):
                with self.assertRaises(ValidationError): mutate()
