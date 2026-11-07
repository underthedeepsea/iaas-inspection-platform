"""Bounded synthetic monitor adapter. No production transport or asset registry."""
from copy import deepcopy
from uuid import UUID, uuid4

from apps.api.http import APIRequestError, parse_positive_int
from . import mapping_services as store, mapping_simulation as simulation
from .models import Environment

# Explicit, immutable fixture identities; all alias the registered synthetic monitor.
ENDPOINTS = ("grid-monitor",) + tuple(f"demo-node-{i:03d}" for i in range(1, 100))
CURSORS = (None, "demo-page-2", "demo-page-3", "demo-page-4")
SCOPE_FIELDS = {"source_ref", "environment_id", "cluster_uid", "monitor_cluster_id"}
OPTIONS = {"fixture", "seed"}
COUNTERS = {spec[0]: (field, spec[1]) for field, spec in store.FIELD_SPECS.items()}


def invalid(message="Invalid synthetic request."):
    raise APIRequestError("INVALID_INPUT", message)


def integer(value, *, query, maximum=None, minimum=0):
    if value is None or not query and type(value) is not int:
        invalid("Integer seconds and integer options are required.")
    return parse_positive_int(value, maximum=maximum, minimum=minimum)


def admit(data, *, required, optional=(), query=False):
    if not required <= set(data) or set(data) - required - set(optional):
        invalid("Unexpected or missing fields.")
    if any(type(data.get(key)) is not str for key in SCOPE_FIELDS):
        invalid()
    try:
        environment_id = UUID(data["environment_id"])
    except (ValueError, TypeError, AttributeError):
        invalid()
    if any(data[key] != value for key, value in store.MOCK_INFERENCE_SCOPE.items()):
        raise store.MappingScopeError("Unregistered synthetic scope.")
    environment = Environment.objects.get(pk=environment_id)
    store.check_mock_environment(environment, data["source_ref"])
    fixture = data.get("fixture", "complete")
    if type(fixture) is not str or fixture not in simulation.FIXTURES:
        invalid("Unknown fixture.")
    seed = integer(data.get("seed", 0), query=query, maximum=9999)
    return {"request_id": str(uuid4()), "synthetic": True,
            "source_ref": store.SOURCE_REF, "fixture": fixture, "seed": seed,
            "scope": {"environment_id": str(environment.pk), **store.MOCK_INFERENCE_SCOPE},
            "cursor": None, "has_more": False, "errors": []}


def endpoints(value):
    if (type(value) is not list or not 1 <= len(value) <= 100
            or any(type(item) is not str or item not in ENDPOINTS for item in value)
            or len(set(value)) != len(value)):
        invalid("Use 1..100 unique registered synthetic endpoints.")
    return value


def metric(counter):
    field, unit = COUNTERS[counter]
    labels = (store.MOCK_FILESYSTEM_IDENTITY if counter.startswith("demo.filesystem.") else
              {"block_device": "nvme0n1"} if counter.startswith("demo.disk.") else
              {"engine_id": store.MOCK_INFERENCE_ENGINE["engine_id"]} if counter.startswith("demo.llm.") else {})
    return {"counter": counter, "standard_field": field, "unit": unit,
            "dstype": store.source_type(field), "labels": dict(sorted(labels.items()))}


def discover(data):
    out = admit(data, required=SCOPE_FIELDS, optional=OPTIONS | {"cursor"}, query=True)
    cursor = data.get("cursor")
    if cursor not in CURSORS:
        invalid("Unknown fixed fixture cursor.")
    page = CURSORS.index(cursor)
    out.update(endpoints=list(ENDPOINTS[page * 25:(page + 1) * 25]),
               metrics=[metric(counter) for counter in sorted(COUNTERS)],
               cursor=CURSORS[page + 1] if page < 3 else None, has_more=page < 3)
    return out


def describe(data):
    out = admit(data, required=SCOPE_FIELDS | {"endpoints"}, optional=OPTIONS)
    out["items"] = [{"endpoint": endpoint, "metrics": [metric(c) for c in sorted(COUNTERS)]}
                    for endpoint in endpoints(data["endpoints"])]
    return out


def data_response(data, *, batch=False, query=False):
    endpoint_key = "endpoints" if batch else "endpoint"
    out = admit(data, required=SCOPE_FIELDS | {endpoint_key, "counter", "start", "end", "step"}, optional=OPTIONS, query=query)
    selected = endpoints(data["endpoints"] if batch else [data["endpoint"]])
    counter = data["counter"]
    if type(counter) is not str or counter not in COUNTERS:
        invalid("One registered counter is required.")
    stamps = {key: integer(data[key], query=query) for key in ("start", "end", "step")}
    grid = simulation.window(**stamps)
    if counter in {definition[0] for definition in store.COUNTER_FIELDS.values()} and len(grid) + 1 > 61:
        invalid("Counter end boundary exceeds the existing 61 point limit.")
    out.update(counter=counter, unit=metric(counter)["unit"], dstype=metric(counter)["dstype"],
               window={"start": stamps["start"], "end": stamps["end"]}, step=stamps["step"])
    spec = {**out["scope"], "counter": counter, "fixture": out["fixture"], "seed": out["seed"], **stamps}
    if counter.startswith(("demo.disk.", "demo.filesystem.")):
        spec["resource_labels"] = metric(counter)["labels"]
    items = []
    for endpoint in selected:
        if endpoint == "demo-node-099":
            error = {"endpoint": endpoint, "code": "SYNTHETIC_FAILURE"}
            items.append({"endpoint": endpoint, "status": "failed", "series": [], "errors": [error]})
            out["errors"].append(error)
            continue
        raw = simulation.query(spec)
        rows = deepcopy(raw["series"])
        if endpoint == "demo-node-098":
            rows = []
        for row in rows:
            row["source_endpoint"] = row["endpoint"]
            row["endpoint"] = endpoint
            row["labels"] = dict(sorted(row["labels"].items()))
            row.setdefault("quality", "VALID" if row.get("points", row.get("events", [1])) else "MISSING")
        empty = not rows or all("points" in row and not row["points"] for row in rows)
        items.append({"endpoint": endpoint, "status": "empty" if empty else "success", "series": rows, "errors": []})
    if batch:
        out["items"] = items
    else:
        out.update(items[0])
    return out
