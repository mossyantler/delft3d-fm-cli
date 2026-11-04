"""Portable AST scope gate: no product import, OS probe, process or native run."""
import unittest
from research.workflows.verification.verify_rr_f152_native_ownership import profile_switch

SOURCE = '''
def execute_native(run, command, cwd, environment):
    record = run.record
    trace_exchange = record.get("profile_name") == "coupling" and record.get("coupling", {}).get("profile", {}).get("name") in {"fm_rtc", "rr_f152"}
    run.job = OwnedJob(trace_members=True) if trace_exchange else OwnedJob()
    run.process = run.job.launch(command, cwd=cwd, env=environment)
    result = capture_normal_exit(run.job, run.process, trace=run.job.member_trace) if trace_exchange else capture_normal_exit(run.job, run.process)
'''


class ExactTraceProfile(unittest.TestCase):
    def test_source_bound_exact_profiles_and_prospective_label(self):
        r = profile_switch(SOURCE)
        self.assertEqual(r['profiles'], ['fm_rtc', 'rr_f152']); self.assertFalse(r['RR_native_ownership_established'])

    def test_unrelated_profiles_missing_trace_and_missing_binding_refused(self):
        for changed in (SOURCE.replace('"rr_f152"', '"fm_rr"'), SOURCE.replace('trace_members=True', 'trace_members=False'),
                        SOURCE.replace('trace=run.job.member_trace', 'trace=None')):
            with self.subTest(changed=changed), self.assertRaises(AssertionError): profile_switch(changed)


if __name__ == '__main__': unittest.main()
