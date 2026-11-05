"""NATIVE-ADAPTER-FINAL-V independent re-review of the corrected V3 candidate (offline; no native/GUI/Job/FFI/process).

Usage (isolated interpreter, fresh output folder under research/experiments):
  python -I -B review_checks.py --out research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-FINAL-V-<stamp>/review-01

Tests decorated with @requirement assert the CORRECTED behaviour for the seven V1 findings (F1-F7);
the V1 review (preserved separately) asserted that those defects reproduced. All other tests are the
unchanged real-class regression coverage.
"""
import argparse
import ast
from contextlib import ExitStack
import copy
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as H  # noqa: E402  (also puts the read-only adapter folder on sys.path)

ADAPTER_FREEZE = 'daffc237b80eb5c35b49dcb445e11cda03ae91f86ba080b9a2177253d3aa8c16'
READER_FREEZE = '980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62'
WHEEL = 'e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6'
CANONICAL_DISPATCH = '2b4c7ad1f58be77466842fd9f3ee3bbf9f45bd8ede760c7117d993905119217d'
OUT = None
REGISTRY = {}


def requirement(fid, summary):
    def decorate(function):
        REGISTRY[function.__name__] = {'id': fid, 'requirement': summary}
        return function
    return decorate


class FastTime:
    """Replaces the time module inside public_driver so bounded waits finish instantly."""

    def __init__(self):
        self.base, self.n = time.monotonic(), 0

    def monotonic(self):
        self.n += 1
        return self.base + self.n * 0.5

    def sleep(self, seconds):
        return None


class Base(unittest.TestCase):
    def build_named(self, suffix, routes=('direct',), script=True):
        return self.build(routes, script, suffix)

    def build(self, routes=('direct',), script=True, suffix=''):
        work = OUT / 'work' / (self.id().split('.')[-1] + ('-' + suffix if suffix else ''))
        work.mkdir(parents=True)
        self.h = H.Harness(work, H.reader())
        if script:
            for route in routes:
                self.h.script_default(route)
        stack = ExitStack()
        for item in self.h.patches():
            stack.enter_context(item)
        self.addCleanup(stack.close)
        self.work = work
        self.rp = self.h.replay()
        return self.h, self.rp

    def cleanup_all(self):
        for item in list(self.rp.driver.active):
            self.rp.cleanup(item)

    def drain(self):
        """Finish leftover scripted clients the way Replay.run()'s final loop would (never raises)."""
        for client in self.h.context['_clients']:
            if client.result is None:
                try:
                    client.finish(10)
                except subprocess.TimeoutExpired:
                    pass

    def case(self, case_id):
        return self.rp.case_by_id[case_id]


# ---------------------------------------------------------------------------
# A. exact hashes, provenance and preserved records
# ---------------------------------------------------------------------------
class A_Hashes(unittest.TestCase):
    def test_adapter_and_reader_freezes_exact(self):
        adapter, reader = H.ADAPTER, H.READER
        self.assertEqual(H.sha(adapter / 'freeze.json'), ADAPTER_FREEZE)
        self.assertEqual(H.sha(reader / 'freeze.json'), READER_FREEZE)
        for folder in (adapter, reader):
            packet = json.loads((folder / 'freeze.json').read_bytes())
            self.assertIs(packet['native_authorized'], False)
            for name, row in packet['artifact_files'].items():
                self.assertEqual(H.sha(folder / name), row['sha256'], name)
                self.assertEqual((folder / name).stat().st_size, row['bytes'], name)
        extra = {p.name for p in H.ADAPTER.iterdir()} - set(json.loads((H.ADAPTER / 'freeze.json').read_bytes())['artifact_files'])
        self.assertEqual(extra, {'README.md', 'VALIDATION.json', 'freeze.json'})  # unhashed documents only

    def test_plan_join_and_forty_inputs_equal_227(self):
        freeze = json.loads((H.ADAPTER / 'freeze.json').read_bytes())
        exp = H.REPO / 'research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01'
        plan_path = exp / 'prepared-02/predeclared.json'
        self.assertEqual(H.sha(plan_path), freeze['predeclared_sha256'])
        plan = json.loads(plan_path.read_bytes())
        self.assertEqual((plan['state'], plan['native_launches'], len(plan['cases'])), ('prepared_NOT_ADMITTED', 0, 12))
        for key in ('runtime', 'auditor', 'admission', 'lease'):
            self.assertIsNone(plan[key])
        files = {p.relative_to(exp / 'prepared-02/inputs').as_posix(): H.sha(p) for p in (exp / 'prepared-02/inputs').rglob('*') if p.is_file()}
        source = {p.relative_to(H.HISTORY / 'inputs').as_posix(): H.sha(p) for p in (H.HISTORY / 'inputs').rglob('*') if p.is_file()}
        self.assertEqual(len(files), 40)
        self.assertEqual(files, source)
        self.assertEqual({k: v['sha256'] for k, v in plan['prepared_inputs'].items()}, {k: v for k, v in files.items()})
        self.assertFalse([n for n in files if n.endswith(('_his.nc', '_map.nc', '_rst.nc'))])
        # each declared mutation touches exactly its own file
        valid = exp / 'prepared-02/inputs/valid'
        for family, changed in (('bad-mesh', 'f34_net.nc'), ('empty-bc', 'f34_001.bc')):
            diff = [p.name for p in valid.iterdir() if p.read_bytes() != (valid.parent / family / p.name).read_bytes()]
            self.assertEqual(diff, [changed])
        slow = (valid.parent / 'slow/f34.mdu').read_bytes()
        self.assertIn(b'DtMax', slow)
        diff = [p.name for p in valid.iterdir() if p.read_bytes() != (valid.parent / 'slow' / p.name).read_bytes()]
        self.assertEqual(diff, ['f34.mdu'])

    def test_matrix_and_declared_bounds(self):
        plan = json.loads((H.REPO / 'research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01/prepared-02/predeclared.json').read_bytes())
        self.assertEqual({(c['route'], c['family']) for c in plan['cases']},
                         {(r, f) for r in ('direct', 'dimr') for f in ('natural', 'bad-mesh', 'empty-bc', 'control', 'timeout', 'cancel')})
        self.assertEqual(len({c['case_id'] for c in plan['cases']}), 12)
        timeouts = {c['family']: c['native_timeout_seconds'] for c in plan['cases']}
        self.assertEqual(timeouts, {'natural': 30, 'bad-mesh': 15, 'empty-bc': 15, 'control': 90, 'timeout': 2, 'cancel': 30})
        b = plan['bounds']
        self.assertEqual((b['max_native_launches'], b['max_concurrent_native'], b['attempts_each'], b['retry']), (12, 2, 1, False))
        self.assertIn('not a 600 s total', b['clock_scope'])
        for case in plan['cases']:  # plan argv must equal what Active composes
            self.assertEqual(case['public_argv'][:2], ['run', 'start'])
            self.assertEqual(case['public_argv'][case['public_argv'].index('--route') + 1], case['route'])
            self.assertEqual(case['public_argv'][case['public_argv'].index('--timeout') + 1], str(case['native_timeout_seconds']))

    def test_runtime_pins_and_installation(self):
        exp = H.REPO / 'research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01'
        pins = json.loads((exp / 'installed-product-pins.json').read_bytes())
        expected = json.loads((H.ADAPTER / 'expected-product.json').read_bytes())
        runtime = H.REPO / 'research/experiments/SHORT-CLOSE-COMPAT-PACK-I-20261105-02/build-01/runtime-venv'
        self.assertEqual((pins['count'], len(pins['payloads']), len(expected)), (191, 191, 191))
        for row in pins['payloads']:
            path = runtime / 'Lib/site-packages' / row['package_relative_path']
            self.assertEqual(H.sha(path), row['sha256'])
            self.assertEqual(row['sha256'], expected[row['package_relative_path']])
        self.assertFalse(list((runtime / 'Lib/site-packages').glob('*.pth')))
        contract = json.loads((exp / 'native-admission-contract.json').read_bytes())
        self.assertIs(contract['native_authorization'], False)
        self.assertEqual(contract['wheel']['sha256'], WHEEL)
        self.assertEqual(H.sha(contract['wheel']['path']), WHEEL)
        inspected = json.loads((exp / 'installation-inspection.json').read_text(encoding='utf-8-sig'))['result']
        for relative, row in inspected['binaries'].items():
            self.assertEqual(H.sha(row['path']), row['sha256'], relative)  # installation unchanged since inspection

    def test_historical_227_records_unchanged_and_states_preserved(self):
        expected = H.READER.parent.parent  # noqa: F841 (documenting intent only)
        reader_validation = json.loads((H.READER / 'VALIDATION.json').read_bytes())
        recorded = reader_validation['original227_manifests_unchanged']
        self.assertIs(recorded, True)
        reader_run = json.loads((H.REPO / 'research/experiments/SHORT-CLOSE-NATIVE-READER-I-20261105-01/tests-03/verification.json').read_bytes())
        for path, digest in reader_run['original227_manifest_hashes'].items():
            self.assertEqual(H.sha(Path(path)), digest)
        states = {n: H.original(n)['state'] for n in ('natural-direct', 'bad-mesh-direct', 'empty-bc-direct', 'timeout-direct', 'control-direct')}
        self.assertEqual(states, {'natural-direct': 'completed', 'bad-mesh-direct': 'failed', 'empty-bc-direct': 'failed',
                                  'timeout-direct': 'cleanup_failed', 'control-direct': 'cleanup_failed'})

    def test_canonical_dispatch_idle_and_unchanged(self):
        path = H.REPO / 'research/experiments/roadmap-coordinator-20261104/dispatch.json'
        self.assertEqual(H.sha(path), CANONICAL_DISPATCH)
        slot = json.loads(path.read_bytes())['native_slot']
        self.assertEqual((slot['owner'], slot['sequence']), ('idle', 228))
        self.assertFalse(list((H.REPO / 'research/experiments').glob('SHORT-CLOSE-G-native-rev04-*')))

    def test_real_numerical_gate_keys_on_retained_natural_outputs(self):
        module = H.load(H.REPO / 'research/workflows/verification/verify_serial_exit.py', 'serial_reader')
        folder = H.HISTORY / 'natural-direct'
        raw = module.raw_outputs(folder, json.loads((folder / 'manifest.json').read_bytes()))
        self.assertTrue(raw['history']['final_time_matches'] and raw['map']['final_time_matches'] and raw['final_restart_present'])
        files = {}
        for pattern in ('*_his.nc', '*_map.nc', '*_rst.nc'):
            for path in (folder / 'model').rglob(pattern):
                files[path.name] = path
        self.assertEqual(len(files), 4)
        self.assertEqual(sum(module.compare_native_data(p, p)['variables'] for p in files.values()), 191)

    def test_product_argv_cwd_and_exit_codes_match_adapter_expectation(self):
        source = (H.REPO / 'src/dfm_cli/runs.py').read_text(encoding='utf-8')
        self.assertIn('command, cwd = [executable, "--autostartstop", staged.name], model', source)
        self.assertIn('command, cwd = [executable, "dimr_config.xml"], destination', source)
        cli = (H.REPO / 'src/dfm_cli/cli.py').read_text(encoding='utf-8')
        self.assertIn('"5": "native execution/timeout/interruption"', cli)
        self.assertIn('cancel.add_argument("--wait"', cli)
        record = H.original('natural-direct')
        self.assertEqual(record['argv'][0], json.loads((H.REPO / 'research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01/installation-inspection.json')
                                                   .read_text(encoding='utf-8-sig'))['result']['binaries']['bin/dflowfm-cli.exe']['path'])
        for name, marker in (('bad-mesh-direct', 'Failed to open: f34_net.nc'), ('empty-bc-direct', 'No signals for polyline')):
            self.assertIn(marker, H.original(name)['diagnostics']['primary_error']['text'])


