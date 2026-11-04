"""Independent E013 saved-output/precision oracle; never launches an engine."""
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification import verify_restart_diagnostics as oracle
from research.workflows.verification import verify_restart_diagnostics_cli as public_gate


AVAILABLE = importlib.util.find_spec('netCDF4') and importlib.util.find_spec('numpy')
POLICY = {'per_variable_rules': {'waterlevel': 'level'},
          'tolerances': {'exact': {'rtol': 0, 'atol': 0},
                         'level': {'rtol': 1e-6, 'atol': 2e-6}}}


def fixtures(root):
    """Small independently specified arrays, explicitly NOT native evidence."""
    from netCDF4 import Dataset
    paths = [root / (name + '.nc') for name in ('continuous', 'first', 'resumed')]
    for path, times, levels, stress, bounds, counter in zip(
            paths, ([0, 10, 20], [0, 10], [10, 20]),
            ([[0, 0], [.1, .2], [.3, .4]], [[0, 0], [.1, .2]], [[.1, .2], [.3, .4]]),
            ([.1, .2, .3], [.1, .2], [0, .3]),
            ([[0, 0], [0, 10], [10, 20]], [[0, 0], [0, 10]], [[10, 10], [10, 20]]),
            ([0, 10, 15], [0, 10], [0, 5])):
        with Dataset(path, 'w') as ds:
            ds.createDimension('time', len(times)); ds.createDimension('cell', 2); ds.createDimension('bounds', 2)
            t = ds.createVariable('time', 'f8', ('time',))
            t.standard_name = 'time'; t.units = oracle.EPOCH; t.calendar = 'standard'; t[:] = times
            x = ds.createVariable('x', 'f8', ('cell',)); x.units = 'm'; x[:] = [5, 15]
            for name, dims, values, units in (
                    ('waterlevel', ('time', 'cell'), levels, 'm'),
                    ('tausx', ('time',), stress, 'N m-2'),
                    ('time_bds', ('time', 'bounds'), bounds, oracle.EPOCH),
                    ('water_balance_storage', ('time',), counter, 'm3'),
                    ('unrecognized_diagnostic', ('time',), [7] * len(times), '1')):
                v = ds.createVariable(name, 'f4' if name == 'water_balance_storage' else 'f8', dims, fill_value=-9999)
                v.units = units; v[:] = values
                if name == 'time_bds': v.standard_name = 'time'
    return paths


@unittest.skipUnless(AVAILABLE, 'Optional run dependencies required')
class PrecisionOracle(unittest.TestCase):
    def test_asymmetric_binary32_cells_and_even_endpoints(self):
        import numpy as np
        lo, hi, lc, hc = oracle.rounding_cell(1, 'f4')
        self.assertEqual(lo, 1 - Fraction(1, 2**25))
        self.assertEqual(hi, 1 + Fraction(1, 2**24))
        self.assertTrue(lc and hc)
        odd = np.nextafter(np.float32(1), np.float32('inf'))
        self.assertEqual(oracle.rounding_cell(odd, 'f4')[2:], (False, False))

    def test_open_singleton_intersection_is_empty(self):
        self.assertFalse(oracle.nonempty(oracle.intersect((0, 1, True, False), (1, 2, True, True))))
        self.assertTrue(oracle.nonempty((1, 1, True, True)))

    def test_exact_counter_reset_with_nonzero_initial_is_explicit(self):
        import numpy as np
        r = oracle.precision_compatibility(np.array([10, 15, 19], 'f4'), np.array([2, 7, 11], 'f4'))
        self.assertTrue(r['interval_reset_exact'])
        self.assertTrue(r['consistent_with_one_shared_origin_and_stored_precision'])
        self.assertFalse(r['native_equality_proven'])
        self.assertFalse(r['acceptance_tolerances_changed'])

    def test_storage_compatibility_cannot_turn_exact_residual_into_pass(self):
        import numpy as np
        r = oracle.precision_compatibility(np.array([1e8, 1e8], 'f4'), np.array([0, 3], 'f4'))
        self.assertTrue(r['consistent_with_one_shared_origin_and_stored_precision'])
        self.assertFalse(r['interval_reset_exact'])
        self.assertEqual(r['interval_reset_max_abs_residual'], 3)

    def test_one_global_origin_not_independent_row_fits(self):
        import numpy as np
        a = np.array([1, .5, np.nextafter(np.float32(.75), np.float32('inf'))], 'f4')
        b = np.array([0, np.nextafter(np.float32(-.5), np.float32('inf')), -.25], 'f4')
        cells = [oracle.difference_interval(oracle.rounding_cell(x, 'f4'), oracle.rounding_cell(y, 'f4')) for x, y in zip(a, b)]
        self.assertTrue(all(oracle.nonempty(oracle.intersect(cells[0], cell)) for cell in cells))
        self.assertFalse(oracle.precision_compatibility(a, b)['consistent_with_one_shared_origin_and_stored_precision'])

    def test_changed_increment_cannot_be_explained_by_rounding(self):
        import numpy as np
        r = oracle.precision_compatibility(np.array([10, 15, 19], 'f4'), np.array([0, 5, 10], 'f4'))
        self.assertFalse(r['consistent_with_one_shared_origin_and_stored_precision'])

    def test_nonfinite_different_dtype_and_shape_refused(self):
        import numpy as np
        for a, b in (([0, float('nan')], [0, 1]), ([0, float('inf')], [0, 1])):
            with self.assertRaises(AssertionError): oracle.precision_compatibility(np.array(a), np.array(b, dtype='f8'))
        with self.assertRaises(AssertionError): oracle.precision_compatibility(np.array([0, 1], 'f4'), np.array([0, 1], 'f8'))
        with self.assertRaises(AssertionError): oracle.precision_compatibility(np.array([0.]), np.array([0.]))

    def test_masks_are_exact_and_signed_zero_bytes_are_reported(self):
        import numpy as np
        self.assertFalse(oracle.compare(np.ma.array([1., 2.], mask=[0, 1]), [1., 2.])['passed'])
        r = oracle.compare(np.array([0.]), np.array([-0.]))
        self.assertTrue(r['stored_value_exact']); self.assertFalse(r['unmasked_bytes_equal'])


