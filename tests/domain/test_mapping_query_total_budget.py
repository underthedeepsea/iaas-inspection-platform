"""S12 approved total-budget oracle, offline with controlled monotonic time."""
import argparse
import ast
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
if not settings.configured:
    settings.configure(INSTALLED_APPS=[], DATABASES={}, USE_TZ=True)
from apps.core import mapping_simulation as sim, mapping_loop as loop, mapping_query as query
from apps.core import mapping_inference as inference
from apps.core.mapping_services import MappingInputError, FIELD_SPECS, source_type, MOCK_INFERENCE_ENGINE, MOCK_FILESYSTEM_IDENTITY

ROWS = []
ACTIVE = None
REAL_QUERY = sim.query
REAL_NORMALIZE = sim.normalize
REAL_SUMMARY = inference.query_summary


class Clock:
    def __init__(self):
        self.value = 0.
        self.waits = []
    def __call__(self):
        return self.value
    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


def spec(fixture='complete'):
    return dict(source_ref='demo-monitor', environment_id='offline-env', cluster_uid='grid-cluster', monitor_cluster_id='grid-monitor', fixture=fixture, seed=1, start=1700000100, end=1700000400, step=60, counter='demo.host.cpu_busy', revision_id='offline-rev', content_hash='offline-hash')


def content(fields):
    result=[]
    for field in fields:
        labels = dict(MOCK_FILESYSTEM_IDENTITY) if field.startswith('filesystem.') else {'block_device':'nvme0n1'} if field.startswith('disk.') else {'engine_id':MOCK_INFERENCE_ENGINE['engine_id']} if field.startswith('llm.') else {}
        result.append(dict(standard_field=field, source_metric=FIELD_SPECS[field][0], source_type=source_type(field), source_unit=FIELD_SPECS[field][1], output_unit=FIELD_SPECS[field][2], conversion=FIELD_SPECS[field][3], labels=labels, window_seconds=300, step_seconds=60))
    return {'metrics':result}


def adapter_spec():
    return {k:v for k,v in spec().items() if k not in ('revision_id','content_hash')}


def profile(frame, event, arg):
    if ACTIVE is not None and event == 'call':
        if frame.f_code is REAL_QUERY.__code__:
            ACTIVE['adapter_calls'] += 1
            ACTIVE['deadlines'].append(frame.f_locals['deadline'])
        if frame.f_code is query.execute.__code__:
            ACTIVE['helper_calls'] += 1