# ---------------------------------------------------------------------------
# B. real adapter classes + frozen reader on scripted fakes: success paths
# ---------------------------------------------------------------------------
class B_Composition(Base):
    def test_harness_records_are_valid_under_frozen_reader(self):
        h, rp = self.build(routes=('direct', 'dimr'))
        self.assertEqual(len(h.owners), 12)
        for case_id, owner in h.owners.items():
            from replay_adapter import expected_record
            audit = h.auditor.audit_record(owner.record, expected_record(h.context, owner.case, owner.folder))
            self.assertEqual(audit['audit_state'], 'qualified_full_lifetime_close', (case_id, audit['errors']))
        # negative control: a stale argv must be refused, so the positive result above is not vacuous
        owner = h.owners['natural-dimr']
        bad = copy.deepcopy(owner.record)
        bad['argv'][0] = h.exe['direct']
        from replay_adapter import expected_record
        self.assertEqual(h.auditor.audit_record(bad, expected_record(h.context, owner.case, owner.folder))['audit_state'], 'refused')

    def test_pair_success_real_classes_and_exact_reader(self):
        h, rp = self.build()
        rp.pair('direct')
        self.cleanup_all()
        self.assertEqual(rp.accepted, {'control-direct', 'timeout-direct', 'cancel-direct'})
        for target in ('timeout-direct', 'cancel-direct'):
            survival = json.loads((self.work / 'audits' / (target + '-control-survival.json')).read_bytes())
            self.assertEqual(survival['audit_state'], 'independent_control_survival_confirmed')
            self.assertTrue(all(survival[k] is True for k in ('passed', 'control_lifetime_passed', 'observer_same_handle_confirmed')))
            self.assertIs(survival['observer_supplies_lifetime_coverage'], False)
            self.assertIs(survival['any_Job_is_private_Job_proof'], False)
        for case_id in rp.accepted:
            audit = json.loads((self.work / 'audits' / (case_id + '.json')).read_bytes())
            self.assertEqual(audit['independent_raw_audit']['audit_state'], 'qualified_full_lifetime_close')
            self.assertIs(audit['independent_state_assertion']['case_success'], True)
            self.assertIs(audit['raw_record_rewritten'], False)
            self.assertEqual(audit['manifest_sha256'], H.sha(self.work / case_id / 'manifest.json'))
        self.assertEqual(h.kernel.handles, {})  # every observer handle released
        self.assertEqual(len(h.kernel.closed), 3)
        self.assertEqual(h.max_live, 2)
        self.assertEqual(rp.budget.active, set())
        for client in h.context['_clients']:
            self.assertIsNotNone(client.result, client.folder)

    def test_singles_success_and_real_diagnostic_markers(self):
        h, rp = self.build()
        for family in ('natural', 'bad-mesh', 'empty-bc'):
            rp.single(self.case(family + '-direct'))
        self.cleanup_all()
        self.assertEqual(rp.accepted, {'natural-direct', 'bad-mesh-direct', 'empty-bc-direct'})
        self.assertTrue((self.work / 'audits/natural-direct-outputs.json').is_file())
        self.assertEqual(h.kernel.handles, {})
        self.assertEqual(rp.results['bad-mesh-direct']['independent_state_assertion']['recorded_state'], 'failed')
        self.assertEqual(rp.results['natural-direct']['public_result']['returncode'], 0)
        self.assertEqual(rp.results['bad-mesh-direct']['public_result']['returncode'], 5)

    def test_full_twelve_case_run_both_routes(self):
        h, rp = self.build(routes=('direct', 'dimr'))
        report = rp.run()
        self.assertEqual(report['state'], 'passed_all12_lifetime_close_isolation_and_raw191', report.get('error'))
        self.assertEqual(len(report['attempts']), 12)
        self.assertEqual(report['actual_manifest_count'], 12)
        self.assertEqual((report['max_native_launches'], report['max_concurrent_native'], report['retry']), (12, 2, False))
        self.assertLessEqual(h.max_live, 2)
        self.assertEqual(h.kernel.handles, {})
        self.assertEqual(list((self.work / 'cleanup-errors').glob('*')), [])
        self.assertEqual(list((self.work / 'audit-errors').glob('*')), [])
        self.assertEqual(json.loads((self.work / 'comparison191.json').read_bytes())['variables'], 191)
        for client in h.context['_clients']:
            self.assertIsNotNone(client.result)
        self.assertEqual(sorted(p.name for p in (self.work / 'attempts').glob('*')), sorted(c + '.json' for c in h.owners))

    def test_natural_race_is_never_a_forced_exercise(self):
        h, rp = self.build()
        # the timeout target completes naturally with exit 0 before any stop request
        case = self.case('timeout-direct')
        natural = H.relabel(H.original('natural-direct'), tag=40, run_dir=self.work / 'timeout-direct', state='completed',
                            exe_new=h.exe['direct'], sha_new=h.sha['direct'])
        h.script(case, tag=40, end=('polls', 3), go_at=140, final_at=141, record=natural)
        control = rp.start(self.case('control-direct'))
        try:
            control.ready()
            target = rp.start(case)
            target.ready()
            with self.assertRaises(ValueError) as caught:
                rp.finish(target)
            self.assertIn('Actual natural race', str(caught.exception))
        finally:
            self.cleanup_all()
        result = rp.results['timeout-direct']
        self.assertTrue(result['independent_state_assertion']['passed'])
        self.assertFalse(result['independent_state_assertion']['case_success'])
        self.assertNotIn('timeout-direct', rp.accepted)
        self.assertEqual(json.loads((self.work / 'timeout-direct/manifest.json').read_bytes())['state'], 'completed')

    def test_public_json_and_exit_code_mismatches_are_refused(self):
        variants = {
            'protocol_3': ({'protocol_version': 3, 'ok': False}, None, 'Unsupported public JSON protocol'),
            'protocol_true': ({'protocol_version': True, 'ok': False}, None, 'Unsupported public JSON protocol'),
            'ok_true_for_failed_record': ({'protocol_version': 2, 'ok': True}, None, 'Actual installed public exit/JSON differs'),
            'ok_missing': ({'protocol_version': 2}, None, 'Actual installed public exit/JSON differs'),
            'exit_zero_for_failed_record': (None, 0, 'Actual installed public exit/JSON differs'),
            'exit_six_for_failed_record': (None, 6, 'Actual installed public exit/JSON differs'),
            'stdout_not_json': ('EMPTY', None, 'Public JSON object unavailable'),
        }
        for name, (payload, code, needle) in variants.items():
            with self.subTest(name):
                h, rp = self.build_named(name)
                owner = h.owners['bad-mesh-direct']
                owner.payload_override = payload
                if code is not None:
                    owner.returncode = code
                with self.assertRaises(ValueError) as caught:
                    rp.single(self.case('bad-mesh-direct'))
                self.assertIn(needle, str(caught.exception))
                self.assertNotIn('bad-mesh-direct', rp.accepted)
                self.cleanup_all()
                self.assertEqual(h.kernel.handles, {})
                saved = json.loads((self.work / 'audits/bad-mesh-direct.json').read_bytes())  # the refused result is still preserved
                self.assertEqual(saved['independent_raw_audit']['audit_state'], 'qualified_full_lifetime_close')
        # positive control for the same fixture
        h, rp = self.build_named('positive')
        rp.single(self.case('bad-mesh-direct'))
        self.assertIn('bad-mesh-direct', rp.accepted)
        self.cleanup_all()

    def test_adapter_requires_stop_achieved_independently_of_case_success(self):
        h, rp = self.build()
        real = h.auditor

        class Lenient:
            audit_record = staticmethod(real.audit_record)

            @staticmethod
            def assert_public_state(record, expectation):
                value = real.assert_public_state(record, expectation)
                if expectation['family'] == 'timeout':
                    value = {**value, 'passed': True, 'case_success': True, 'stop_achieved': False}
                return value
        rp.auditor = Lenient
        control = rp.start(self.case('control-direct'))
        try:
            control.ready()
            target = rp.start(self.case('timeout-direct'))
            target.ready()
            with self.assertRaises(ValueError) as caught:
                rp.finish(target)
            self.assertIn('not a forced-stop exercise', str(caught.exception))
        finally:
            self.cleanup_all()
        self.assertNotIn('timeout-direct', rp.accepted)

    def test_survival_refusals_propagate_and_dispose(self):
        h, rp = self.build()
        h.kernel.procs  # processes are created lazily; force any-Job false for every process created after this point
        real_add = h.kernel.add_process

        def add(pid, creation, image):
            real_add(pid, creation, image)
            h.kernel.procs[pid]['in_job'] = False
        h.kernel.add_process = add
        with self.assertRaises(ValueError) as caught:
            rp.pair('direct')
        self.cleanup_all()
        self.assertIn('Independent control survival audit refused', str(caught.exception) + ' | ' + str(
            json.loads((self.work / 'audits/timeout-direct-control-survival.json').read_bytes())['errors']) or 'x')
        survival = json.loads((self.work / 'audits/timeout-direct-control-survival.json').read_bytes())
        self.assertEqual(survival['audit_state'], 'refused')
        self.assertEqual(h.kernel.handles, {})

    @requirement('F1', 'Complete raw survival bundle is saved before the actual reader runs, including when the verdict is refused or the reader raises')
    def test_f1_complete_bundle_saved_before_reader_including_refused_verdict(self):
        required = {'schema', 'target_case_id', 'target_before', 'target_exit', 'control_before', 'control_after', 'control_pre_cleanup',
                    'control_final', 'target_observer_close', 'control_observer_close'}
        reader = H.reader()
        from replay_adapter import expected_record
        # (1) success: both bundles saved; the verdict is bound to the saved content and re-runs identically offline
        h, rp = self.build()
        rp.pair('direct')
        self.cleanup_all()
        control = json.loads((self.work / 'control-direct/manifest.json').read_bytes())
        for target in ('timeout-direct', 'cancel-direct'):
            saved = json.loads((self.work / 'observations' / (target + '-survival-final.json')).read_bytes())
            self.assertEqual(set(saved), required)
            verdict = json.loads((self.work / 'audits' / (target + '-control-survival.json')).read_bytes())
            self.assertEqual(verdict['observations_sha256'], reader.digest(saved))
            again = reader.audit_control_survival(json.loads((self.work / target / 'manifest.json').read_bytes()), control, saved,
                                                  expected_record(h.context, self.case('control-direct'), self.work / 'control-direct'))
            self.assertEqual(again['audit_state'], 'independent_control_survival_confirmed')
        # (2) refused verdict: the bundle exists and reproduces the refusal
        h, rp = self.build_named('refused')
        real_add = h.kernel.add_process

        def add(pid, creation, image):
            real_add(pid, creation, image)
            h.kernel.procs[pid]['in_job'] = False
        h.kernel.add_process = add
        with self.assertRaises(ValueError):
            rp.pair('direct')
        self.cleanup_all()
        saved = json.loads((self.work / 'observations/timeout-direct-survival-final.json').read_bytes())
        self.assertEqual(set(saved), required)
        verdict = json.loads((self.work / 'audits/timeout-direct-control-survival.json').read_bytes())
        self.assertEqual(verdict['audit_state'], 'refused')
        self.assertEqual(verdict['observations_sha256'], reader.digest(saved))
        again = reader.audit_control_survival(json.loads((self.work / 'timeout-direct/manifest.json').read_bytes()),
                                              json.loads((self.work / 'control-direct/manifest.json').read_bytes()), saved,
                                              expected_record(h.context, self.case('control-direct'), self.work / 'control-direct'))
        self.assertEqual(again['audit_state'], 'refused')
        # (3) the file precedes the reader call: a reader that raises still leaves the complete bundle behind
        h, rp = self.build_named('reader-raises')

        class Raising:
            audit_record = staticmethod(h.auditor.audit_record)
            assert_public_state = staticmethod(h.auditor.assert_public_state)

            @staticmethod
            def audit_control_survival(*args):
                raise RuntimeError('synthetic reader failure')
        rp.auditor = Raising
        with self.assertRaises(RuntimeError):
            rp.pair('direct')
        self.cleanup_all()
        self.assertEqual(set(json.loads((self.work / 'observations/timeout-direct-survival-final.json').read_bytes())), required)


