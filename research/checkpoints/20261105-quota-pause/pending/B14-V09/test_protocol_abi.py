"""Independent authored raw protocol and fake ABI controls; no native process."""
import copy
import ctypes
import json
import shutil
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import test_admission as a


def stream(case, epoch, digest, selected, value_at=lambda t: .125):
    def clock(t): return {'start': 0., 'stop': 120., 'current': t, 'dt_user': 1., 'unit': 's'}
    def frame(event, **extra):
        return {'event': event, 'b14_astro_protocol': 1, 'case_id': case, 'epoch_utc': epoch,
                'plan_sha256': digest, **extra}
    def snapshot(label, count, time):
        fields = {name: {'variable': name, 'rank': 1, 'type': 'double', 'shape': [n],
                        'shape_buffer': [n, 0, 0, 0, 0, 0], 'unit': 'm', 'ordering': 'native unlabelled',
                        'values': [value_at(time) if name == 'zbndz' else .1] * n}
                  for name, n in [('zbndz', 8), ('s1', 56)]}
        return frame('snapshot', label=label, updates_attempted=count, clock_before=clock(time), clock_after=clock(time), fields=fields)
    rows = [frame('ready', worker_pid=77, native_dll_loaded=False), frame('initialized', clock=clock(0.), native_returncode=0)]
    rows += [snapshot(label, 0, 0.) for label in ('read0a', 'read0b', 'read0c')]
    for i in range(1, 9):
        before = (i - 1) / 4; after = i / 4
        rows.append(frame('update', index=i, native_returncode=0, requested_delta_s=.125,
                          requested_target_s=before + .125, clock_before=clock(before), clock_after=clock(after)))
        rows.append(snapshot('after_update_' + str(i), i, after))
    rows.append(frame('finalized', native_returncode=0, clock_before_finalize=clock(2.), completion='partial diagnostic slice, not 120s completion'))
    result = {'state': 'diagnostic_sampled_partial', 'b14_astro_protocol': 1, 'case_id': case, 'epoch_utc': epoch,
              'plan_sha256': digest, 'worker_pid': 77, 'initialize_attempts': 1, 'finalize_attempts': 1, 'finalized': True,
              'initialize_native_returncode': 0, 'finalize_native_returncode': 0,
              'initial_clock': clock(0.), 'final_clock': clock(2.), 'snapshots': [r for r in rows if r['event'] == 'snapshot'],
              'updates': [r for r in rows if r['event'] == 'update'],
              'dll_binding': {**selected, 'actual_loaded_module_path_confirmed': True}}
    return rows, result


