"""Bounded LOCAL/MOCK draft persistence; no activation, ingestion or algorithms.

This storage envelope is NOT a hardware/inference snapshot schema or a validation
receipt. A bounded CPU/GPU gauge, paired memory-capacity and Xid event catalogue is accepted;
Full37-field completeness is not implemented.
Submitting metrics replaces the entire draft collection; there is no merge.
"""
import hashlib
import json
import re

from django.db import IntegrityError, transaction

from .models import Environment, MappingBundle, MappingRevision

SOURCE_REF = "demo-monitor"
SCHEMA_VERSION = "mapping-draft-v1"
# Dedicated metadata marker; DEV/TEST/PROD_SIM alone never authorizes writes.
MOCK_METADATA = {"mode": "MOCK", "source_ref": SOURCE_REF}
# A static synthetic source registration; environment remains server-resolved.
MOCK_INFERENCE_SCOPE = {"source_ref": SOURCE_REF, "cluster_uid": "grid-cluster", "monitor_cluster_id": "grid-monitor"}
MOCK_INFERENCE_ENGINE = {"engine_id": "demo-llm-control", "engine_type": "vllm", "model_name": "Qwen/Qwen3-32B"}
INFERENCE_METRICS = {
    "ttft": ("avg_ms", "p90_ms", "p95_ms", "p99_ms", "e2e_ratio"),
    "tpot": ("avg_ms", "p90_ms", "p95_ms", "p99_ms"),
    "e2e": ("avg_ms", "p90_ms", "p95_ms", "p99_ms"),
    "traffic": ("qps", "qpm"), "throughput": ("generation_tps", "prompt_tps"),
    "cache": ("kv_cache_hit_rate",), "requests": ("running", "waiting"),
}
def _inference_unit(group, name):
    if name.endswith("_ms"): return "ms"
    if name in {"e2e_ratio", "kv_cache_hit_rate"}: return "ratio"
    if group == "throughput": return "tokens_per_second"
    return {"qps": "requests_per_second", "qpm": "requests_per_minute"}.get(name, "count")
INFERENCE_FIELD_SPECS = {
    f"llm.{group}.{name}": (f"demo.llm.{group}.{name}", _inference_unit(group, name), _inference_unit(group, name), "REQUEST_WINDOW")
    for group, names in INFERENCE_METRICS.items() for name in names
}

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
FIELD_SPECS = {
    "filesystem.available_bytes": ("demo.filesystem.available_bytes", "bytes", "bytes", "IDENTITY"),
    "filesystem.size_bytes": ("demo.filesystem.size_bytes", "bytes", "bytes", "IDENTITY"),
    "disk.read_bytes_per_second": ("demo.disk.read_bytes_per_second", "bytes_per_second", "bytes_per_second", "IDENTITY"),
    "disk.write_bytes_per_second": ("demo.disk.write_bytes_per_second", "bytes_per_second", "bytes_per_second", "IDENTITY"),
    "disk.io_busy_ratio": ("demo.disk.io_busy_ratio", "ratio", "ratio", "IDENTITY"),
    "host.cpu_busy_ratio": ("demo.host.cpu_busy", "percent", "ratio", "DIVIDE_100"),
    "gpu.temperature_celsius": ("demo.gpu.temperature", "celsius", "celsius", "IDENTITY"),
    "disk.read_latency_avg_ms": ("demo.disk.read_latency_avg_seconds", "seconds", "ms", "MULTIPLY_1000"),
    "disk.write_latency_avg_ms": ("demo.disk.write_latency_avg_seconds", "seconds", "ms", "MULTIPLY_1000"),
    "gpu.xid_events": ("demo.gpu.xid_events", "events", "events", "EVENT_LIST"),
    'gpu.utilization_ratio': ('demo.gpu.utilization', 'percent', 'ratio', 'DIVIDE_100'),
    'gpu.memory_used_bytes': ('demo.gpu.memory_used', 'bytes', 'bytes', 'IDENTITY'),
    'gpu.memory_total_bytes': ('demo.gpu.memory_total', 'bytes', 'bytes', 'IDENTITY'),
    'host.memory_available_bytes': ('demo.host.memory_available', 'bytes', 'bytes', 'IDENTITY'),
    'host.memory_total_bytes': ('demo.host.memory_total', 'bytes', 'bytes', 'IDENTITY'),

}