# ---------------------------------------------------------------------------
# C. error disposal for every started owner/client/observer
# ---------------------------------------------------------------------------
class C_Disposal(Base):
    def test_warmup_failure_aborts_every_client_and_launches_nothing(self):
        h, rp = self.build()
        from public_driver import Warm
        with patch.object(Warm, 'ready', side_effect=ValueError('Warm public CLI readiness unavailable')):
            report = rp.run()
        self.assertEqual(report['state'], 'stopped_no_retry_NOT_ACCEPTED')
        self.assertEqual(h.kernel.calls, [])
        self.assertFalse(list(self.work.glob('*/manifest.json')))
        self.assertTrue(h.context['_clients'])
        for client in h.context['_clients']:
            self.assertFalse(client.result['command_started'])
            self.assertEqual(client.result['returncode'], 2)
        self.assertEqual(len(report['attempts']), 1)  # a pre-go failure still spends the single attempt

    def test_control_cancel_client_warmup_failure_aborts_started_siblings(self):
        h, rp = self.build()
        from public_driver import Warm
        real = Warm.ready

        def ready(self):
            if self.folder.name == 'control-direct-cancel':
                raise ValueError('synthetic cancel-client readiness failure')
            return real(self)
        with patch.object(Warm, 'ready', ready):
            with self.assertRaises(ValueError):
                rp.start(self.case('control-direct'))
            # Active.__init__ failed before registration: the adapter's run() finally loop must still see both clients
            self.assertEqual(rp.driver.active, [])
            self.assertEqual(len(h.context['_clients']), 2)
            for client in h.context['_clients']:
                self.assertFalse(client.started)
                client.finish(10)
                self.assertEqual(client.result['returncode'], 2)
        self.assertFalse((self.work / 'control-direct').exists())

    def test_failure_after_live_control_disposes_owner_client_and_observer(self):
        h, rp = self.build()
        control = rp.start(self.case('control-direct'))
        control.ready()
        self.assertEqual(len(h.kernel.handles), 1)
        record, public, closed = control.dispose()  # what Replay.cleanup() does after any pair/readiness error
        self.assertEqual(record['state'], 'cancelled')
        self.assertEqual(public['returncode'], 5)
        self.assertEqual(h.kernel.handles, {})
        self.assertTrue(h.owners['control-direct'].cancel_requested)
        self.assertTrue(closed['close']['succeeded'])
        self.drain()

    def test_mid_pair_audit_refusal_disposes_both_owners_and_keeps_refusal_evidence(self):
        h, rp = self.build()
        h.owners['timeout-direct'].record['ownership']['job_close']['return_value'] = True  # raw close no longer an int
        rp.single = lambda case: None  # start at the pair, like the author's flow tests, but with REAL Active/Warm/Driver
        report = rp.run()
        self.assertEqual(report['state'], 'stopped_no_retry_NOT_ACCEPTED')
        refused = json.loads((self.work / 'audits/timeout-direct.json').read_bytes())
        self.assertEqual(refused['independent_raw_audit']['audit_state'], 'refused')
        self.assertEqual(report['results']['control-direct']['independent_raw_audit']['audit_state'], 'qualified_full_lifetime_close')
        self.assertEqual(report['results']['control-direct']['independent_state_assertion']['recorded_state'], 'cancelled')
        self.assertTrue(h.owners['control-direct'].cancel_requested)
        self.assertEqual(h.kernel.handles, {})
        for client in h.context['_clients']:
            self.assertIsNotNone(client.result)
        self.assertEqual(list((self.work / 'cleanup-errors').glob('*')), [])
        self.assertEqual(report['attempts'], ['control-direct', 'timeout-direct'])

    @requirement('F2', 'A known-unstarted warm client is aborted: no cancel, no native manifest wait, no fabricated lifetime, primary cause preserved')
    def test_f2_known_unstarted_client_aborts_without_cancel_or_manifest(self):
        h, rp = self.build()
        calls = {'recheck': 0}

        def recheck(context):
            calls['recheck'] += 1
            if calls['recheck'] == 2:  # Active.begin, after the clients are warm and before any go pipe call
                raise ValueError('Adapter freeze changed')
        fast = FastTime()
        with patch('admission.recheck_start', side_effect=recheck), patch('public_driver.time', fast):
            report = rp.run()
        self.assertLess(fast.n * 0.5, 30)                                  # was >= 110 s waiting for a client that never started
        self.assertEqual(report['error']['message'], 'Adapter freeze changed')
        self.assertEqual(report['state'], 'stopped_no_retry_NOT_ACCEPTED')  # primary cause not overwritten by a cleanup failure
        self.assertEqual(list((self.work / 'cleanup-errors').glob('*')), [])
        self.assertFalse((self.work / 'commands/natural-direct-cleanup-cancel').exists())  # no spurious public cancel
        receipt = json.loads((self.work / 'observations/natural-direct-unstarted-client.json').read_bytes())
        self.assertIs(receipt['native_owner_started'], False)
        self.assertIs(receipt['public_client']['command_started'], False)
        self.assertEqual(receipt['public_client']['command_delivery'], 'not_attempted')
        self.assertEqual(receipt['public_client']['returncode'], 2)
        self.assertFalse((self.work / 'natural-direct').exists())          # no native manifest or folder invented
        self.assertFalse((self.work / 'audits/natural-direct.json').exists())
        self.assertEqual(h.kernel.calls, [])
        self.assertFalse(h.owners['natural-direct'].go_count)
        self.assertEqual(rp.budget.active, set())
        self.assertEqual(report['attempts'], ['natural-direct'])           # the single attempt is still spent (no retry)

    @requirement('F3', 'Cleanup recovery of a failed cancel delivery is allowed ONLY before any go pipe attempt; after a pipe attempt it is never repeated')
    def test_f3_cancel_recovery_only_before_pipe_attempt(self):
        import public_driver
        # (a) receipt failure BEFORE the pipe: still unattempted, disposal recovers with exactly one actual delivery
        h, rp = self.build_named('a')
        item = rp.start(self.case('control-direct'))
        item.ready()
        real = public_driver.save
        state = {'failed': False}

        def save(path, value):
            if path.name == 'started.json' and path.parent.name == 'control-direct-cancel' and not state['failed']:
                state['failed'] = True
                raise OSError('synthetic pre-pipe receipt failure')
            return real(path, value)
        with patch.object(public_driver, 'save', save):
            with self.assertRaises(OSError):
                item.cancel()
            self.assertFalse(item.cancelled)
            self.assertFalse(item.cancel_client.go_attempted)
            self.assertEqual(item.cancel_client.delivery_state, 'not_attempted')
            record, public, closed = item.dispose()
        self.assertEqual(record['state'], 'cancelled')
        self.assertTrue(h.owners['control-direct'].cancel_requested)
        self.assertEqual(item.cancel_client.process.lines, [b'go\n'])
        self.assertEqual(item.cancel_client.go_receipts, 2)
        self.assertTrue((self.work / 'commands/control-direct-cancel/started-2.json').is_file())
        self.assertEqual(h.kernel.handles, {})
        self.drain()
        # (b) failure AFTER the pipe call began (line written, flush failed): unknown, never repeated by disposal
        h, rp = self.build_named('b')
        item = rp.start(self.case('control-direct'))
        item.ready()
        item.cancel_client.process.stdin.mode = 'flush_fail'
        with self.assertRaises(BrokenPipeError):
            item.cancel()
        self.assertTrue(item.cancel_client.go_attempted)
        self.assertEqual(item.cancel_client.delivery_state, 'unknown')
        self.assertFalse(item.cancelled)
        record, public, closed = item.dispose()
        self.assertEqual(item.cancel_client.process.lines, [b'go\n'])      # exactly one pipe write, ever
        self.assertEqual(item.cancel_client.go_receipts, 1)
        self.assertIsNone(item.cancel_client.result['command_started'])
        self.assertEqual(item.cancel_client.result['command_delivery'], 'unknown')
        self.assertEqual(h.kernel.handles, {})
        self.drain()
        # (c) pipe died during the write (nothing delivered, still uncertain to the adapter): no repeat either
        h, rp = self.build_named('c')
        item = rp.start(self.case('control-direct'))
        item.ready()
        item.cancel_client.process.stdin.mode = 'dead'
        with self.assertRaises(BrokenPipeError):
            item.cancel()
        with patch('public_driver.time', FastTime()):
            with self.assertRaises(subprocess.TimeoutExpired):          # conservative limit: the owner is left to its own native timeout
                item.dispose()
        self.assertEqual(item.cancel_client.process.lines, [])
        self.assertEqual(item.cancel_client.go_receipts, 1)
        self.assertFalse(h.owners['control-direct'].cancel_requested)
        self.assertEqual(h.kernel.handles, {})                           # observer still released
        self.drain()

    @requirement('F4', 'A snapshot failure still closes the observer HANDLE and records the failure as non-exit-proof')
    def test_f4_snapshot_failure_still_closes_observer(self):
        h, rp = self.build()
        item = rp.start(self.case('control-direct'))
        item.ready()
        self.assertEqual(len(h.kernel.handles), 1)
        h.kernel.fail.add('snapshot')
        closed = item.close_observer()
        self.assertEqual(h.kernel.handles, {})
        self.assertIs(closed['close']['succeeded'], True)
        self.assertEqual(closed['final_snapshot']['state'], 'unavailable')
        self.assertIs(closed['final_snapshot']['not_exit_proof'], True)
        self.assertEqual(closed['final_snapshot']['error']['type'], 'OSError')
        self.assertIs(item.close_observer(), closed)                      # idempotent, no second close
        saved = json.loads((self.work / 'observations/control-direct-observer-close.json').read_bytes())
        self.assertEqual(saved['close']['succeeded'], True)
        h.kernel.fail.discard('snapshot')
        item.dispose()
        self.drain()

    @requirement('F5', 'Sharing/lock errors 32/33 while reading the manifest are unavailable observations with a diagnostic; real denial and unknown errors still raise')
    def test_f5_sharing_violations_unknown_with_diagnostic_real_denial_raises(self):
        import public_driver
        real = public_driver.no_alias

        def flaky(winerror, times=1):
            counter = {'n': 0}

            def replace(path, **kw):
                if Path(path).name == 'manifest.json' and counter['n'] < times:
                    counter['n'] += 1
                    err = PermissionError(13, 'synthetic manifest read error')
                    err.winerror = winerror
                    raise err
                return real(path, **kw)
            return replace
        for winerror in (32, 33):
            with self.subTest(winerror):
                h, rp = self.build_named('w%d' % winerror)
                item = rp.start(self.case('control-direct'))
                item.client.process.poll()
                with patch.object(public_driver, 'no_alias', flaky(winerror)):
                    self.assertIsNone(item.sample())                       # unknown now, not an exit and not an exception
                errors = h.context['_manifest_read_errors']
                self.assertEqual([(e['winerror'], e['not_exit_proof']) for e in errors], [(winerror, True)])
                self.assertEqual(errors[0]['type'], 'PermissionError')
                self.assertIsNotNone(item.sample())                        # the next poll proceeds normally and captures
                item.dispose()
                self.drain()
        for winerror in (5, None):                                         # real denial / unclassified: loud
            with self.subTest(winerror):
                h, rp = self.build_named('x%s' % winerror)
                item = rp.start(self.case('control-direct'))
                with patch.object(public_driver, 'no_alias', flaky(winerror)):
                    with self.assertRaises(PermissionError):
                        item.sample()
                self.assertEqual(h.context.get('_manifest_read_errors', []), [])
                item.dispose()
                self.drain()
        self.assertIsNone(public_driver.manifest(self.work / 'does-not-exist', []))   # absent file: no diagnostic, plain None
        # end to end: a transient 32 during a full run neither aborts it nor disappears from the report
        h, rp = self.build_named('run', routes=('direct', 'dimr'))
        counter = {'n': 0}

        def once(path, **kw):
            if Path(path).name == 'manifest.json':
                counter['n'] += 1
                if counter['n'] == 5:
                    err = PermissionError(13, 'synthetic')
                    err.winerror = 32
                    raise err
            return real(path, **kw)
        with patch.object(public_driver, 'no_alias', once):
            report = rp.run()
        self.assertEqual(report['state'], 'passed_all12_lifetime_close_isolation_and_raw191', report.get('error'))
        self.assertEqual([e['winerror'] for e in report['manifest_polling_errors']], [32])

    @requirement('F6', 'An uncertain go stays null (never declared unstarted), is never repeated, and is not mistaken for a known-unstarted client')
    def test_f6_uncertain_go_remains_null_and_never_repeats(self):
        from public_driver import Warm
        for mode, delivered in (('dead', False), ('flush_fail', True)):
            with self.subTest(mode):
                h, rp = self.build_named(mode)
                warm = Warm(h.context, self.work / 'commands' / 'probe', ['run', 'start', 'x.mdu', '--out', str(self.work / 'natural-direct')])
                warm.ready()
                warm.process.stdin.mode = mode
                with self.assertRaises(BrokenPipeError):
                    warm.go()
                self.assertTrue(warm.go_attempted)
                self.assertFalse(warm.started)
                self.assertEqual(warm.delivery_state, 'unknown')
                with self.assertRaises(ValueError):
                    warm.go()                                             # never repeats
                self.assertEqual(len(warm.process.lines), 1 if delivered else 0)
                self.assertEqual(h.owners['natural-direct'].go_count, 1 if delivered else 0)
                result = warm.finish(5)
                self.assertIsNone(result['command_started'])               # null: neither started nor unstarted
                self.assertEqual(result['command_delivery'], 'unknown')
                self.assertIs(result['go_attempted'], True)
                self.assertEqual(len(warm.process.lines), 1 if delivered else 0)
                if not delivered:
                    self.assertEqual(result['returncode'], 1)             # honest: the pipe broke because the client had died
        # pre-pipe receipt failure is KNOWN undelivered and retryable exactly once
        h, rp = self.build_named('prepipe')
        import public_driver
        warm = Warm(h.context, self.work / 'commands' / 'probe2', ['run', 'start', 'x.mdu', '--out', str(self.work / 'natural-direct')])
        warm.ready()
        real = public_driver.save
        seen = {'n': 0}

        def save(path, value):
            if path.name == 'started.json':
                seen['n'] += 1
                if seen['n'] == 1:
                    raise OSError('synthetic receipt failure')
            return real(path, value)
        with patch.object(public_driver, 'save', save):
            with self.assertRaises(OSError):
                warm.go()
            self.assertFalse(warm.go_attempted)
            self.assertEqual(warm.delivery_state, 'not_attempted')
            warm.go()
        self.assertTrue(warm.started)
        self.assertEqual(warm.delivery_state, 'delivered')
        self.assertEqual(warm.process.lines, [b'go\n'])
        self.assertEqual(warm.finish(5)['command_started'], True)
        # an unknown-delivery client is NOT disposed as unstarted: the owner path (cancel + manifest) is taken
        h, rp = self.build_named('active')
        h.pipe_modes['natural-direct-start'] = 'flush_fail'
        with patch('public_driver.time', FastTime()):
            report = rp.run()
        self.assertEqual(h.owners['natural-direct'].go_count, 1)
        self.assertFalse((self.work / 'observations/natural-direct-unstarted-client.json').exists())
        self.assertTrue((self.work / 'commands/natural-direct-cleanup-cancel').exists())
        self.assertIsNone(json.loads((self.work / 'commands/natural-direct-start/invocation.json').read_bytes())['command_started'])
        self.assertTrue((self.work / 'natural-direct/manifest.json').is_file())

    def test_warm_finish_timeout_is_retryable_and_final_files_close(self):
        h, rp = self.build()
        from public_driver import Warm
        folder = self.work / 'commands' / 'timeout-warm'
        warm = Warm(h.context, folder, ['run', 'start', 'x.mdu', '--out', str(self.work / 'natural-direct')])
        warm.ready()
        warm.go()
        h.owners['natural-direct'].end = ('polls', 10 ** 6)  # owner never ends
        with self.assertRaises(subprocess.TimeoutExpired):
            warm.finish(0.1)
        self.assertIsNone(warm.result)
        self.assertFalse(warm.out.closed)  # nothing leaks into later success: a retry can still complete
        h.owners['natural-direct'].end = ('polls', 1)
        result = warm.finish(5)
        self.assertEqual(result['returncode'], 0)
        self.assertTrue(warm.out.closed and warm.err.closed)

    def test_budget_never_exceeds_two_active_or_twelve_attempts(self):
        h, rp = self.build(routes=('direct', 'dimr'))
        rp.run()
        self.assertLessEqual(h.max_live, 2)
        self.assertEqual(len(rp.budget.attempted), 12)
        with self.assertRaises(ValueError):
            rp.budget.reserve('natural-direct')  # no retry of a spent case

    def test_budget_caps_checked_directly(self):
        from replay_adapter import Budget
        from prepare import matrix
        budget = Budget(matrix())
        budget.reserve('control-direct')
        budget.reserve('timeout-direct')
        with self.assertRaises(ValueError):
            budget.reserve('cancel-direct')            # third concurrent native owner
        budget.finished('timeout-direct')
        with self.assertRaises(ValueError):
            budget.reserve('timeout-direct')           # a spent case is never retried
        budget.reserve('cancel-direct')
        budget.started -= 601
        with self.assertRaises(ValueError):
            budget.reserve('natural-direct')           # scheduling clock expired

    def test_admission_failure_before_start_launches_no_client(self):
        h, rp = self.build()
        with patch('admission.recheck_start', side_effect=ValueError('Admission changed')):
            report = rp.run()
        self.assertEqual(report['state'], 'stopped_no_retry_NOT_ACCEPTED')
        self.assertEqual(h.context['_clients'], [])
        self.assertEqual(h.kernel.calls, [])
        self.assertEqual(report['attempts'], [])