class BudgetTests(unittest.TestCase):
    def setUp(self):
        global ACTIVE
        self.clock = Clock()
        ACTIVE = {'name':self._testMethodName, 'adapter_calls':0, 'helper_calls':0, 'deadlines':[]}
        self.patches=[patch.object(query,'monotonic',self.clock),patch.object(query,'sleep',self.clock.sleep)]
        for p in self.patches:p.start()
        sys.setprofile(profile)
    def tearDown(self):
        global ACTIVE
        sys.setprofile(None)
        ACTIVE.update(elapsed=self.clock.value, waits=self.clock.waits)
        ROWS.append(ACTIVE)
        for p in reversed(self.patches):p.stop()
        ACTIVE=None
    def fetch(self,fields=('host.cpu_busy_ratio',),fixture='complete'):
        return loop.fetch(spec(fixture),content(fields))
    def controlled(self,mode=None,delays=(),retry_after=None,late=0,per_request=False):
        fixtures={}; pending=list(delays)
        def call(s,**kw):
            fault=None
            if mode:
                key=s['counter'] if per_request else 'single'
                fault=fixtures.setdefault(key,sim.AttemptFixture(mode))
            if pending:self.clock.value+=pending.pop(0)
            try:
                raw=REAL_QUERY(s,**(kw|{'attempt_fixture':fault}))
            except sim.SimulatedRateLimited as exc:
                exc.retry_after=retry_after
                raise
            self.clock.value+=late
            return raw
        return patch.object(sim,'query',call)
    def test_normal_and_zero_keep_values(self):
        fields=['host.cpu_busy_ratio','gpu.memory_used_bytes','gpu.memory_total_bytes']
        self.assertEqual(self.fetch(fields)[1],{'host.cpu_busy_ratio':.41,'gpu.memory_used_bytes':8*1024**3,'gpu.memory_total_bytes':16*1024**3})
        self.assertEqual(self.fetch(fields,'zero')[1]['host.cpu_busy_ratio'],0.)
        self.assertEqual(ACTIVE['adapter_calls'],6);self.assertEqual(ACTIVE['helper_calls'],6)
    def test_default_faults_once_and_persistent(self):
        for mode in sorted(sim.AttemptFixture.MODES):
            before=ACTIVE['adapter_calls']
            with self.controlled(mode):
                if mode.endswith('always'):
                    with self.assertRaises(query.QueryAttemptsExhausted) as cm:self.fetch()
                    self.assertEqual(cm.exception.attempts,2)
                else:self.assertEqual(self.fetch()[1],{'host.cpu_busy_ratio':.41})
            self.assertEqual(ACTIVE['adapter_calls']-before,2)
        self.assertEqual(self.clock.waits,[1,1,1,1])
    def test_nonretryable_scope_and_unit_errors_once(self):
        with self.assertRaises(MappingInputError):loop.fetch(spec()|{'source_ref':'unknown'},content(['host.cpu_busy_ratio']))
        with self.assertRaises(MappingInputError):self.fetch(fixture='wrong-unit')
        self.assertEqual(ACTIVE['adapter_calls'],2);self.assertEqual(self.clock.waits,[])
    def test_capacity_overflow_regression(self):
        with self.assertRaises(MappingInputError):self.fetch(['gpu.memory_used_bytes','gpu.memory_total_bytes'],'capacity-overflow')
        self.assertEqual(ACTIVE['adapter_calls'],2)
    def test_attempt_deadline_inclusive_failure_and_two_max(self):
        with self.controlled(delays=[2,2]):
            with self.assertRaises(query.QueryAttemptsExhausted):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],2);self.assertEqual(ACTIVE['deadlines'],[2.,5.]);self.assertEqual(self.clock.value,5)
    def test_late_success_is_rejected(self):
        with self.controlled(late=2):
            with self.assertRaises(query.QueryAttemptsExhausted):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],2)
    def test_late_over_batch_is_visible(self):
        with self.controlled(late=5.1):
            with self.assertRaises(query.QueryBudgetExceeded):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],1);self.assertEqual(self.clock.waits,[])
    def test_retry_after_consumes_shared_budget(self):
        with self.controlled('429-once',retry_after=3):
            self.assertEqual(self.fetch()[1]['host.cpu_busy_ratio'],.41)
        self.assertEqual(self.clock.value,3);self.assertEqual(ACTIVE['deadlines'],[2,5]);self.assertEqual(self.clock.waits,[3])
    def test_retry_after_cannot_wait_to_or_past_deadline(self):
        for delay in [5,6,1e99]:
            with self.controlled('429-once',retry_after=delay):
                with self.assertRaises(query.QueryBudgetExceeded):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],3);self.assertEqual(self.clock.waits,[])
    def test_invalid_retry_after(self):
        for delay in [-1,float('nan'),float('inf'),float('-inf'),'1',True,{},[],10**1000]:
            with self.controlled('429-once',retry_after=delay):
                with self.assertRaises(MappingInputError):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],9);self.assertEqual(self.clock.waits,[])
    def test_zero_retry_after_is_bounded(self):
        with self.controlled('429-always',retry_after=0):
            with self.assertRaises(query.QueryAttemptsExhausted):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],2);self.assertEqual(self.clock.waits,[0])
    def test_second_metric_uses_consumed_time_and_capped_deadline(self):
        calls=0
        def normalize(raw,s,m):
            nonlocal calls
            result=REAL_NORMALIZE(raw,s,m);calls+=1
            if calls==1:self.clock.value=9
            return result
        with patch.object(sim,'normalize',normalize):
            self.fetch(['host.cpu_busy_ratio','gpu.temperature_celsius'])
        self.assertEqual(ACTIVE['deadlines'],[2,10]);self.assertEqual(self.clock.value,9)
    def test_between_metrics_elapsed_blocks_next_entry(self):
        def normalize(raw,s,m):
            result=REAL_NORMALIZE(raw,s,m);self.clock.value=10;return result
        with patch.object(sim,'normalize',normalize):
            with self.assertRaises(query.QueryBudgetExceeded):self.fetch(['host.cpu_busy_ratio','gpu.temperature_celsius'])
        self.assertEqual(ACTIVE['adapter_calls'],1)
    def test_final_normalization_and_capacity_time_included(self):
        def normalize(raw,s,m):
            result=REAL_NORMALIZE(raw,s,m);self.clock.value=5.001;return result
        with patch.object(sim,'normalize',normalize):
            with self.assertRaises(query.QueryBudgetExceeded):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],1)
    def test_custom_wait_elapsed_still_bounded(self):
        def wait(a,e):self.clock.value=5
        with self.assertRaises(query.QueryBudgetExceeded):query.execute(adapter_spec(),clock=self.clock,retry_wait=wait,attempt_fixture=sim.AttemptFixture('timeout-once'))
        self.assertEqual(ACTIVE['adapter_calls'],1)
    def test_call_limit_exact_and_reentry_blocked(self):
        b=query.QueryBudget(1,clock=self.clock)
        query.execute(adapter_spec(),budget=b);query.execute(adapter_spec(),budget=b)
        with self.assertRaises(query.QueryBudgetExceeded):query.execute(adapter_spec(),budget=b)
        self.assertEqual(b.calls,2);self.assertEqual(ACTIVE['adapter_calls'],2)
    def test_37_real_metrics_74_calls_185_seconds_exact(self):
        fields=list(FIELD_SPECS);self.assertEqual(len(fields),37)
        def normalize(raw,s,m):
            result=REAL_NORMALIZE(raw,s,m)
            if m['standard_field']==fields[-1]:self.clock.value=185
            return result
        with self.controlled('429-once',per_request=True),patch.object(sim,'normalize',normalize):
            result=self.fetch(fields)
        self.assertEqual(len(result[1]),37);self.assertEqual(ACTIVE['helper_calls'],37)
        self.assertEqual(ACTIVE['adapter_calls'],74);self.assertEqual(self.clock.value,185)
        self.assertEqual(sum(self.clock.waits),37);self.assertEqual(max(ACTIVE['deadlines']),39)
    def test_37_completion_over185_fails(self):
        fields=list(FIELD_SPECS)
        def normalize(raw,s,m):
            result=REAL_NORMALIZE(raw,s,m)
            if m['standard_field']==fields[-1]:self.clock.value=185.001
            return result
        with self.controlled('429-once',per_request=True),patch.object(sim,'normalize',normalize):
            with self.assertRaises(query.QueryBudgetExceeded):self.fetch(fields)
        self.assertEqual(ACTIVE['adapter_calls'],74)
    def test_37_nearly_full_attempts_and_all_backoff(self):
        fixtures={}
        def slow(s,**kw):
            fault=fixtures.setdefault(s['counter'],sim.AttemptFixture('timeout-once'))
            try:
                raw=REAL_QUERY(s,**(kw|{'attempt_fixture':fault}))
            except sim.SimulatedTimeout:
                self.clock.value+=2
                raise
            self.clock.value+=1.999
            return raw
        with patch.object(sim,'query',slow):
            result=self.fetch(list(FIELD_SPECS))
        self.assertEqual(len(result[1]),37);self.assertEqual(ACTIVE['adapter_calls'],74)
        self.assertAlmostEqual(self.clock.value,184.963,places=6)
        self.assertEqual(sum(self.clock.waits),37)
    def test_sleeper_overshoot_blocks_retry(self):
        def oversleep(seconds):self.clock.value+=6
        with patch.object(query,'sleep',oversleep),self.controlled('timeout-once'):
            with self.assertRaises(query.QueryBudgetExceeded):self.fetch()
        self.assertEqual(ACTIVE['adapter_calls'],1)
    def test_empty_and_invalid_planned_count(self):
        self.assertEqual(self.fetch([]),([],{}))
        for n in [-1,True,1.,'1',None]:
            with self.assertRaises(MappingInputError):query.QueryBudget(n)
        self.assertEqual(ACTIVE['adapter_calls'],0)
    def test_llm_summary_checks_own_completion_deadline(self):
        def summary(*a):
            raw=REAL_SUMMARY(*a);self.clock.value=2;return raw
        s=adapter_spec()|{'counter':'demo.llm.ttft.avg_ms'}
        with patch.object(inference,'query_summary',summary):
            with self.assertRaises(sim.SimulatedTimeout):REAL_QUERY(s,deadline=2,clock=self.clock)
        self.assertEqual(ACTIVE['adapter_calls'],1)
    def test_validate_and_collect_share_default_fetch_callsite(self):
        tree=ast.parse(Path(loop.__file__).read_text())
        for name in ['validate','collect']:
            fun=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            calls=[n for n in ast.walk(fun) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='fetch']
            self.assertEqual(len(calls),1);self.assertEqual(calls[0].keywords,[])
        self.fetch();self.assertEqual(ACTIVE['helper_calls'],1);self.assertEqual(ACTIVE['adapter_calls'],1)
    def test_explicit_executor_contract_preserved(self):
        def executor(s):return REAL_QUERY(s)
        self.assertEqual(loop.fetch(spec(),content(['host.cpu_busy_ratio']),query_executor=executor)[1]['host.cpu_busy_ratio'],.41)
        self.assertEqual(ACTIVE['adapter_calls'],1);self.assertEqual(ACTIVE['helper_calls'],0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BudgetTests))
    output={'scope':'S12_APPROVED_DEFAULT_TOTAL_BUDGET','case_count':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'adapter_calls':sum(r['adapter_calls'] for r in ROWS),'cases':ROWS,'exit_code':int(not result.wasSuccessful()),'requested_model':'gpt-6.1-sol','requested_effort':'high','runtime_model':None,'runtime_effort':None,'tokens':None,'cost':None}
    Path(args.output).write_text(json.dumps(output,indent=2,allow_nan=False)+'\n');return output['exit_code']
if __name__=='__main__':raise SystemExit(main())