@unittest.skipUnless(AVAILABLE, 'Optional run dependencies required')
class SavedTraceOracle(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='e013-v-diagnostics-')
        self.addCleanup(temp.cleanup); self.paths = fixtures(Path(temp.name))

    def mutate(self, field, index, value):
        from netCDF4 import Dataset
        with Dataset(self.paths[2], 'r+') as ds: ds[field][index] = value

    def report(self): return oracle.trace(self.paths, POLICY)

    def test_raw_failure_kept_separate_from_saved_forecast(self):
        r = self.report()
        self.assertEqual(set(r['raw_failed_fields']), {'tausx', 'time_bds', 'water_balance_storage'})
        self.assertTrue(r['forecast_samples_passed']); self.assertTrue(r['forecast_samples_exact'])
        self.assertTrue(r['initial_cut_non_counter_passed'])
        self.assertEqual(r['seconds'], [0, 10, 20])

    def test_advanced_physical_perturbation_fails(self):
        self.mutate('waterlevel', (1, 0), .31)
        self.assertFalse(self.report()['forecast_samples_passed'])

    def test_tiny_advanced_change_is_detected_even_inside_old_tolerance(self):
        self.mutate('waterlevel', (1, 0), .30000001)
        r = self.report()
        self.assertTrue(r['forecast_samples_passed'])
        self.assertFalse(r['forecast_samples_exact'])

    def test_initial_cut_state_is_not_a_blanket_exception(self):
        self.mutate('waterlevel', (0, 0), .12)
        r = self.report(); self.assertTrue(r['forecast_samples_passed'])
        self.assertFalse(r['initial_cut_non_counter_passed'])

    def test_initial_exception_does_not_exclude_advanced_diagnostic(self):
        self.mutate('tausx', 1, .31)
        self.assertFalse(self.report()['forecast_samples_passed'])

    def test_initial_diagnostic_masks_and_counter_prefix_are_still_guarded(self):
        from netCDF4 import Dataset
        import numpy as np
        self.mutate('tausx', 0, np.ma.masked)
        self.assertFalse(self.report()['cut_masks_equal'])
        with Dataset(self.paths[1], 'r+') as ds: ds['water_balance_storage'][0] = 1
        self.assertFalse(self.report()['first_segment_stored_value_exact'])

    def test_all_checkpoint_fields_exact_even_for_tiny_and_unknown_changes(self):
        from netCDF4 import Dataset
        a, b = self.paths[1:]
        # Reuse files with matching time axes; this exercises the separate
        # all-variable state comparator without claiming these are native states.
        b.write_bytes(a.read_bytes())
        self.assertTrue(oracle.checkpoint_pair(a, b, POLICY)['stored_values_exact'])
        with Dataset(b, 'r+') as ds: ds['waterlevel'][1, 0] += 1e-8
        r = oracle.checkpoint_pair(a, b, POLICY)
        self.assertTrue(r['passed']); self.assertFalse(r['stored_values_exact'])
        with Dataset(b, 'r+') as ds: ds['unrecognized_diagnostic'][1] = 8
        self.assertFalse(oracle.checkpoint_pair(a, b, POLICY)['passed'])

    def test_interval_bounds_after_cut_must_be_exact(self):
        self.mutate('time_bds', (1, 0), 9)
        self.assertFalse(self.report()['forecast_samples_passed'])

    def test_unknown_field_not_silently_classified_or_dropped(self):
        self.mutate('unrecognized_diagnostic', 1, 8)
        self.assertFalse(self.report()['forecast_samples_passed'])

    def test_similar_counter_prefix_does_not_acquire_exception(self):
        from netCDF4 import Dataset
        for i, path in enumerate(self.paths):
            with Dataset(path, 'r+') as ds:
                v = ds.createVariable('water_balance_future_counter', 'f4', ('time',)); v.units = 'm3'
                v[:] = 7 if i != 2 else 8
        r = self.report()
        self.assertEqual(r['variables']['water_balance_future_counter']['classification'], 'forecast_or_instantaneous_field')
        self.assertFalse(r['forecast_samples_passed'])

    def test_exceptions_are_dataset_bound(self):
        r = oracle.trace(self.paths, POLICY, kind='map')
        self.assertEqual(r['variables']['tausx']['classification'], 'forecast_or_instantaneous_field')
        self.assertEqual(r['variables']['water_balance_storage']['classification'], 'forecast_or_instantaneous_field')
        self.assertFalse(r['initial_cut_non_counter_exact'])

    def test_masks_cannot_be_tolerated(self):
        import numpy as np
        self.mutate('waterlevel', (1, 0), np.ma.masked)
        self.assertFalse(self.report()['forecast_samples_passed'])

    def test_units_and_missing_fields_are_schema_errors(self):
        from netCDF4 import Dataset
        with Dataset(self.paths[2], 'r+') as ds: ds['waterlevel'].units = 'cm'
        with self.assertRaisesRegex(AssertionError, 'semantics'): self.report()

    def test_static_identity_advanced_clock_and_inventory_must_match(self):
        self.mutate('x', 0, 5.01)
        self.assertFalse(self.report()['forecast_samples_passed'])
        self.mutate('time', 1, 21)
        with self.assertRaisesRegex(AssertionError, 'partition'): self.report()

    def test_extra_field_is_not_intersection_compared(self):
        from netCDF4 import Dataset
        with Dataset(self.paths[2], 'r+') as ds: ds.createVariable('surprise', 'f8', ('time',))[:] = 1
        with self.assertRaisesRegex(AssertionError, 'omission'): self.report()