class ProtocolABI(unittest.TestCase):
    setUp = a.Full.setUp
    tearDown = a.Full.tearDown

    def protocol(self):
        plan = {'case_id': self.r.a.BMI[0], 'epoch_utc': '2001-01-01T00:00:00Z',
                'installation': {'binaries': {'lib/dflowfm.dll': {'path': 'SYNTHETIC_ONLY', 'sha256': 'a' * 64}}}}
        rows, result = stream(plan['case_id'], plan['epoch_utc'], 'b' * 64, plan['installation']['binaries']['lib/dflowfm.dll'])
        return rows, result, plan

    def test_authored22frames_actual_clock_and_metadata_pass(self):
        rows, result, plan = self.protocol()
        self.assertTrue(self.r.p.validate(rows, result, plan, 'b' * 64, 77)['passed'])
        self.assertEqual(rows[5]['requested_target_s'], .125); self.assertEqual(rows[5]['clock_after']['current'], .25)

    def test_protocol_case_epoch_pid_digest_shape_type_codes_and_summary_refuse(self):
        for mode in ('case', 'epoch', 'pid', 'digest', 'missing', 'extra', 'bool_code', 'failed_finalize',
                     'target', 'actual', 'shape', 'rank', 'mask', 'nan', 'dll', 'summary', 'startup'):
            with self.subTest(mode=mode):
                rows, result, plan = self.protocol()
                if mode == 'case': rows[0]['case_id'] = self.r.a.BMI[2]
                if mode == 'epoch': rows[0]['epoch_utc'] = '2026-01-01T00:00:00Z'
                if mode == 'pid': rows[0]['worker_pid'] = 78
                if mode == 'digest': rows[0]['plan_sha256'] = 'c' * 64
                if mode == 'missing': rows.pop()
                if mode == 'extra': rows.append(copy.deepcopy(rows[-1]))
                if mode == 'bool_code': rows[1]['native_returncode'] = False
                if mode == 'failed_finalize': rows[-1]['native_returncode'] = 9
                if mode == 'target': rows[5]['requested_target_s'] = .25
                if mode == 'actual': rows[5]['clock_after']['current'] = 0.
                if mode == 'shape': rows[2]['fields']['zbndz']['shape'] = [7]
                if mode == 'rank': rows[2]['fields']['zbndz']['rank'] = True
                if mode == 'mask': rows[2]['fields']['s1']['mask'] = [True] * 56
                if mode == 'nan': rows[2]['fields']['zbndz']['values'][7] = float('nan')
                if mode == 'dll': result['dll_binding']['sha256'] = 'c' * 64
                if mode == 'summary': result['snapshots'] = []
                if mode == 'startup': rows[3]['fields']['zbndz']['values'][0] += .01
                with self.assertRaises((ValueError, KeyError)): self.r.p.validate(rows, result, plan, 'b' * 64, 77)

    def test_update_actual_argument_is_byvalue_double_point125_no_update_until(self):
        calls = []; reader = object.__new__(self.r.worker.Reader); reader.gate = lambda: None
        reader.dll = SimpleNamespace(update=lambda value: calls.append(value) or 0)
        self.assertEqual(reader.update(), 0); self.assertIs(type(calls[0]), ctypes.c_double); self.assertEqual(calls[0].value, .125)
        self.assertNotIn('update_until', (a.I / 'worker.py').read_text())

    def test_real_array_wrapper_detaches_bounded_buffer(self):
        data = (ctypes.c_double * 8)(*range(8))
        def rank(name, p): ctypes.cast(p, ctypes.POINTER(ctypes.c_int))[0] = 1
        def shape(name, p):
            for i, n in enumerate([8, 0, 0, 0, 0, 0]): p[i] = n
        def kind(name, p): ctypes.memmove(p, b'double\0', 7)
        def pointer(name, p): ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(data)
        fields = self.r.worker.array(SimpleNamespace(get_var_rank=rank, get_var_shape=shape, get_var_type=kind, get_var=pointer), b'zbndz', 8)
        data[0] = 900.
        self.assertEqual(fields['values'], [float(i) for i in range(8)])
        self.assertNotIn('address', fields)

    def test_wrong_metadata_or_null_never_read_pointer(self):
        def rank(name, p): ctypes.cast(p, ctypes.POINTER(ctypes.c_int))[0] = 2
        fake = SimpleNamespace(get_var_rank=rank, get_var_shape=lambda *a: None, get_var_type=lambda *a: None)
        with patch.object(self.r.worker.c, 'string_at', side_effect=AssertionError('unbounded pointer access')) as read:
            with self.assertRaises(ValueError): self.r.worker.array(fake, b'zbndz', 8)
            self.assertEqual(read.call_count, 0)
        for name, n in ((b'other', 8), (b'zbndz', 9), (b's1', 8)):
            with self.assertRaises(ValueError): self.r.worker.array(None, name, n)

    def test_frozen_science_consumer_threshold_and_all_four_handoff(self):
        science = self.r.consumer({}); contract = science.c.authority(); index = {'schema': 'B14-BMI-raw-index-1', 'contract_sha256': self.r.a.CONTRACT, 'cases': {}}
        for case in self.r.a.BMI:
            folder = self.tmp / case; folder.mkdir(); expected = contract['input_bindings']['uniform_BMI_cases'][case]
            model = folder / 'model'; shutil.copytree(a.PREPARED / 'cases' / case, model)
            plan = {'case_id': case, 'epoch_utc': expected['epoch_utc'], 'model': str(model), 'contract_sha256': self.r.a.CONTRACT,
                    'inputs': self.r.a.graph(model, expected['input_files'])}
            path = folder / 'worker-plan.json'; self.r.save(path, plan, fresh=True); digest = self.r.sha(path)
            # Science V owns this exact frozen oracle; use its H_current only
            # for synthetic handoff plumbing, never as an independent physics claim.
            rows, result = stream(case, expected['epoch_utc'], digest, {}, lambda t: science.expected(expected, t)[0])
            samples = folder / 'samples.jsonl'; samples.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            final = folder / 'result.json'; self.r.save(final, result, fresh=True)
            report = science.consume(path, digest, samples, final)
            self.assertEqual(report['state'], 'passed_data_only'); self.assertIs(report['native_ownership_qualified'], False)
            self.assertEqual(report['atol_m'], 1e-8); self.assertEqual(report['rtol'], 0)
            index['cases'][case] = {k: self.r.record(p) for k, p in [('plan', path), ('samples', samples), ('result', final)]}
        ip = self.tmp / 'index.json'; self.r.save(ip, index, fresh=True)
        report = science.consume_suite(ip); self.assertEqual(report['state'], 'passed_data_only')
        # A numerically wrong support must not be hidden by any epoch/clock
        # choice, nor by updating the summary to agree with the bad raw stream.
        case = self.r.a.BMI[-1]; row = index['cases'][case]; samples = self.tmp / case / 'samples.jsonl'; final = self.tmp / case / 'result.json'
        rows = [json.loads(line) for line in samples.read_text().splitlines()]; result = self.r.load(final)
        rows[-2]['fields']['zbndz']['values'][7] += .001
        result['snapshots'][-1] = rows[-2]
        samples.write_text(''.join(json.dumps(r) + '\n' for r in rows)); self.r.save(final, result)
        bad = science.consume(self.tmp / case / 'worker-plan.json', row['plan']['sha256'], samples, final)
        self.assertEqual(bad['state'], 'failed_scientific_hypotheses')


if __name__ == '__main__':
    unittest.main(verbosity=2)
