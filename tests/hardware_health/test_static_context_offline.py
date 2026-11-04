"""R1 regression: event ownership survives replacement observations, without I/O."""
from copy import deepcopy
from datetime import timedelta
import unittest
from apps.hardware_health.evaluator import evaluate
from apps.hardware_health.host_policy import static_event_recovered
from tests.hardware_health.test_host_policy_offline import BASE, row, sequence


class StaticEventContextTests(unittest.TestCase):
    def confirmed(self):
        rows=sequence([row(i,.9,.1) for i in range(3)])
        issues=[deepcopy(issue) for issue in rows[-1].evaluation['issues'] if issue['key'] in ('host/cpu_static','host/memory_static')]
        return rows,issues

    def test_foreign_points_do_not_recover_and_original_context_needs_five_new_points(self):
        for field in ('source','config_id'):
            rows,issues=self.confirmed()
            frozen={issue['event_id']:deepcopy(issue['frozen_context']) for issue in issues}
            for i in range(3,8):
                sample=row(i,.1,.8);sample.payload[field]='replacement'
                sample.evaluation=evaluate(sample,rows);rows.append(sample)
            for issue in issues:
                result=rows[-1].evaluation
                event=result['host_rule_events'][issue['event_id']]
                current_issue=next(x for x in result['issues'] if x['key']==issue['key'])
                self.assertEqual(event['status'],'ACTIVE')
                self.assertEqual(event['frozen_context'],frozen[issue['event_id']])
                self.assertEqual(current_issue['frozen_context'],issue['frozen_context'])
                self.assertNotEqual(current_issue['context'],issue['frozen_context'])
                self.assertEqual(result['host_rule_states'][issue['key']]['warning_recovery_points'],0)
                self.assertFalse(static_event_recovered(result,issue,BASE+timedelta(seconds=121)))
            for i in range(8,13):
                sample=row(i,.1,.8);sample.evaluation=evaluate(sample,rows);rows.append(sample)
                for issue in issues:
                    event=sample.evaluation['host_rule_events'][issue['event_id']]
                    self.assertEqual(event['status'],'ACTIVE' if i<12 else 'RECOVERED')
            for issue in issues:
                self.assertTrue(static_event_recovered(rows[-1].evaluation,issue,BASE+timedelta(seconds=121)))

    def test_missing_old_context_is_not_filled_from_current_state(self):
        rows,issues=self.confirmed()
        for event in rows[-1].evaluation['host_rule_events'].values():event.pop('frozen_context')
        for i in range(3,8):
            sample=row(i,.1,.8);sample.evaluation=evaluate(sample,rows);rows.append(sample)
        for issue in issues:
            event=rows[-1].evaluation['host_rule_events'][issue['event_id']]
            self.assertEqual(event['status'],'ACTIVE')
            self.assertNotIn('frozen_context',event)
            self.assertFalse(static_event_recovered(rows[-1].evaluation,issue,BASE+timedelta(seconds=121)))

    def test_helper_requires_original_issue_and_recovery_context(self):
        rows,issues=self.confirmed()
        for i in range(3,8):
            sample=row(i,.1,.8);sample.evaluation=evaluate(sample,rows);rows.append(sample)
        final=rows[-1].evaluation
        for issue in issues:
            self.assertTrue(static_event_recovered(final,issue,BASE+timedelta(seconds=121)))
            for target in ('event','recovery','issue','state'):
                changed=deepcopy(final);old_issue=deepcopy(issue);event=changed['host_rule_events'][issue['event_id']]
                if target=='event':event.pop('frozen_context')
                elif target=='recovery':event['recovery_context']['source']='replacement'
                elif target=='issue':old_issue.pop('frozen_context')
                else:changed['host_rule_states'][issue['key']]['context']['source']='replacement'
                self.assertFalse(static_event_recovered(changed,old_issue,BASE+timedelta(seconds=121)))

    def test_invalid_point_interrupts_same_context_recovery(self):
        rows,issues=self.confirmed()
        for i in range(3,7):
            sample=row(i,.1,.8);sample.evaluation=evaluate(sample,rows);rows.append(sample)
        invalid=row(7,.1,.8)
        for point in invalid.payload['metrics']['host']['values'].values():point.update(quality='MISSING',value=None)
        invalid.evaluation=evaluate(invalid,rows);rows.append(invalid)
        sample=row(8,.1,.8);sample.evaluation=evaluate(sample,rows);rows.append(sample)
        for issue in issues:
            self.assertEqual(sample.evaluation['host_rule_events'][issue['event_id']]['status'],'ACTIVE')
            self.assertEqual(sample.evaluation['host_rule_states'][issue['key']]['warning_recovery_points'],1)
            self.assertFalse(static_event_recovered(sample.evaluation,issue,BASE+timedelta(seconds=121)))