# ---------------------------------------------------------------------------
# F/G. warm client semantics, observer capture failures, deadlines, pass keys
# ---------------------------------------------------------------------------
class F_WarmClientAndGates(Base):
    def _warm(self, text, *, sha=None, replace=None, ready_exists=False):
        module = H.load(H.ADAPTER / 'warm_client.py', 'warm_under_test')
        folder = OUT / 'work' / ('warm-%s' % hashlib.sha256(repr((text, sha, replace, ready_exists)).encode()).hexdigest()[:8])
        folder.mkdir(parents=True, exist_ok=True)
        arguments = folder / 'arguments.json'
        arguments.write_text(json.dumps(['run', 'start', 'x.mdu']))
        ready = folder / 'ready.json'
        if ready_exists:
            ready.write_text('{}')
        calls = []
        fake = types.ModuleType('dfm_cli')
        fake.__file__ = 'SYNTHETIC/dfm_cli/__init__.py'
        cli = types.ModuleType('dfm_cli.cli')
        cli.main = lambda a: (calls.append(list(a)), 77)[1]

        class Stdin:
            def readline(self_inner):
                if replace:
                    arguments.write_text(replace)
                return text
        argv = ['warm_client.py', '--arguments', str(arguments), '--sha256', sha or H.sha(arguments), '--ready', str(ready)]
        with patch.dict(sys.modules, {'dfm_cli': fake, 'dfm_cli.cli': cli}), patch.object(sys, 'argv', argv), patch.object(sys, 'stdin', Stdin()):
            try:
                value = module.main()
            except Exception as exc:  # noqa: BLE001
                return type(exc).__name__, calls, ready
        return value, calls, ready

    def test_real_warm_client_go_abort_eof_and_tamper(self):
        value, calls, ready = self._warm('go\n')
        self.assertEqual((value, calls), (77, [['run', 'start', 'x.mdu']]))
        self.assertEqual(json.loads(ready.read_bytes())['state'], 'installed_public_cli_imported_command_NOT_started')
        for text in ('abort\n', '', 'GO\n', 'go'):
            value, calls, _ = self._warm(text)
            self.assertEqual((value, calls), (2, []), text)       # abort / EOF / malformed never reach the product CLI
        value, calls, _ = self._warm('go\n', replace=json.dumps(['run', 'cancel', 'y']))
        self.assertEqual((value, calls), ('ValueError', []))     # arguments replaced after warm import
        value, calls, ready = self._warm('go\n', sha='0' * 64)
        self.assertEqual((value, calls, ready.exists()), ('ValueError', [], False))  # refused before import or ready
        value, calls, _ = self._warm('go\n', ready_exists=True)
        self.assertEqual((value, calls), ('FileExistsError', []))

    def test_warm_python_and_origin_mismatch_refused_and_go_never_retried(self):
        h, rp = self.build()
        from public_driver import Warm
        warm = Warm(h.context, self.work / 'commands' / 'w1', ['run', 'start', 'x.mdu', '--out', str(self.work / 'natural-direct')])
        ready = self.work / 'commands/w1/ready.json'
        body = json.loads(ready.read_bytes())
        for key, value, needle in (('python', str(self.work / 'other/python.exe'), 'wrong interpreter'),
                                   ('package_origin', str(self.work / 'src/dfm_cli/__init__.py'), 'unadmitted product')):
            ready.write_text(json.dumps({**body, key: value}))
            with self.assertRaises(ValueError) as caught:
                warm.ready()
            self.assertIn(needle, str(caught.exception))
        ready.write_text(json.dumps(body))
        warm.ready()
        warm.go()
        with self.assertRaises(ValueError):
            warm.go()
        self.assertEqual(warm.process.lines, [b'go\n'])           # exactly one go
        self.drain()

    def test_capture_failures_never_leak_and_never_retry(self):
        for failure in ('open', 'times', 'image'):
            with self.subTest(failure):
                h, rp = self.build_named('capture-' + failure)
                control = rp.start(self.case('control-direct'))
                h.kernel.fail.add(failure)
                with patch('public_driver.time', FastTime()):
                    with self.assertRaises(ValueError):
                        control.ready()
                self.assertTrue(control.capture_attempted)
                self.assertIsNone(control.probe)
                self.assertEqual(h.kernel.handles, {}, failure)    # an opened handle is closed before giving up
                saved = json.loads((self.work / 'observations/control-direct-capture-unavailable.json').read_bytes())
                self.assertIs(saved['not_exit_proof'], True)
                self.assertIs(saved['retry'], False)
                if failure != 'open':
                    self.assertTrue(saved['observer_close']['succeeded'])
                h.kernel.fail.discard(failure)
                opened = h.kernel.calls.count('OpenProcess')
                with patch('public_driver.time', FastTime()):
                    with self.assertRaises(ValueError):
                        control.ready()                           # no second capture attempt, ever
                self.assertEqual(h.kernel.calls.count('OpenProcess'), opened)
                control.dispose()
                self.drain()

    def test_identity_mismatch_rejects_capture_and_closes_handle(self):
        h, rp = self.build()
        control = rp.start(self.case('control-direct'))
        owner = h.owners['control-direct']
        ident = owner.record['ownership']['native_identity']
        control.client.process.poll()  # first poll: owner writes the running manifest and registers the process
        h.kernel.procs[ident['pid']]['creation'] += 1  # a recycled PID would carry another birth
        self.assertIsNone(control.sample())
        self.assertEqual(h.kernel.handles, {})
        saved = json.loads((self.work / 'observations/control-direct-capture-unavailable.json').read_bytes())
        self.assertIn('identity/image mismatch', saved['error']['message'])
        self.assertTrue(saved['observer_close']['succeeded'])
        control.dispose()
        self.drain()

    def test_scheduling_deadline_blocks_new_starts_before_any_client(self):
        h, rp = self.build()
        rp.budget.started -= 601
        with self.assertRaises(ValueError) as caught:
            rp.start(self.case('natural-direct'))
        self.assertIn('scheduling deadline exhausted', str(caught.exception))
        self.assertEqual(h.context['_clients'], [])               # refused before any warm client existed
        self.assertEqual(h.kernel.calls, [])

    def test_deadline_passing_during_warmup_is_refused_before_go(self):
        h, rp = self.build()
        rp.context['_schedule_deadline'] = time.monotonic() - 1   # warm-up consumed the rest of the 600 s; reserve() already passed
        with self.assertRaises(ValueError) as caught:
            rp.start(self.case('natural-direct'))
        self.assertIn('Batch scheduling deadline exceeded before native go', str(caught.exception))
        self.assertFalse(h.owners['natural-direct'].go_count)
        self.assertEqual(h.kernel.calls, [])

    def test_pass_key_predicates_equal_reader_freeze_pass_keys(self):
        from replay_adapter import full_audit_pass, control_survival_pass
        keys = json.loads((H.READER / 'freeze.json').read_bytes())['pass_keys']
        record_keys, survival_keys = keys['audit_record'], keys['audit_control_survival']
        self.assertTrue(full_audit_pass(dict(record_keys)))
        self.assertTrue(control_survival_pass(dict(survival_keys)))
        for predicate, good in ((full_audit_pass, record_keys), (control_survival_pass, survival_keys)):
            for key in good:
                for bad in (None, False, 1, 'passed', 'refused', 0):
                    self.assertFalse(predicate({**good, key: bad}), (predicate.__name__, key, bad))
                self.assertFalse(predicate({k: v for k, v in good.items() if k != key}))
        self.assertFalse(full_audit_pass(None))
        self.assertFalse(control_survival_pass([]))
        self.assertEqual(keys['assert_public_state'], {'passed': True, 'case_success': True})

    def test_manifests_are_never_rewritten_by_the_adapter(self):
        h, rp = self.build(routes=('direct', 'dimr'))
        rp.run()
        self.assertEqual(len(rp.results), 12)
        for case_id, result in rp.results.items():
            self.assertEqual(result['manifest_sha256'], H.sha(self.work / case_id / 'manifest.json'))
            self.assertEqual(H.sha(self.work / case_id / 'manifest.json'), hashlib.sha256(json.dumps(h.owners[case_id].record).encode()).hexdigest())