COUNTER_FIELDS = {
    "gpu.ecc_sbe_delta": ("demo.gpu.ecc_sbe", "SINGLE_BIT"),
    "gpu.ecc_dbe_delta": ("demo.gpu.ecc_dbe", "DOUBLE_BIT"),
}
for _field, (_source, _bits) in COUNTER_FIELDS.items():
    FIELD_SPECS[_field] = (_source, "count", "count", "COUNTER_DELTA")


HARDWARE_FIELD_SPECS = dict(FIELD_SPECS)
FIELD_SPECS.update(INFERENCE_FIELD_SPECS)

MOCK_FILESYSTEM_IDENTITY = {"filesystem":"ext4", "mountpoint":"/", "block_device":"dev0"}

CAPACITY_PAIRS = (("filesystem.available_bytes", "filesystem.size_bytes"), ("gpu.memory_used_bytes", "gpu.memory_total_bytes"), ("host.memory_available_bytes", "host.memory_total_bytes"))

def source_type(field):
    return "REQUEST_WINDOW" if field in INFERENCE_FIELD_SPECS else "COUNTER" if field in COUNTER_FIELDS else "EVENTS" if field == "gpu.xid_events" else "GAUGE"


class MappingInputError(ValueError):
    def __init__(self, message, *, path=None):
        self.path = path
        super().__init__(message)


class MappingScopeError(MappingInputError):
    pass


class MappingConflict(MappingInputError):
    def __init__(self, current_head=None):
        self.current_head = current_head
        super().__init__("Mapping head or scope uniqueness conflict; reread before retrying.")


def _token(value, name):
    if type(value) is not str or not TOKEN.fullmatch(value):
        raise MappingInputError(f"Invalid {name}.")
    return value


def _text(value, name, limit):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise MappingInputError(f"Invalid {name}.")
    if any(ord(char) < 32 for char in value) or any(part in value.lower() for part in ("://", "<", ">", "javascript:")):
        raise MappingInputError(f"Unsafe {name}.")
    return value


def _keys(value, expected, name, *, path=None):
    if type(value) is not dict or set(value) != set(expected):
        raise MappingInputError(f"Unexpected or missing {name} fields.", path=path)


def validate_version(value, *, minimum=0):
    if type(value) is not int or not minimum <= value <= 2147483646:
        raise MappingInputError("Version must be an exact bounded integer, not bool.")
    return value


def check_mock_environment(environment, source_ref):
    if type(source_ref) is not str or source_ref != SOURCE_REF:
        raise MappingScopeError("Only demo-monitor is registered.")
    if (environment.environment_type not in Environment.EnvironmentType.values
            or environment.is_active is not True or type(environment.metadata) is not dict
            or environment.metadata.get("local_mapping") != MOCK_METADATA):
        raise MappingScopeError("An active environment with explicit local_mapping MOCK metadata is required.")


