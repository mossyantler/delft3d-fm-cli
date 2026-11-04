"""Independent 3D-V acceptance/oracle fixtures; never launch a native engine."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.workflows.verification.verify_layers import (
    boundary_profile, check_bundle, check_outputs, fingerprints, initial_profile,
    public_cli, sigma_geometry, specification, write_json, write_synthetic_outputs,
)


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "Optional netCDF4/run extra required")
class IndependentLayerOracle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-layers-oracle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.spec = specification()
        self.map, self.history = write_synthetic_outputs(self.root, self.spec)

    def checked(self):
        return check_outputs(self.map, self.history, self.spec)

    def test_unequal_layers_nonzero_surface_and_bottom_to_top_elevations(self):
        import numpy as np
        result = sigma_geometry(-6, .5, [.2, .3, .5])
        np.testing.assert_allclose(result["z_interfaces"], [-6, -4.7, -2.75, .5], rtol=0, atol=1e-12)
        np.testing.assert_allclose(result["z_centres"], [-5.35, -3.725, -1.125], rtol=0, atol=1e-12)
        np.testing.assert_allclose(result["sigma_centres"], [-.9, -.65, -.25], rtol=0, atol=1e-12)
        require = self.checked()
        self.assertEqual(require["actual_layer_count"], 3)
        self.assertEqual(require["actual_interface_count"], 4)
        self.assertTrue(require["nonuniform_initial_profile_verified"])

    def test_initial_salinity_uses_actual_layer_centres_without_extrapolation(self):
        import numpy as np
        profile = self.spec["initial"]["salinity"]
        np.testing.assert_allclose(initial_profile([-5.35, -3.725, -1.125], profile), [27.5, 21.25, 11.25])
        for z in ([-6.1], [.6]):
            with self.subTest(z=z), self.assertRaises(AssertionError):
                initial_profile(z, profile)

    def test_boundary_interpolation_separates_time_and_fraction_from_bed(self):
        import numpy as np
        west = self.spec["boundaries"][0]
        # At t=10 the west rows average; f=.2 lies halfway from f=0 to .4.
        np.testing.assert_allclose(boundary_profile(west, 10, [0, .2, .4, 1]), [32, 27, 22, 7])
        for seconds in (-1, 21):
            with self.subTest(seconds=seconds), self.assertRaises(AssertionError):
                boundary_profile(west, seconds, [.2])

    def test_reversed_duplicated_or_wrong_unit_profiles_fail(self):
        for kind in ("initial-unit", "initial-order", "boundary-unit", "boundary-order", "boundary-columns"):
            with self.subTest(kind=kind):
                s = copy.deepcopy(self.spec)
                if kind.startswith("initial"):
                    p = s["initial"]["salinity"]
                    if kind.endswith("unit"):
                        p["unit"] = "g/L"
                    else:
                        p["z_m"] = list(reversed(p["z_m"]))
                    with self.assertRaises(AssertionError):
                        initial_profile([-3], p)
                else:
                    b = s["boundaries"][0]
                    if kind.endswith("unit"):
                        b["salinity"]["unit"] = "kg m-3"
                    elif kind.endswith("order"):
                        b["salinity"]["positions"] = [0, .4, .4]
                    else:
                        b["salinity"]["values"][0].pop()
                    with self.assertRaises((AssertionError, ValueError)):
                        boundary_profile(b, 10, [.2])

    def test_station_ids_cell_mapping_depth_profiles_and_cf_epoch(self):
        result = self.checked()
        self.assertEqual(result["stations"]["near_west"]["map_cell_index"], 0)
        self.assertEqual(result["stations"]["centre"]["map_cell_index"], 9)
        self.assertEqual(result["axes"][0]["iso"], result["axes"][1]["iso"])
        self.assertNotEqual(result["axes"][0]["units"], result["axes"][1]["units"])

    def test_authoritative_station_id_and_trailing_nul_name_padding(self):
        from netCDF4 import Dataset
        import numpy as np
        with Dataset(self.history, 'r+') as ds:
            for index, obs in enumerate(self.spec['observations']):
                ds['station_name'][index, len(obs['id']):] = np.full(20-len(obs['id']), b'', dtype='S1')
        self.assertEqual(set(self.checked()['stations']), {'near_west', 'centre'})
        with Dataset(self.history, 'r+') as ds:
            ds['station_name'][0, 2] = b''
        with self.assertRaisesRegex(AssertionError, 'Interior'):
            self.checked()

    def test_station_name_must_match_authoritative_id(self):
        from netCDF4 import Dataset
        with Dataset(self.history, 'r+') as ds:
            ds['station_id'][0, 0] = b'X'
        with self.assertRaisesRegex(AssertionError, 'identity mismatch'):
            self.checked()

    def test_depth_averaged_uniform_salinity_is_not_accepted_as_initial_profile(self):
        from netCDF4 import Dataset
        with Dataset(self.map, "r+") as ds:
            ds["mesh2d_sa1"][:] = 20
        with self.assertRaises(AssertionError):
            self.checked()

    def test_missing_layer_axis_is_not_accepted_as_three_dimensional_output(self):
        from netCDF4 import Dataset
        with Dataset(self.map, "r+") as ds:
            ds.renameVariable("mesh2d_sa1", "discarded_layered_data")
            v = ds.createVariable("mesh2d_sa1", "f8", ("time", "faces"))
            v.units, v.standard_name = "ppt", "sea_water_salinity"
            v[:] = 20
        with self.assertRaises(AssertionError):
            self.checked()

    def test_wrong_sigma_direction_or_interface_levels_fail(self):
        from netCDF4 import Dataset
        for case in ("direction", "interface"):
            raw = self.map.read_bytes()
            with self.subTest(case=case):
                with Dataset(self.map, "r+") as ds:
                    if case == "direction":
                        ds["mesh2d_layer_sigma"][:] = ds["mesh2d_layer_sigma"][::-1]
                    else:
                        ds["mesh2d_interface_sigma"][1] = -.5
                with self.assertRaises(AssertionError):
                    self.checked()
            self.map.write_bytes(raw)

    def test_mask_nonfinite_wrong_salinity_or_depth_units_fail(self):
        from netCDF4 import Dataset
        raw = self.map.read_bytes()
        for case in ("mask", "nan", "salt-unit", "bed-unit"):
            with self.subTest(case=case):
                self.map.write_bytes(raw)
                with Dataset(self.map, "r+") as ds:
                    if case == "mask":
                        ds["mesh2d_sa1"][0, 0, 1] = -999
                    elif case == "nan":
                        ds["mesh2d_ucx"][1, 0, 0] = float("nan")
                    elif case == "salt-unit":
                        ds["mesh2d_sa1"].units = "kg m-3"
                    else:
                        ds["mesh2d_flowelem_bl"].units = "cm"
                with self.assertRaises(AssertionError):
                    self.checked()

    def test_wrong_station_identity_elevation_or_layer_values_fail(self):
        from netCDF4 import Dataset
        raw = self.history.read_bytes()
        for case in ("identity", "z", "salinity"):
            with self.subTest(case=case):
                self.history.write_bytes(raw)
                with Dataset(self.history, "r+") as ds:
                    if case == "identity":
                        ds["station_name"][0, 0] = b"X"
                    elif case == "z":
                        ds["zcoordinate_c"][0, 0, 1] = -3
                    else:
                        ds["salinity"][0, 0, :] = ds["salinity"][0, 0, ::-1]
                with self.assertRaises(AssertionError):
                    self.checked()

    def test_early_missing_or_repeated_time_is_not_completion(self):
        from netCDF4 import Dataset
        with Dataset(self.map, "r+") as ds:
            ds["time"][-1] = 19
        with self.assertRaises(AssertionError):
            self.checked()

    def test_explicit_physical_layer_and_interface_output_route(self):
        from netCDF4 import Dataset
        import numpy as np
        with Dataset(self.map, "r+") as ds:
            ds.renameVariable("mesh2d_layer_sigma", "unused_layer_sigma")
            ds.renameVariable("mesh2d_interface_sigma", "unused_interface_sigma")
            geometry = sigma_geometry(ds["mesh2d_flowelem_bl"][:], ds["mesh2d_s1"][:], [.2, .3, .5])
            for name, dim, key in (("mesh2d_layer_z", "layers", "z_centres"), ("mesh2d_interface_z", "interfaces", "z_interfaces")):
                v = ds.createVariable(name, "f8", ("time", "faces", dim)); v.units = "m"; v[:] = geometry[key]
        self.assertIn("Full physical", self.checked()["coordinate_evidence"])
        with Dataset(self.map, "r+") as ds:
            ds["mesh2d_interface_z"][0, 0, 1] += .1
        with self.assertRaises(AssertionError):
            self.checked()


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "Optional netCDF4/run extra required")
class PublicLayersContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        commands = public_cli('schema', 'inspect')['commands']
        if not {'layers create', 'layers inspect'} <= set(commands):
            raise unittest.SkipTest('Public layers create/inspect registration pending; raw oracle tests still execute')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='dfm-layers-public-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.spec = specification()
        self.path = self.root / 'spec.json'
        write_json(self.path, self.spec)

    def create(self, name='authored'):
        folder = self.root / name
        result = public_cli('layers', 'create', self.path, '--out', folder)
        return folder, result

    def test_written_profiles_grid_layers_and_preflight_match_explicit_input(self):
        before = self.path.read_bytes()
        folder, result = self.create()
        checked = check_bundle(folder, self.spec)
        self.assertEqual(checked['layer_count'], 3)
        self.assertEqual(checked['forcing_blocks'], 8)
        self.assertEqual(self.path.read_bytes(), before)
        inspected = public_cli('layers', 'inspect', folder / 'model.mdu')
        self.assertEqual(inspected['checks']['engine_initialization'], 'not_performed')

    def test_wrong_layers_profiles_units_coverage_and_station_ids_refused(self):
        for case in ('one-layer', 'sum', 'negative', 'z-layers', 'salt-unit', 'short-profile', 'profile-order',
                     'boundary-unit', 'boundary-order', 'boundary-columns', 'coverage', 'station-id', 'station-outside', 'mixing', 'crs'):
            with self.subTest(case=case):
                s = copy.deepcopy(self.spec)
                if case == 'one-layer': s['layers']['fractions'] = [1]
                elif case == 'sum': s['layers']['fractions'] = [.2, .3, .6]
                elif case == 'negative': s['layers']['fractions'] = [-.2, .7, .5]
                elif case == 'z-layers': s['layers']['type'] = 'z'
                elif case == 'salt-unit': s['initial']['salinity']['unit'] = 'kg m-3'
                elif case == 'short-profile': s['initial']['salinity']['z_m'] = [-3, .5]
                elif case == 'profile-order': s['initial']['salinity']['z_m'] = [.5, -6]
                elif case == 'boundary-unit': s['boundaries'][0]['salinity']['unit'] = 'g/L'
                elif case == 'boundary-order': s['boundaries'][0]['salinity']['positions'] = [1, .4, 0]
                elif case == 'boundary-columns': s['boundaries'][0]['salinity']['values'][0].pop()
                elif case == 'coverage': s['boundaries'][0]['salinity']['values'][-1][0] = 19
                elif case == 'station-id': s['observations'][1]['id'] = s['observations'][0]['id'].upper()
                elif case == 'station-outside': s['observations'][0]['x_m'] = 499999
                elif case == 'mixing': s['mixing']['vertical_diffusivity_m2s'] = -1
                elif case == 'crs': s['crs']['unit'] = 'km'
                write_json(self.path, s)
                out = self.root / case
                error = public_cli('layers', 'create', self.path, '--out', out, expected=4)
                self.assertNotIn(error['code'], ('usage', 'internal_error'))
                self.assertFalse(out.exists())

    def test_existing_destination_is_preserved_and_inputs_relocate_without_receipts(self):
        folder, _ = self.create()
        before = fingerprints(folder)
        public_cli('layers', 'create', self.path, '--out', folder, expected=4)
        self.assertEqual(fingerprints(folder), before)
        moved = self.root / 'moved native inputs'
        folder.rename(moved)
        for metadata in ('layers-spec.json', 'layers-provenance.json'):
            (moved / metadata).unlink()
        public_cli('layers', 'inspect', moved / 'model.mdu')

    def test_missing_or_corrupt_initial_and_boundary_profiles_are_refused(self):
        folder, _ = self.create()
        for name in ('initial.ini', 'initial_salinity.pli', 'boundaries.bc'):
            with self.subTest(name=name):
                path = folder / name
                raw = path.read_bytes()
                path.unlink()
                error = public_cli('layers', 'inspect', folder / 'model.mdu', expected=4)
                self.assertNotEqual(error['code'], 'internal_error')
                path.write_bytes(raw)
        profile = folder / 'initial_salinity.pli'
        profile.write_bytes(profile.read_bytes().replace(b'-6 30', b'-3 30'))
        public_cli('layers', 'inspect', folder / 'model.mdu', expected=4)


if __name__ == "__main__":
    unittest.main()