# ---------------------------------------------------------------------------
# D. admission adversaries (real file joins, synthetic lease; never a grant)
# ---------------------------------------------------------------------------
class D_Admission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import admission
        import draft_grant
        from prepare import EXPERIMENTS, PREPARED, OWNER, save
        cls.admission, cls.EXP, cls.PREPARED = admission, EXPERIMENTS, PREPARED
        cls.dir = OUT / 'work' / 'admission'
        cls.dir.mkdir(parents=True)
        cls.root = EXPERIMENTS / ('SHORT-CLOSE-G-native-rev04-REVIEW-PROBE-' + hashlib.sha256(str(OUT).encode()).hexdigest()[:8])
        review = {'state': 'reviewed_offline_only', 'native_authorized': False, 'reader_freeze_sha256': READER_FREEZE,
                  'adapter_freeze_sha256': ADAPTER_FREEZE, 'predeclared_sha256': H.sha(PREPARED / 'predeclared.json'),
                  'wheel_sha256': WHEEL, 'SYNTHETIC_V_PROBE_NOT_G_APPROVAL': True}
        save(cls.dir / 'review.json', review)
        cls.review = review
        grant = draft_grant.draft(cls.root, 229, cls.dir / 'review.json')
        grant.update(state='admitted', SYNTHETIC_TEST_NOT_NATIVE_PERMISSION=True)
        cls.grant = grant
        save(cls.dir / 'dispatch.json', {'native_slot': {'owner': OWNER, 'sequence': 229}})
        cls.n = 0

    def check(self, grant, *, plan=None, root=None, dispatch=True, save_review=None):
        from prepare import save
        type(self).n += 1
        path = self.dir / ('grant-%02d.json' % self.n)
        save(path, grant)
        with ExitStack() as stack:
            stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('NO processes')))
            if dispatch:
                stack.enter_context(patch.object(self.admission, 'DISPATCH', self.dir / 'dispatch.json'))
            return self.admission.check(plan or self.PREPARED / 'predeclared.json', path, H.sha(path), root or self.root, require_host=False)

    REASONS = {}

    def refuse(self, name, grant, needle=None, **kw):
        with self.assertRaises((ValueError, KeyError, TypeError, OSError), msg=name) as caught:
            self.check(grant, **kw)
        message = '%s: %s' % (type(caught.exception).__name__, caught.exception)
        type(self).REASONS[name] = message
        if needle is not None:
            self.assertIn(needle, message, name)
        return message

    def test_positive_control(self):
        context = self.check(copy.deepcopy(self.grant))
        self.assertEqual(context['grant']['max_native_launches'], 12)

    def test_negative_matrix(self):
        base = self.grant
        cases = {}

        def repin(row, path):
            row.update(path=str(path), sha256=H.sha(path), bytes=Path(path).stat().st_size)

        def variant(name, mutate):
            g = copy.deepcopy(base)
            mutate(g)
            cases[name] = g
        variant('state_draft', lambda g: g.update(state='draft_NOT_AUTHORIZED'))
        variant('launch_cap_13', lambda g: g.update(max_native_launches=13))
        variant('launch_cap_float', lambda g: g.update(max_native_launches=12.0))
        variant('concurrency_1', lambda g: g.update(max_concurrent_native=1))
        variant('retry_true', lambda g: g.update(retry=True))
        variant('sequence_string', lambda g: g.update(lease_sequence='229'))
        variant('sequence_bool', lambda g: g.update(lease_sequence=True))
        variant('sequence_mismatch', lambda g: g.update(lease_sequence=230))
        variant('owner_substring', lambda g: g.update(owner='X-' + g['owner']))
        variant('run_root_other', lambda g: g.update(run_root=str(self.EXP / 'SHORT-CLOSE-G-native-rev04-other')))
        variant('auditor_api', lambda g: g.update(auditor_api='SHORT-CLOSE-NATIVE-V-raw-api-3'))
        variant('kernel_root_outside_install', lambda g: g.update(kernel_root=str(self.EXP)))
        variant('direct_exe_swapped', lambda g: g['executables'].update(direct=g['executables']['dimr']))
        variant('engine_file_dropped', lambda g: g.update(engine_files=[r for r in g['engine_files'] if not r['path'].endswith('gdal.dll')]))
        variant('engine_hash_wrong', lambda g: g['engine_files'][0].update(sha256='0' * 64))
        variant('extra_dependency', lambda g: g['research_dependencies'].update(extra=g['research_dependencies']['observer']))
        variant('review_not_offline', lambda g: None)
        variant('auditor_freeze_other_copy', lambda g: repin(g['auditor_freeze'], self.dir / 'review.json'))
        variant('audit_module_other_name', lambda g: repin(g['audit_module'], H.READER / 'fixtures.py'))
        variant('package_freeze_other', lambda g: repin(g['package_freeze'], H.ADAPTER / 'freeze.json'))
        (self.dir / 'contract-copy.json').write_bytes(Path(self.grant['runtime_contract']['path']).read_bytes())
        variant('contract_relocated_copy', lambda g: repin(g['runtime_contract'], self.dir / 'contract-copy.json'))
        del cases['review_not_offline']
        expected = {'state_draft': 'Explicit G admission', 'launch_cap_13': 'Bound/retry', 'launch_cap_float': 'Bound/retry',
                    'concurrency_1': 'Bound/retry', 'retry_true': 'Bound/retry', 'sequence_string': 'fresh lease',
                    'sequence_bool': 'fresh lease', 'sequence_mismatch': 'fresh lease', 'owner_substring': 'Exact coordinator',
                    'run_root_other': 'fresh output directory', 'auditor_api': 'Unknown independent audit API',
                    'kernel_root_outside_install': 'kernels outside', 'direct_exe_swapped': 'Wrong native engines',
                    'engine_file_dropped': 'missing from pins', 'engine_hash_wrong': 'hash mismatch',
                    'extra_dependency': 'Only pinned observer', 'auditor_freeze_other_copy': 'Independent frozen auditor binding differs',
                    'audit_module_other_name': 'Independent frozen auditor binding differs',
                    'package_freeze_other': 'Only exact compatibility package freeze', 'contract_relocated_copy': 'Runtime contract/package binding differs'}
        for name, grant in cases.items():
            with self.subTest(name):
                self.refuse(name, grant, expected.get(name))
        self.assertEqual(set(expected) - set(cases), set())
        # composition review binding variants
        from prepare import save
        for name, patch_review in {'review_state_admitted': {'state': 'admitted'}, 'review_native_true': {'native_authorized': True},
                                   'review_wrong_reader': {'reader_freeze_sha256': '0' * 64},
                                   'review_wrong_adapter': {'adapter_freeze_sha256': '0' * 64},
                                   'review_wrong_plan': {'predeclared_sha256': '0' * 64}, 'review_wrong_wheel': {'wheel_sha256': '0' * 64}}.items():
            with self.subTest(name):
                review = {**self.review, **patch_review}
                path = self.dir / (name + '.json')
                save(path, review)
                g = copy.deepcopy(base)
                g['composition_review'] = {'path': str(path), 'sha256': H.sha(path), 'bytes': path.stat().st_size}
                self.refuse(name, g)

    @requirement('F7', 'Observer and comparator roles must use the exact canonical pinned source paths (a swap or a byte-identical copy elsewhere is refused)')
    def test_f7_exact_canonical_role_paths(self):
        swapped = copy.deepcopy(self.grant)
        deps = swapped['research_dependencies']
        deps['observer'], deps['raw_output_reader'] = deps['raw_output_reader'], deps['observer']
        self.refuse('roles_swapped', swapped, 'canonical pinned source paths')
        copied = copy.deepcopy(self.grant)
        clone = self.dir / 'observer-byte-identical-copy.py'
        clone.write_bytes(H.OBSERVER_SOURCE.read_bytes())
        copied['research_dependencies']['observer'].update(path=str(clone), sha256=H.sha(clone), bytes=clone.stat().st_size)
        self.refuse('observer_byte_identical_copy', copied, 'canonical pinned source paths')
        self.assertEqual(self.check(copy.deepcopy(self.grant))['dependencies']['observer'], H.OBSERVER_SOURCE.resolve())

    def test_foreign_plan_and_output_locations(self):
        exp = self.EXP / 'SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01'
        with self.subTest('prepared-01'):
            self.refuse('prepared-01', copy.deepcopy(self.grant), 'Plan does not join exact adapter freeze', plan=exp / 'prepared-01/predeclared.json')
        with self.subTest('output prefix'):
            self.refuse('prefix', copy.deepcopy(self.grant), 'fresh direct approved experiment child', root=self.EXP / 'SHORT-CLOSE-G-native-rev03-x')
        with self.subTest('output nested'):
            self.refuse('nested', copy.deepcopy(self.grant), 'fresh direct approved experiment child', root=self.root / 'child')
        with self.subTest('existing output'):
            self.root.mkdir()
            try:
                self.refuse('exists', copy.deepcopy(self.grant), 'Destination must be absent')
            finally:
                self.root.rmdir()
        with self.subTest('idle canonical dispatch'):
            self.refuse('idle', copy.deepcopy(self.grant), 'Exact coordinator native owner required', dispatch=False)
        self.assertEqual(H.sha(H.REPO / 'research/experiments/roadmap-coordinator-20261104/dispatch.json'), CANONICAL_DISPATCH)

    def test_recheck_start_detects_drift_in_each_gate_it_claims(self):
        context = self.check(copy.deepcopy(self.grant))
        self.root.mkdir()
        try:
            with patch.object(self.admission, 'DISPATCH', self.dir / 'dispatch.json'):
                self.admission.recheck_start(context)
                for name, target in (('lease', 'DISPATCH'),):
                    pass
                from prepare import save
                save(self.dir / 'dispatch-other.json', {'native_slot': {'owner': 'idle', 'sequence': 228}})
                with patch.object(self.admission, 'DISPATCH', self.dir / 'dispatch-other.json'):
                    with self.assertRaises(ValueError):
                        self.admission.recheck_start(context)  # lease revoked between warm-up and go
            # a pinned research dependency drifting after check() must be refused at the next start
            drift = copy.deepcopy(context)
            drift['grant'] = copy.deepcopy(context['grant'])
            drift['grant']['research_dependencies']['observer']['sha256'] = '0' * 64
            with patch.object(self.admission, 'DISPATCH', self.dir / 'dispatch.json'):
                with self.assertRaises(ValueError):
                    self.admission.recheck_start(drift)
        finally:
            self.root.rmdir()

    def test_info_pins_only_five_of_134_kernel_binaries(self):
        kernels = Path(self.grant['kernel_root'])
        binaries = [p for sub in ('bin', 'lib') for p in (kernels / sub).iterdir() if p.suffix.lower() in ('.dll', '.exe')]
        pinned = {str(Path(r['path']).resolve()) for r in self.grant['engine_files']}
        self.assertEqual((len(binaries), len(pinned)), (134, 5))
        self.assertLess(len(pinned), len(binaries))