def validate_content(content, *, cluster_uid, monitor_cluster_id):
    """Return a detached full package, canonical JSON and SHA-256; never evaluate strings."""
    _token(cluster_uid, "cluster_uid")
    _token(monitor_cluster_id, "monitor_cluster_id")
    _keys(content, ("schema_version", "cluster", "metrics"), "package", path="content")
    if content["schema_version"] != SCHEMA_VERSION:
        raise MappingInputError("Unsupported storage envelope version.")
    cluster = content["cluster"]
    _keys(cluster, ("cluster_uid", "monitor_cluster_id", "display_name"), "cluster", path="content.cluster")
    if cluster["cluster_uid"] != cluster_uid or cluster["monitor_cluster_id"] != monitor_cluster_id:
        raise MappingScopeError("Cluster identity cannot change or cross scope.")
    _text(cluster["display_name"], "display_name", 128)
    metrics = content["metrics"]
    if type(metrics) is not list or not 1 <= len(metrics) <= 37:
        raise MappingInputError("Submit the entire bounded metric collection (1..37).")
    seen = set()
    for index, metric in enumerate(metrics):
        path = f"content.metrics[{index}]"
        _keys(metric, ("standard_field", "source_metric", "source_type", "source_unit", "output_unit", "conversion", "labels", "window_seconds", "step_seconds"), "metric", path=path)
        field = _token(metric["standard_field"], "standard_field")
        if field not in FIELD_SPECS or field in seen:
            raise MappingInputError("Unsupported or duplicate standard field.")
        seen.add(field)
        actual = tuple(metric[key] for key in ("source_metric", "source_unit", "output_unit", "conversion"))
        if actual != FIELD_SPECS[field] or metric["source_type"] != source_type(field):
            raise MappingInputError("Only explicit whitelisted source/unit/conversion bindings are stored.", path=path + "." + next(key for key, value in (("source_metric", FIELD_SPECS[field][0]), ("source_unit", FIELD_SPECS[field][1]), ("output_unit", FIELD_SPECS[field][2]), ("conversion", FIELD_SPECS[field][3]), ("source_type", source_type(field))) if metric[key] != value))
        labels = metric["labels"]
        if type(labels) is not dict or len(labels) > 16:
            raise MappingInputError("Labels must be a bounded structured object.", path=path + ".labels")
        if field in INFERENCE_FIELD_SPECS:
            if ({"source_ref": SOURCE_REF, "cluster_uid": cluster_uid, "monitor_cluster_id": monitor_cluster_id} != MOCK_INFERENCE_SCOPE
                    or labels != {"engine_id": MOCK_INFERENCE_ENGINE["engine_id"]}):
                raise MappingScopeError("Inference mapping requires the static MOCK cluster/monitor/engine binding.")
        if field in COUNTER_FIELDS and labels != {}:
            raise MappingInputError("ECC mapping requires the registered cluster series identity.", path=path + ".labels")
        if field.startswith("filesystem.") and labels != MOCK_FILESYSTEM_IDENTITY:
            raise MappingInputError("Filesystem requires the registered mock root identity.", path=path + ".labels")
        for key, value in labels.items():
            if field.startswith("filesystem.") and key == "mountpoint":continue
            _token(key, "label name")
            _token(value, "label value")
        if field.startswith("disk.") and labels != {"block_device": "nvme0n1"}:
            raise MappingInputError("Disk mapping requires registered mock block_device nvme0n1.")
        window, step = metric["window_seconds"], metric["step_seconds"]
        if type(window) is not int or type(step) is not int or not 1 <= step <= window <= 3600:
            raise MappingInputError("Window/step must be bounded positive integer seconds.", path=path + (".window_seconds" if type(window) is not int or not 1 <= window <= 3600 else ".step_seconds"))
    for left, right in CAPACITY_PAIRS:
        if (left in seen) != (right in seen):
            raise MappingInputError("Capacity mapping requires both value and total fields.")
    try:
        canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        encoded = canonical.encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise MappingInputError("Package must be finite JSON with valid Unicode.") from exc
    if len(encoded) > 65536:
        raise MappingInputError("Package exceeds 64 KiB.")
    return json.loads(canonical), canonical, hashlib.sha256(encoded).hexdigest()


def _environment(environment_id, source_ref):
    try:
        environment = Environment.objects.select_for_update().get(pk=environment_id)
    except Environment.DoesNotExist as exc:
        raise MappingScopeError("Unknown mock environment.") from exc
    check_mock_environment(environment, source_ref)
    return environment


def _bundle(bundle_id, environment_id, source_ref, cluster_uid):
    _token(cluster_uid, "cluster_uid")
    try:
        return MappingBundle.objects.select_for_update().get(pk=bundle_id, environment_id=environment_id, source_ref=source_ref, cluster_uid=cluster_uid)
    except MappingBundle.DoesNotExist as exc:
        raise MappingScopeError("Bundle does not belong to the requested scope.") from exc


