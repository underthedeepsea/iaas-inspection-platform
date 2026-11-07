"""Offline S12 defined-scope oracle. No DB, HTTP, model or real sleep."""
import json, sys, argparse
from pathlib import Path
from functools import partial
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from django.conf import settings
if not settings.configured:
    settings.configure(INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth', 'apps.core'], DATABASES={}, USE_TZ=True)
import django
django.setup()
from apps.core import mapping_simulation as sim, mapping_loop as loop, mapping_query as query
from apps.core.mapping_services import MappingInputError, FIELD_SPECS

ROWS = []
ASSERTIONS = 0

class Clock:
    def __init__(self, script=()):
        self.value = 0.0
        self.script = list(script)
        self.reads = []
        self.waits = []
    def __call__(self):
        if self.script:
            self.value = self.script.pop(0)
        self.reads.append(self.value)
        return self.value
    def wait(self, attempt, error):
        # Explicit test scheduler, not a product backoff default.
        self.waits.append({'attempt': attempt, 'error': type(error).__name__, 'test_delay': 0.25})
        self.value += 0.25


def eq(actual, expected):
    global ASSERTIONS
    ASSERTIONS += 1
    assert actual == expected, (actual, expected)


def raises(kind, action):
    global ASSERTIONS
    ASSERTIONS += 1
    try:
        action()
    except kind as error:
        return error
    raise AssertionError('Expected ' + kind.__name__)


def spec(fixture='complete'):
    return dict(source_ref='demo-monitor', environment_id='offline-env', cluster_uid='offline-cluster', monitor_cluster_id='offline-host', fixture=fixture, seed=1, start=1700000100, end=1700000400, step=60, counter='demo.host.cpu_busy')


def content(fields):
    return {'metrics': [dict(standard_field=field, source_metric=FIELD_SPECS[field][0], source_type='GAUGE', source_unit=FIELD_SPECS[field][1], output_unit=FIELD_SPECS[field][2], conversion=FIELD_SPECS[field][3], labels={}, window_seconds=300, step_seconds=60) for field in fields]}


def case(name, action, expected_calls, clock=None):
    row = {'name': name, 'adapter_calls': 0, 'assertions': 0}
    before = ASSERTIONS
    def profile(frame, event, arg):
        if event == 'call' and frame.f_code is sim.query.__code__:
            row['adapter_calls'] += 1
    sys.setprofile(profile)
    try:
        action()
        eq(row['adapter_calls'], expected_calls)
        row['status'] = 'PASS'
    except Exception as error:
        row['status'] = 'FAIL'
        row['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        sys.setprofile(None)
        row['assertions'] = ASSERTIONS - before
        if clock is not None:
            row['clock_reads'] = clock.reads
            row['retry_waits'] = clock.waits
        ROWS.append(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    for fixture, cpu in [('complete', 0.41), ('zero', 0.0)]:
        clock = Clock()
        executor = partial(query.execute, retry_wait=clock.wait, clock=clock)
        def positive(fixture=fixture, cpu=cpu, executor=executor):
            bound = spec(fixture)
            fields = ['host.cpu_busy_ratio', 'gpu.memory_used_bytes', 'gpu.memory_total_bytes']
            actual = loop.fetch(bound, content(fields), query_executor=executor)
            old = loop.fetch(bound, content(fields))
            eq(actual, old)
            eq(actual[1]['host.cpu_busy_ratio'], cpu)
            eq(actual[1]['gpu.memory_total_bytes'], 16 * 1024**3)
            eq(actual[1]['gpu.memory_used_bytes'], 0 if fixture == 'zero' else 8 * 1024**3)
        case('fetch_' + fixture + '_preserves_capacity_pair', positive, 6, clock)
    clock = Clock()
    executor = partial(query.execute, retry_wait=clock.wait, clock=clock)
    case('raw_capacity_overflow_still_rejected', lambda: raises(MappingInputError, lambda: loop.fetch(spec('capacity-overflow'), content(['gpu.memory_used_bytes', 'gpu.memory_total_bytes']), query_executor=executor)), 2, clock)
    for mode in sorted(sim.AttemptFixture.MODES):
        clock = Clock()
        fault = sim.AttemptFixture(mode)
        def fault_case(mode=mode, clock=clock, fault=fault):
            action = lambda: query.execute(spec(), retry_wait=clock.wait, clock=clock, attempt_fixture=fault)
            if mode.endswith('-always'):
                error = raises(query.QueryAttemptsExhausted, action)
                eq(error.attempts, 2)
                eq(error.cause_code, 'TIMEOUT' if mode.startswith('timeout') else '429')
            else:
                eq(action()['counter'], 'demo.host.cpu_busy')
            eq(fault.calls, 2)
            eq(len(clock.waits), 1)
        case(mode, fault_case, 2, clock)
    clock = Clock()
    case('nonretry_validation_error_once', lambda: raises(MappingInputError, lambda: query.execute(spec() | {'source_ref': 'unknown'}, retry_wait=clock.wait, clock=clock)), 1, clock)
    clock = Clock()
    executor = partial(query.execute, retry_wait=clock.wait, clock=clock)
    case('normalization_error_not_retried', lambda: raises(MappingInputError, lambda: loop.fetch(spec('wrong-unit'), content(['host.cpu_busy_ratio']), query_executor=executor)), 1, clock)
    for at in [1.999, 2.0, 2.001]:
        clock = Clock([0.0, 0.0, at])
        def boundary(at=at, clock=clock):
            action = lambda: sim.query(spec(), deadline=2.0, clock=clock)
            if at < 2:
                eq(action()['counter'], 'demo.host.cpu_busy')
            else:
                raises(sim.SimulatedTimeout, action)
        case('deadline_' + str(at), boundary, 1, clock)
    clock = Clock([0, 0, 0, 2, 2.25, 2.25, 2.25, 4.25])
    def exhausted_deadlines():
        error = raises(query.QueryAttemptsExhausted, lambda: query.execute(spec(), retry_wait=clock.wait, clock=clock))
        eq(error.cause_code, 'TIMEOUT')
        eq(error.attempts, 2)
        eq(len(clock.waits), 1)
    case('two_real_adapter_deadline_failures', exhausted_deadlines, 2, clock)
    clock = Clock()
    fault = sim.AttemptFixture('429-once')
    executor = partial(query.execute, retry_wait=clock.wait, clock=clock, attempt_fixture=fault)
    case('fetch_transient_429_real_normalization', lambda: eq(loop.fetch(spec(), content(['host.cpu_busy_ratio']), query_executor=executor)[1], {'host.cpu_busy_ratio': 0.41}), 2, clock)
    clock = Clock()
    case('no_implicit_scheduler_default', lambda: raises(MappingInputError, lambda: query.execute(spec(), retry_wait=None, clock=clock)), 0, clock)
    result = {'scope': 'DEFINED_RETRY_SCOPE_ONLY', 'overall_s12': 'NOT_SIGNED', 'cases': ROWS, 'case_count': len(ROWS), 'assertions': ASSERTIONS, 'adapter_calls': sum(row['adapter_calls'] for row in ROWS), 'exit_code': int(any(row['status'] != 'PASS' for row in ROWS)), 'test_scheduler_policy': 'Explicit fake 0.25s per retry; no product default, no real sleep', 'production_default_engine_enabled': False}
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return result['exit_code']

if __name__ == '__main__':
    raise SystemExit(main())
