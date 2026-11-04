"""Independent RR native-oracle tests. Synthetic arrays never native evidence."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification import verify_rr_f152_native as oracle

AVAILABLE = importlib.util.find_spec('numpy') and importlib.util.find_spec('netCDF4')
SOURCE = oracle.ROOT / 'research/experiments/RR-G-f152-readiness-02/wet/fm'


def synthetic_receivers():
    import numpy as np
    level = np.array([[3.4] * 34, [3.8] * 34], 'f8'); q = np.array([[.5] * 34, [1.] * 34])
    fm = np.vstack(([0.] * 34, np.repeat(q, 5, axis=0)))
    data = {}
    for key, values, seconds in (
            ('sent_level', level, [0, 300]), ('rr_level', level.astype('f4').astype('f8'), [300, 600]),
            ('rr_flow', q, [300, 600]), ('sent_flow', q, [0, 300]),
            *[(key, fm, list(range(0, 601, 60))) for key in ('fm_prescribed', 'fm_realized', 'fm_average')]):
        data[key] = {'ids': list(oracle.IDS), 'values': values.tolist(), 'seconds': seconds}
    return data


@unittest.skipUnless(AVAILABLE, 'Optional run dependencies required')
class F152ReceiverOracle(unittest.TestCase):
    def test_all34_both_directions_and_true_following_step_phase(self):
        result = oracle.receiver_oracle(synthetic_receivers())
        self.assertEqual(result['transactions_per_direction'], 68)
        self.assertEqual(result['rr_signed_volume_m3'], 15300)
        self.assertTrue(result['rr_level_encoding_exact'])

    def test_wrong_phase_rejected_without_best_fit_lag(self):
        for name in ('sent_level', 'rr_level', 'rr_flow', 'sent_flow', 'fm_prescribed'):
            data = synthetic_receivers(); data[name]['seconds'] = [t + 60 for t in data[name]['seconds']]
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'phase'): oracle.receiver_oracle(data)

    def test_missing_or_changed_identity_not_intersection_compared(self):
        data = synthetic_receivers(); data['rr_level']['ids'][-1] = 'invented_boundary'
        with self.assertRaisesRegex(AssertionError, 'identities'): oracle.receiver_oracle(data)

    def test_signed_flow_reversal_and_row_shift_fail(self):
        data = synthetic_receivers(); data['sent_flow']['values'][0][0] *= -1
        with self.assertRaisesRegex(AssertionError, 'DIMR send'): oracle.receiver_oracle(data)
        data = synthetic_receivers(); data['fm_prescribed']['values'][5][0] = 1
        with self.assertRaisesRegex(AssertionError, 'following-step'): oracle.receiver_oracle(data)

    def test_masked_and_nonfinite_receiver_are_not_zero(self):
        import numpy as np
        for value in (None, float('nan'), float('inf')):
            data = synthetic_receivers(); data['rr_level']['values'][0][0] = value
            with self.subTest(value=value), self.assertRaises(AssertionError): oracle.receiver_oracle(data)
        with self.assertRaisesRegex(AssertionError, 'masked'):
            oracle.numeric(np.ma.array([0., 1.], mask=[0, 1]), 'test')

    def test_initial_FM_row_is_not_an_already_coupled_receiver(self):
        data = synthetic_receivers()
        for name in ('fm_prescribed', 'fm_realized', 'fm_average'): data[name]['values'][0] = [12345.] * 34
        self.assertEqual(oracle.receiver_oracle(data)['fm_realized_signed_volume_m3'], 15300)

    def test_actual_realized_volume_not_prescribed_echo(self):
        data = synthetic_receivers(); data['fm_average']['values'][-1][0] += .01
        with self.assertRaisesRegex(AssertionError, 'volume'): oracle.receiver_oracle(data)
        data = synthetic_receivers(); data['fm_realized']['values'][1][0] = 0
        with self.assertRaisesRegex(AssertionError, 'realized'): oracle.receiver_oracle(data)

    def causal(self):
        import numpy as np
        cases = {r: synthetic_receivers() for r in ('wet', 'dry', 'hydraulic')}
        for name in ('rr_flow', 'sent_flow', 'fm_prescribed', 'fm_realized', 'fm_average'):
            cases['dry'][name]['values'] = (np.array(cases['dry'][name]['values']) * .5).tolist()
        level = np.array(cases['hydraulic']['sent_level']['values']) + .01
        cases['hydraulic']['sent_level']['values'] = level.tolist()
        cases['hydraulic']['rr_level']['values'] = level.astype('f4').astype('f8').tolist()
        return {r: {'data': d, 'receivers': oracle.receiver_oracle(d)} for r, d in cases.items()}

    def test_separate_rain_consumption_and_hydraulic_receiver_causality(self):
        result = oracle.causal_comparison(self.causal())
        self.assertGreater(result['rain_consumed_FM_volume_difference_m3'], 1e-5)
        self.assertEqual(result['hydraulic_RR_Q_difference_measured_not_assumed_m3_s'], 0)

    def test_causal_effect_cannot_be_only_sender_or_only_unconsumed_runoff(self):
        runs = self.causal(); runs['hydraulic']['data']['rr_level'] = copy.deepcopy(runs['wet']['data']['rr_level'])
        with self.assertRaisesRegex(AssertionError, 'hydraulic|Hydraulic'): oracle.causal_comparison(runs)
        runs = self.causal(); runs['dry']['receivers']['fm_realized_signed_volume_m3'] = runs['wet']['receivers']['fm_realized_signed_volume_m3']
        with self.assertRaisesRegex(AssertionError, 'consumed'): oracle.causal_comparison(runs)


@unittest.skipUnless(AVAILABLE, 'Optional run dependencies required')
class F152RawNetCDF(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='rr-f152-independent-')
        self.addCleanup(temp.cleanup); self.path = Path(temp.name) / 'synthetic-boundary.nc'
        import numpy as np
        from netCDF4 import Dataset
        with Dataset(self.path, 'w') as ds:
            ds.createDimension('location', 34); ds.createDimension('char', 40); ds.createDimension('time', 3)
            ids = ds.createVariable('locations', 'S1', ('location', 'char'))
            ids[:] = np.array([list(n.upper().encode().ljust(40, b'\x00')) for n in oracle.IDS], 'u1').view('S1')
            t = ds.createVariable('time', 'i4', ('time',)); t.units = 'seconds since 2000-01-01 00:00:00 +00:00'; t[:] = [0, 300, 600]
            q = ds.createVariable('Flow', 'f8', ('location', 'time'), fill_value=-9999.)
            q.units = 'm3 s-1'; q.aggregation_option = 'current'; q[:] = np.array([[-999.99, .5, 1.]] * 34)

    def read(self):
        return oracle.nc_series(self.path, 'Flow', 'locations', list(oracle.IDS), 'm3 s-1', [0, 300, 600], rr=True)

    def test_native_dimension_order_padding_case_and_initial_sentinel_retained(self):
        r = self.read()
        self.assertEqual(r['seconds'], [300, 600]); self.assertEqual(r['native_seconds'], [0, 300, 600])
        self.assertEqual(r['values'], [[.5] * 34, [1.] * 34])
        self.assertEqual(r['initial_values_retained_separately'], [-999.99] * 34)
        self.assertEqual(r['native_ids'][0], oracle.IDS[0].upper())

    def test_completed_sentinel_and_mask_fail_no_fill(self):
        from netCDF4 import Dataset
        import numpy as np
        with Dataset(self.path, 'r+') as ds: ds['Flow'][0, 1] = -999.99
        with self.assertRaisesRegex(AssertionError, 'sentinel'): self.read()
        with Dataset(self.path, 'r+') as ds: ds['Flow'][0, 1] = np.ma.masked
        with self.assertRaisesRegex(AssertionError, 'masked'): self.read()

    def test_wrong_unit_schedule_and_average_cannot_be_receiver(self):
        from netCDF4 import Dataset
        with Dataset(self.path, 'r+') as ds: ds['Flow'].units = 'm3 per step'
        with self.assertRaisesRegex(AssertionError, 'units'): self.read()
        with Dataset(self.path, 'r+') as ds: ds['Flow'].units = 'm3 s-1'; ds['Flow'].aggregation_option = 'average'
        with self.assertRaisesRegex(AssertionError, 'current'): self.read()
        with Dataset(self.path, 'r+') as ds: ds['Flow'].aggregation_option = 'current'; ds['time'][2] = 601
        with self.assertRaisesRegex(AssertionError, 'schedule'): self.read()

    def test_missing_and_ambiguous_ID_are_not_silently_skipped(self):
        from netCDF4 import Dataset
        with Dataset(self.path, 'r+') as ds:
            ds['locations'][0] = ds['locations'][1]
        with self.assertRaisesRegex(AssertionError, 'ambiguous'): self.read()

    def test_all34_logger_columns_bound_to_exact_addresses_and_native_offsets(self):
        from netCDF4 import Dataset
        items = [{'id': n, 'source': 'laterals/' + n + '/water_level', 'target': 'catchments/' + n + '/water_level'} for n in reversed(oracle.IDS)]
        path = self.path.parent / 'synthetic-log.nc'
        with Dataset(path, 'w') as ds:
            ds.createDimension('time_offset', 2); ds.createDimension('scalar', 1)
            t = ds.createVariable('time_offset', 'f8', ('time_offset',)); t.units = 'seconds since 1980-01-01T00:00:00'
            t.long_name = 'seconds since simulation reference date, T00:00:00'; t[:] = [0, 300]
            for i, item in enumerate(items, 1):
                v = ds.createVariable(f'item{i}_values', 'f8', ('time_offset', 'scalar'))
                v.long_name = item['source'] + ' -> ' + item['target']; v[:] = [[i], [i + 100]]
        r = oracle.logger(path, items)
        self.assertEqual(r['ids'], list(oracle.IDS)); self.assertEqual(r['values'][0], list(range(34, 0, -1)))
        with Dataset(path, 'r+') as ds: ds['item1_values'].long_name = 'foreign -> receiver'
        with self.assertRaisesRegex(AssertionError, 'address'): oracle.logger(path, items)


class F152RainHeader(unittest.TestCase):
    def raw(self, marker=False):
        header = '* authored\r\n1\r\n' + ('* aantal stations\r\n' if marker else '')
        return (header + "2\r\n'A'\r\n'B'\r\n1 300\r\n2000 1 1 0 0 0 0 0 10 0\r\n10.0 10.0\r\n10.0 10.0\r\n").encode()

    def test_comment_stripping_parser_is_not_native_header_eligibility(self):
        self.assertEqual(oracle.rain_contract(self.raw()), oracle.rain_contract(self.raw(True)))
        self.assertFalse(oracle.native_rain_header(self.raw())['station_marker_ready'])
        self.assertTrue(oracle.native_rain_header(self.raw(True))['station_marker_ready'])

    def test_source_bound_marker_only_adapter_keeps_all_data_bytes(self):
        result = oracle.rain_header_only_adapter(self.raw(), self.raw(True))
        self.assertEqual(result['physical_records'], 'all non-comment records exactly unchanged')

    def test_marker_wrong_position_blank_line_and_A17_truncation_fail(self):
        for raw in (self.raw(True).replace(b'1\r\n* aantal', b'1\r\n\r\n* aantal'),
                    self.raw(True).replace(b'* aantal stations', b'* header long before aantal stations')):
            self.assertFalse(oracle.native_rain_header(raw)['station_marker_ready'])

    def test_station_time_rainfall_and_noncomment_reformat_cannot_sneak_into_adapter(self):
        for before, after in ((self.raw(), self.raw(True).replace(b"'A'", b"'X'")),
                              (self.raw(), self.raw(True).replace(b'10.0', b'11.0')),
                              (self.raw(), self.raw(True).replace(b'1 300', b'1 600')),
                              (self.raw(), self.raw(True).replace(b'10.0', b'10.00'))):
            with self.subTest(after=after), self.assertRaises(AssertionError): oracle.rain_header_only_adapter(before, after)


@unittest.skipUnless((SOURCE / 'structure.ini').is_file(), 'Local archived f152 source needed; no native run')
class ActualBridgeHeaderAudit(unittest.TestCase):
    def setUp(self):
        self.raw = (SOURCE / 'structure.ini').read_bytes(); self.cross = (SOURCE / 'cross_section_definitions.ini').read_bytes()

    def test_both_bridges_already_shift_not_bedlevel_and_all37_types_enumerated(self):
        r = oracle.structure_audit(self.raw, self.cross)
        self.assertEqual(r['type_counts'], oracle.TYPE_COUNTS); self.assertFalse(r['native_format_ready'])
        self.assertEqual(set(r['bridges']), {'RS1-KBR32', 'RS1-KBR31'})
        self.assertTrue(all(v['shift_literal'] == '0.0' and 'bedlevel' not in v['fields'] for v in r['bridges'].values()))

    def test_exact_SHA_header_only_migration_preserves_all_other_physics(self):
        after = self.raw.replace(b'fileVersion = 2.00', b'fileVersion = 3.00')
        self.assertTrue(oracle.header_only_migration(self.raw, after, self.cross, self.cross)['native_format_ready'])

    def test_invented_bedlevel_shift_changes_csdef_or_other_structure_changes_rejected(self):
        valid = self.raw.replace(b'fileVersion = 2.00', b'fileVersion = 3.00')
        for after in (valid.replace(b'shift = 0.0', b'shift = 8.0', 1), valid.replace(b'csDefId = prof_RS1-KBR32', b'csDefId = W_980.1S_0'),
                      valid.replace(b'length = 3.54', b'length = 3.55'), valid.replace(b'fileVersion = 3.00', b'fileVersion = 3.01')):
            with self.subTest(after=after[:40]), self.assertRaises(AssertionError): oracle.header_only_migration(self.raw, after, self.cross, self.cross)
        with self.assertRaises(AssertionError): oracle.header_only_migration(self.raw, valid, self.cross, self.cross + b'\n')

    def test_old_legacy_key_and_duplicate_structure_ID_refused(self):
        with self.assertRaisesRegex(AssertionError, 'Legacy'):
            oracle.structure_audit(self.raw.replace(b'\tshift = 0.0', b'\tbedLevel = 0.0', 1), self.cross)
        with self.assertRaisesRegex(AssertionError, 'unique'):
            oracle.structure_audit(self.raw.replace(b'id = RS1-KBR31', b'id = RS1-KBR32'), self.cross)


if __name__ == '__main__': unittest.main()