# ---------------------------------------------------------------------------
# E. static boundary audit and bounds
# ---------------------------------------------------------------------------
class E_Static(unittest.TestCase):
    def test_no_native_kill_job_or_ffi_in_adapter_sources(self):
        banned_attrs = {'kill', 'terminate', 'TerminateProcess', 'TerminateJobObject', 'CreateJobObjectW', 'AssignProcessToJobObject',
                        'SuspendThread', 'ResumeThread', 'system', 'startfile', 'killpg'}
        popen_sites = []
        for path in sorted(H.ADAPTER.glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in banned_attrs and path.name not in ('test_portable.py',):
                    self.fail('%s:%d uses %s' % (path.name, node.lineno, node.attr))
                if isinstance(node, ast.Attribute) and node.attr == 'Popen':
                    popen_sites.append(path.name)
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in node.names] + [getattr(node, 'module', None) or '']
                    if any(n.split('.')[0] in ('dfm_cli', 'win32api', 'win32process', 'psutil') for n in names) and path.name not in ('warm_client.py',):
                        self.fail('%s imports product/process library %s' % (path.name, names))
                if isinstance(node, ast.Attribute) and node.attr in ('WinDLL', 'CDLL', 'windll', 'cdll') and path.name not in (
                        'test_flow.py', 'test_portable.py', 'run_checks.py', 'check_admission.py', 'check_composition.py'):
                    self.fail('%s:%d loads a foreign library' % (path.name, node.lineno))
        self.assertEqual(sorted(set(popen_sites)), ['public_driver.py'])  # the only subprocess creation site is the fixed warm-client trampoline

    def test_observer_source_uses_read_only_access_mask(self):
        source = H.OBSERVER_SOURCE.read_text(encoding='utf-8')
        self.assertIn('OpenProcess(0x1000 | 0x100000, False, pid)', source)
        self.assertEqual(0x1000 | 0x100000, 0x101000)
        for forbidden, name in ((0x0001, 'TERMINATE'), (0x0002, 'CREATE_THREAD'), (0x0800, 'SUSPEND_RESUME'), (0x0200, 'SET_QUOTA'), (0x0100, 'SET_INFORMATION')):
            self.assertEqual(0x101000 & forbidden, 0, name)
        self.assertNotRegex(source, r'Terminate|SuspendThread|ResumeThread|AssignProcessToJobObject|CreateJobObject')

    def test_warm_client_is_only_a_public_cli_trampoline(self):
        source = (H.ADAPTER / 'warm_client.py').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'^\s*(?:import|from)\s+(\S+)', source, re.M),
                         ['argparse', 'hashlib', 'json', 'pathlib', 'sys', 'dfm_cli', 'dfm_cli.cli'])
        self.assertIn("if sys.stdin.readline()!='go\\n':return 2", source)
        self.assertIn('return public_cli(arguments)', source)

    def test_info_bound_stages_sum(self):
        bounds = json.loads((H.REPO / 'research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01/prepared-02/predeclared.json').read_bytes())['bounds']
        per_owner = (bounds['disposal_request_warm_seconds'] + bounds['disposal_request_result_seconds'] +
                     bounds['disposal_owner_terminal_wait_seconds'] + bounds['disposal_request_result_seconds'])
        self.assertEqual(per_owner, 170)
        self.assertEqual(3 * per_owner + 3 * bounds['final_started_client_wait_seconds'], 840)  # worst-case sequential pair disposal; no total is claimed


