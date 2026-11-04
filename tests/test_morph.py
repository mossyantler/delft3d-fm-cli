"""Independent MORPH-V raw-array and portable public-contract checks.

No product imports, native processes or product numerical comparator.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

from research.workflows.verification.verify_morph import (
    bundle_check, check_role, final_state, mass_storage_balance, public_cli, raw_map,
    release_specification, sha, specification, write_fixture, write_json,
)


@unittest.skipUnless(importlib.util.find_spec('netCDF4'), 'Optional run/NetCDF extra required')
class IndependentMorphOracle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dfm-morph-oracle-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'map.nc'
        write_fixture(self.path)

    def checked(self, **kwargs):
        return raw_map(self.path, strict_budget=True, **kwargs)

    def test_manufactured_mobile_conserves_cell_mass_with_opposite_bed_changes(self):
        report = self.checked(expected_seconds=[0, 30, 60])
        self.assertTrue(check_role(report, 'active')['passed'])
        self.assertAlmostEqual(report['bed_change_max_m'], 3.75e-5)
        self.assertEqual(report['mass_checks']['storage_change_kg'], [0., 0., 0.])
        self.assertLess(report['mass_checks']['boundary_budget']['per_cell_max_error_kg'], 1e-8)

    def test_open_boundary_actual_export_matches_decreasing_storage(self):
        write_fixture(self.path, open_boundary=True)
        report = self.checked()
        for actual, expected in zip(report['mass_checks']['storage_change_kg'], [0., -3., -6.]):
            self.assertAlmostEqual(actual, expected, places=8)
        self.assertAlmostEqual(report['mass_checks']['boundary_budget']['transferred_mass_kg'], 6.)

    def test_frozen_control_may_retain_transport_and_rest_must_not(self):
        write_fixture(self.path, 'frozen')
        report = self.checked(morfac=0)
        self.assertTrue(check_role(report, 'frozen')['passed'])
        self.assertGreater(report['transport_max_kg_s_m'], 0)
        with self.assertRaises(AssertionError): check_role(report, 'rest')
        write_fixture(self.path, 'rest')
        self.assertTrue(check_role(self.checked(), 'rest')['passed'])

    def test_nonzero_flux_without_bed_response_is_not_active_acceptance(self):
        write_fixture(self.path, 'frozen')
        report = self.checked(morfac=0)
        report['morfac'] = 1
        with self.assertRaisesRegex(AssertionError, 'active bed response'): check_role(report, 'active')

    def test_particle_density_cannot_replace_dry_bulk_density(self):
        with self.assertRaisesRegex(AssertionError, 'dry bulk density'): self.checked(dry_density=2650.)

    def test_equal_opposite_cell_errors_cannot_hide_behind_global_closure(self):
        from netCDF4 import Dataset
        with Dataset(self.path, 'r+') as ds:
            ds['mesh2d_sbn'][:] *= 2
        with self.assertRaisesRegex(AssertionError, 'mass budget does not close'): self.checked()

    def test_reversed_flux_sign_is_rejected(self):
        from netCDF4 import Dataset
        with Dataset(self.path, 'r+') as ds: ds['mesh2d_sbn'][:] *= -1
        with self.assertRaisesRegex(AssertionError, 'mass budget'): self.checked()

    def test_instantaneous_snapshots_and_unproved_orientation_do_not_prove_budget(self):
        from netCDF4 import Dataset
        for attribute in ('cell_methods', 'verification_positive_direction'):
            with self.subTest(attribute=attribute):
                write_fixture(self.path)
                with Dataset(self.path, 'r+') as ds: ds['mesh2d_sbn'].delncattr(attribute)
                report = raw_map(self.path)
                self.assertEqual(report['mass_checks']['boundary_budget']['status'], 'not_verified')
                with self.assertRaisesRegex(AssertionError, 'orientation'): self.checked()

    def test_volume_transport_wrong_bed_units_and_missing_inventory_refused(self):
        from netCDF4 import Dataset
        for name, unit in [('mesh2d_sbn', 'm3 s-1 m-1'), ('mesh2d_mor_bl', 'days'), ('mesh2d_bodsed', 'm')]:
            with self.subTest(name=name):
                write_fixture(self.path)
                with Dataset(self.path, 'r+') as ds: ds[name].units = unit
                with self.assertRaisesRegex(AssertionError, 'Unsupported units'): self.checked()
        write_fixture(self.path)
        with Dataset(self.path, 'r+') as ds: ds.renameVariable('mesh2d_bodsed', 'missing_inventory')
        with self.assertRaisesRegex(AssertionError, 'inventory is mandatory'): self.checked()

    def test_missing_or_nonfinite_bed_inventory_and_active_flux_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        for field in ('mesh2d_mor_bl', 'mesh2d_bodsed', 'mesh2d_sbn'):
            for value in (np.ma.masked, np.nan, np.inf):
                with self.subTest(field=field, value=value):
                    write_fixture(self.path)
                    with Dataset(self.path, 'r+') as ds:
                        index = (1, 1) if field == 'mesh2d_mor_bl' else (1, 1, 0)
                        ds[field][index] = value
                    with self.assertRaises(AssertionError): self.checked()

    def test_only_explicitly_inactive_transport_padding_is_accepted(self):
        from netCDF4 import Dataset
        import numpy as np
        with Dataset(self.path, 'r+') as ds:
            ds['mesh2d_sbn'][:, 2, 0] = np.ma.masked
        with self.assertRaisesRegex(AssertionError, 'Masked active transport'): self.checked()
        with Dataset(self.path, 'r+') as ds: ds['verification_active_edge'][2] = 0
        self.assertTrue(check_role(self.checked(), 'active')['passed'])

    def test_wrong_fraction_dimension_refused(self):
        from netCDF4 import Dataset
        with Dataset(self.path, 'r+') as ds:
            ds.renameVariable('mesh2d_sbn', 'original_sbn')
            ds.createDimension('two_fractions', 2)
            v = ds.createVariable('mesh2d_sbn', 'f8', ('time', 'edges', 'two_fractions'))
            v.units = 'kg s-1 m-1'; v[:] = 0
        with self.assertRaisesRegex(AssertionError, 'one bedload fraction'): self.checked()

    def test_interior_transport_cannot_be_hidden_as_inactive_padding(self):
        from netCDF4 import Dataset
        import numpy as np
        with Dataset(self.path, 'r+') as ds:
            ds['mesh2d_sbn'][:, 1, 0] = np.ma.masked
            ds['verification_active_edge'][1] = 0
            ds['verification_closed_edge'][1] = 1
        with self.assertRaisesRegex(AssertionError, 'interior/dangling'): self.checked()

    def test_direct_array_budget_does_not_discard_masks(self):
        import numpy as np
        args = ([0., 1.], [1.], np.ma.array([[1.], [1.]], mask=[[False], [True]]), [[-1.], [-1.]], 1600.)
        with self.assertRaisesRegex(AssertionError, 'Masked mass'): mass_storage_balance(*args)

    def test_clock_units_increasing_schedule_and_actual_final_time(self):
        from netCDF4 import Dataset
        self.assertEqual(self.checked()['seconds'], [0., 30., 60.])
        with self.assertRaisesRegex(AssertionError, 'schedule/final'): self.checked(expected_seconds=[0, 30, 61])
        with Dataset(self.path, 'r+') as ds: ds['time'][-1] = .5
        with self.assertRaisesRegex(AssertionError, 'increase'): self.checked()
        write_fixture(self.path)
        with Dataset(self.path, 'r+') as ds: ds['time'].units = 'seconds'
        with self.assertRaises((ValueError, AttributeError)): self.checked()

    def test_negative_available_mass_and_invalid_geometry_refused(self):
        from netCDF4 import Dataset
        for field, index, value in [('mesh2d_bodsed', (1, 0, 0), -1), ('mesh2d_flowelem_ba', 0, 0),
                                    ('mesh2d_edge_faces', (1, 1), 99), ('mesh2d_edge_length', 1, 0)]:
            with self.subTest(field=field):
                write_fixture(self.path)
                with Dataset(self.path, 'r+') as ds: ds[field][index] = value
                with self.assertRaises(AssertionError): self.checked()

    def test_budget_refuses_fractional_connectivity_nonfinite_flux_and_acceleration(self):
        args = ([0., 1.], [1.], [[1.], [1.]], [[-1.], [-1.]], 1600.)
        for kwargs in ({'morfac': 2}, {'flux': [[0.], [float('nan')]], 'edge_faces': [[0, -1]]},
                       {'flux': [[0.], [0.]], 'edge_faces': [[.5, -1]]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(AssertionError):
                mass_storage_balance(*args, widths=[1.], interval_mean=True, orientation='first_to_second', **kwargs)

    def test_final_state_matches_all_cells_and_explicit_coordinate_identity(self):
        state = self.root / 'restart.nc'; shutil.copy2(self.path, state)
        self.assertTrue(final_state(self.path, state)['passed'])
        from netCDF4 import Dataset
        with Dataset(state, 'r+') as ds: ds['mesh2d_face_x'][:] = ds['mesh2d_face_x'][::-1]
        with self.assertRaisesRegex(AssertionError, 'identities/coordinates'): final_state(self.path, state)

    def test_final_state_altered_bed_mass_clock_units_or_mask_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        state = self.root / 'restart.nc'
        for case in ('bed', 'mass', 'clock', 'units', 'mask'):
            with self.subTest(case=case):
                shutil.copy2(self.path, state)
                with Dataset(state, 'r+') as ds:
                    if case == 'bed': ds['mesh2d_mor_bl'][-1, 0] += .01
                    elif case == 'mass': ds['mesh2d_bodsed'][-1, 0, 0] += .01
                    elif case == 'clock': ds['time'][-1] += 1
                    elif case == 'units': ds['mesh2d_mor_bl'].units = 'days'
                    else: ds['mesh2d_bodsed'][-1, 0, 0] = np.ma.masked
                with self.assertRaises(AssertionError): final_state(self.path, state)

    def test_preparation_helper_refuses_run_commands(self):
        with self.assertRaisesRegex(AssertionError, 'refuses engine'): public_cli('run', 'start', 'anything')


@unittest.skipUnless(importlib.util.find_spec('netCDF4'), 'Optional run/NetCDF extra required')
class PublicMorphContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not {'morph create', 'morph inspect'} <= set(public_cli('schema', 'inspect')['commands']):
            raise unittest.SkipTest('Public morphology wiring pending; independent raw oracle still runs')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dfm-morph-public-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'spec.json'
        self.spec = release_specification()
        write_json(self.path, self.spec)

    def test_public_creation_inspection_and_no_spec_mutation(self):
        before = sha(self.path)
        out = self.root / 'authored'
        public_cli('morph', 'create', self.path, '--out', out)
        public_cli('morph', 'inspect', out / 'model.mdu')
        self.assertEqual(sha(self.path), before)
        self.assertTrue(bundle_check(out, self.spec)['passed'])

    def test_public_frozen_and_rest_definitions_are_distinct_from_transport_disabled(self):
        from research.workflows.verification.verify_morph import one_section, field_value
        for role, mode, rest, mf in [('active','mobile',False,'1'),('frozen','control',False,'0'),('rest','rest',True,'1'),('disabled','transport_disabled',False,'1')]:
            with self.subTest(role=role):
                spec = release_specification(mode, rest=rest)
                write_json(self.path, spec); out = self.root / role
                public_cli('morph','create',self.path,'--out',out)
                check = bundle_check(out,spec)
                mor = one_section(out/'morphology.mor','morphology')
                self.assertEqual(field_value(mor,'morfac'),mf)
                self.assertEqual(field_value(mor,'bed'),'0' if role == 'disabled' else '1')
                self.assertEqual(check['MorFac'],int(mf))

    def test_explicit_units_density_fraction_clock_and_path_refusals_are_atomic(self):
        for case in ('grain-unit', 'density', 'fraction', 'clock', 'crs', 'datum', 'path', 'unknown', 'dry', 'forcing', 'station'):
            with self.subTest(case=case):
                s = copy.deepcopy(self.spec)
                if case == 'grain-unit': s['grain']['d50']['unit'] = 'mm'
                elif case == 'density': s['grain']['dry_bulk_density']['value'] = 2700
                elif case == 'fraction': s['grain']['volume_fraction'] = .5
                elif case == 'clock': s['clock']['stop'] = '2001-01-01T00:10:01Z'
                elif case == 'crs': s['crs']['epsg'] = 4326
                elif case == 'datum': s['vertical_datum'] = ''
                elif case == 'path': s['name'] = '../escape'
                elif case == 'unknown': s['waves'] = True
                elif case == 'dry': s['initial_water_level_m'] = -3
                elif case == 'forcing': s['boundaries'][0]['water_level_m'][-1][0] = 59
                else: s['observations'][0]['x_m'] = 0
                write_json(self.path, s)
                out = self.root / case
                error = public_cli('morph', 'create', self.path, '--out', out, expected=4)
                self.assertNotIn(error['code'], ('usage', 'internal_error'))
                self.assertFalse(out.exists())

    def test_extreme_json_exponents_refused_without_output(self):
        text = self.path.read_text()
        for token in ('1e999', '1e-999'):
            with self.subTest(token=token):
                self.path.write_text(text.replace('0.0002', token))
                out = self.root / token
                public_cli('morph', 'create', self.path, '--out', out, expected=4)
                self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