def _append(bundle, content, expected_head, reason, actor_label, rollback_from=None):
    if bundle.head_version != expected_head:
        raise MappingConflict(bundle.head_version)
    _, canonical, digest = validate_content(content, cluster_uid=bundle.cluster_uid, monitor_cluster_id=bundle.monitor_cluster_id)
    revision = MappingRevision.objects.create(
        bundle=bundle, version=expected_head + 1, schema_version=SCHEMA_VERSION,
        canonical_json=canonical, content_hash=digest,
        parent_revision_id=bundle.head_revision_id, rollback_from=rollback_from,
        reason=reason, actor_label=actor_label,
    )
    bundle.head_revision = revision
    bundle.head_version = revision.version
    bundle.save(update_fields=["head_revision", "head_version"])
    return revision


def _write_input(expected_head, reason, actor_label):
    validate_version(expected_head)
    _text(reason, "reason", 512)
    _text(actor_label, "actor_label", 128)


def create_bundle(*, environment_id, source_ref, cluster_uid, monitor_cluster_id, content, expected_head, reason, actor_label):
    _write_input(expected_head, reason, actor_label)
    if expected_head != 0:
        raise MappingConflict(0)
    validate_content(content, cluster_uid=cluster_uid, monitor_cluster_id=monitor_cluster_id)
    try:
        with transaction.atomic():
            environment = _environment(environment_id, source_ref)
            bundle = MappingBundle.objects.create(environment=environment, source_ref=source_ref, cluster_uid=cluster_uid, monitor_cluster_id=monitor_cluster_id)
            _append(bundle, content, 0, reason, actor_label)
            return bundle
    except IntegrityError as exc:
        raise MappingConflict() from exc


def append_revision(*, bundle_id, environment_id, source_ref, cluster_uid, content, expected_head, reason, actor_label):
    _write_input(expected_head, reason, actor_label)
    with transaction.atomic():
        _environment(environment_id, source_ref)
        bundle = _bundle(bundle_id, environment_id, source_ref, cluster_uid)
        return _append(bundle, content, expected_head, reason, actor_label)


def rollback_revision(*, bundle_id, environment_id, source_ref, cluster_uid, target_version, expected_head, reason, actor_label):
    _write_input(expected_head, reason, actor_label)
    validate_version(target_version, minimum=1)
    with transaction.atomic():
        _environment(environment_id, source_ref)
        bundle = _bundle(bundle_id, environment_id, source_ref, cluster_uid)
        if bundle.head_version != expected_head:
            raise MappingConflict(bundle.head_version)
        try:
            target = bundle.revisions.get(version=target_version)
        except MappingRevision.DoesNotExist as exc:
            raise MappingInputError("Rollback target is not in this bundle.") from exc
        if hashlib.sha256(target.canonical_json.encode("utf-8")).hexdigest() != target.content_hash:
            raise MappingInputError("Stored revision hash mismatch.")
        return _append(bundle, json.loads(target.canonical_json), expected_head, reason, actor_label, rollback_from=target)


def read_bundle(*, bundle_id, environment_id, source_ref, cluster_uid):
    # Lock consistently with writers to read a coherent head + full package.
    with transaction.atomic():
        _environment(environment_id, source_ref)
        bundle = _bundle(bundle_id, environment_id, source_ref, cluster_uid)
        revision = bundle.revisions.get(pk=bundle.head_revision_id, version=bundle.head_version)
        content, canonical, digest = validate_content(json.loads(revision.canonical_json), cluster_uid=bundle.cluster_uid, monitor_cluster_id=bundle.monitor_cluster_id)
        if canonical != revision.canonical_json or digest != revision.content_hash:
            raise MappingInputError("Stored revision integrity mismatch.")
        return {"active_version": bundle.active_revision.version if bundle.active_revision_id else 0, "active_revision_id": str(bundle.active_revision_id) if bundle.active_revision_id else None, "bundle_id": str(bundle.pk), "environment_id": str(bundle.environment_id), "source_ref": bundle.source_ref, "cluster_uid": bundle.cluster_uid, "enabled": bundle.enabled, "head_version": bundle.head_version, "revision_id": str(revision.pk), "content": content, "content_hash": digest, "status": "DRAFT", "validation": "NOT_RUN"}