# ---------------------------------------------------------------------------
class Result(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.rows.append({'test': subtest.id().split('.', 1)[-1], 'outcome': 'FAIL', 'detail': self._exc_info_to_string(err, test)[-1500:]})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({'test': test.id().split('.', 1)[-1], 'outcome': 'pass'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({'test': test.id().split('.', 1)[-1], 'outcome': 'FAIL', 'detail': self._exc_info_to_string(err, test)[-1500:]})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({'test': test.id().split('.', 1)[-1], 'outcome': 'ERROR', 'detail': self._exc_info_to_string(err, test)[-1500:]})


def main(argv=None):
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    OUT = args.out.resolve()
    experiments = (H.REPO / 'research/experiments').resolve()
    if OUT.parent.parent != experiments or not OUT.parent.name.startswith('SHORT-CLOSE-NATIVE-ADAPTER-FINAL-V-'):
        print('output must be research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-FINAL-V-*/<fresh child>', file=sys.stderr)
        return 2
    OUT.mkdir(parents=True)  # FileExistsError if reused
    (OUT / 'work').mkdir()
    watched = [H.ADAPTER / 'freeze.json', H.READER / 'freeze.json', H.REPO / 'research/experiments/roadmap-coordinator-20261104/dispatch.json']
    before = {str(p): H.sha(p) for p in [*H.ADAPTER.glob('*'), *H.READER.glob('*'), *watched, *H.HISTORY.glob('*/manifest.json')] if p.is_file()}
    log = io.StringIO()
    with ExitStack() as stack:
        blocked = []

        def forbidden(*a, **k):
            blocked.append('real process/FFI boundary')
            raise AssertionError('boundary')
        # outermost guards: tests replace these with scripted fakes inside their own patch scope
        stack.enter_context(patch('subprocess.Popen', side_effect=forbidden))
        import ctypes
        stack.enter_context(patch.object(ctypes, 'WinDLL', create=True, side_effect=forbidden))
        stack.enter_context(patch.object(ctypes, 'CDLL', create=True, side_effect=forbidden))
        suite = unittest.TestSuite()
        for cls in (A_Hashes, B_Composition, C_Disposal, F_WarmClientAndGates, D_Admission, E_Static):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
        runner = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=Result)
        result = runner.run(suite)
    after = {k: H.sha(Path(k)) for k in before}
    (OUT / 'tests.log').write_text(log.getvalue(), encoding='utf-8')
    satisfied = {name: {**info, 'satisfied': next((r['outcome'] == 'pass' for r in result.rows if r['test'].endswith(name)), False)}
                 for name, info in REGISTRY.items()}
    report = {'node': 'NATIVE-ADAPTER-FINAL-V', 'adapter_freeze_sha256': ADAPTER_FREEZE, 'reader_freeze_sha256': READER_FREEZE,
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
              'blocked_real_boundary_attempts': blocked, 'native_launches': 0,
              'inputs_unchanged': before == after, 'tracked_hashes': before,
              'requirements': satisfied, 'admission_refusal_reasons': D_Admission.REASONS, 'rows': result.rows,
              'scope': 'Offline: real adapter classes + pinned observer class + frozen reader on scripted fake CLI/kernel32; synthetic metadata only.'}
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('tests', 'failures', 'errors', 'skips', 'inputs_unchanged', 'native_launches')}))
    for row in result.rows:
        if row['outcome'] != 'pass':
            print(row['test'], row['outcome'], '\n', row['detail'])
    return 0 if result.wasSuccessful() and before == after and not blocked else 1


if __name__ == '__main__':
    raise SystemExit(main())