TRIAL = oracle.ROOT / 'research/experiments/E013-restart-native-20261104-01'


@unittest.skipUnless(AVAILABLE and (TRIAL / 'runs/cold-tail/manifest.json').is_file(),
                     'Local retained native archives required; no engine is launched')
class RetainedPublicForecast(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='e013-v-public-diagnostics-')
        self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.cli = public_gate.PublicCLI(self.root / 'commands')

    def test_frozen_public_raw_comparator_keeps_exit_six(self):
        before = oracle.fingerprints(TRIAL)
        result = public_gate.raw_gate(self.cli, TRIAL, oracle.investigate(TRIAL))
        self.assertEqual(result['returncode'], 6)
        self.assertEqual(oracle.fingerprints(TRIAL), before)

    def test_public_forecast_retained_hot_cold_and_predeclared_perturbations(self):
        code, schema = self.cli.invoke('schema', 'inspect')
        self.assertEqual(code, 0)
        if 'restart forecast' not in schema['commands']:
            self.skipTest('Parent has not registered public restart forecast yet')
        gate_root = self.root / 'gate'; gate_root.mkdir()
        result = public_gate.exercise([TRIAL], gate_root)
        self.assertEqual(result['status'], 'passed_archived_public_saved_forecast_and_negative_gate', result['failures'])
        self.assertTrue(result['retained_trials_unchanged'])
        self.assertEqual(len(result['trials'][0]['negative_fixtures']), len(public_gate.CASES))


if __name__ == '__main__': unittest.main()
