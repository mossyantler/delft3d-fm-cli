"""Portable E012-R negatives; synthetic files, no engine or product imports."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest
import shutil

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc = np = None

from research.workflows.verification import verify_parallel_continuation as prep
from research.workflows.verification import verify_parallel_continuation_raw as raw


def variable(ds, name, dimensions, values, units=None, dtype="f8", **attrs):
    v = ds.createVariable(name, dtype, dimensions, fill_value=-999 if dtype != "S1" else None)
    if units is not None:
        v.units = units
    for key, value in attrs.items():
        v.setncattr(key, value)
    v[:] = values
    return v


def mesh(path, mapped=False):
    with nc.Dataset(path, "w") as ds:
        for name, count in {"node": 6, "edge": 7, "face": 2, "maxnode": 4, "two": 2}.items():
            ds.createDimension(name, count)
        ds.createDimension("time", 3 if mapped else 1)
        variable(ds, "time", ("time",), [0, 10, 120] if mapped else [120],
                 "seconds since 2001-01-01 00:00:00 +00:00", standard_name="time")
        variable(ds, "mesh2d_node_x", ("node",), [0, 1, 2, 0, 1, 2], "m")
        variable(ds, "mesh2d_node_y", ("node",), [0, 0, 0, 1, 1, 1], "m")
        variable(ds, "mesh2d_node_z", ("node",), [-1] * 6, "m")
        variable(ds, "mesh2d_face_x", ("face",), [.5, 1.5], "m")
        variable(ds, "mesh2d_face_y", ("face",), [.5, .5], "m")
        variable(ds, "mesh2d_face_nodes", ("face", "maxnode"), [[0, 1, 4, 3], [1, 2, 5, 4]],
                 dtype="i4", start_index=0)
        variable(ds, "mesh2d_edge_nodes", ("edge", "two"),
                 [[0, 1], [1, 2], [3, 4], [4, 5], [0, 3], [1, 4], [2, 5]], dtype="i4", start_index=0)
        m = ds.createVariable("mesh2d", "i4")
        m.setncatts({"cf_role": "mesh_topology", "topology_dimension": 2,
                    "node_coordinates": "mesh2d_node_x mesh2d_node_y",
                    "face_node_connectivity": "mesh2d_face_nodes", "edge_node_connectivity": "mesh2d_edge_nodes"})
        c = ds.createVariable("projected_coordinate_system", "i4")
        c.setncatts({"grid_mapping_name": "transverse_mercator", "epsg": 32631})
        c.assignValue(0)
        if mapped:
            variable(ds, "mesh2d_flowelem_globalnr", ("face",), [1, 2], dtype="i4")
            variable(ds, "mesh2d_flowelem_domain", ("face",), [0, 1], dtype="i4")


def state(path, added=False, reversed_links=False):
    with nc.Dataset(path, "w") as ds:
        dims = {"time": 1, "nFlowElem": 2, "nNetElem": 2, "nNetNode": 6, "nFlowLink": 3,
                "nNetLink": 7, "nFlowElemBnd": 2, "nNetElemMaxNode": 4,
                "nFlowLinkPts": 2, "nNetLinkPts": 2}
        for name, size in dims.items():
            ds.createDimension(name, size)
        variable(ds, "time", ("time",), [120], "seconds since 2001-01-01 00:00:00 +00:00", standard_name="time")
        variable(ds, "timestep", ("time",), [1], "seconds")
        for suffix, xs, ys, dim in (("Elem_xzw", [.5, 1.5], [.5, .5], "nFlowElem"),
                                   ("Elem_xcc", [.5, 1.5], [.5, .5], "nFlowElem"),
                                   ("Link_xu", [0, 1, 2], [.5, .5, .5], "nFlowLink"),
                                   ("Elem_xbnd", [-.5, 2.5], [.5, .5], "nFlowElemBnd")):
            variable(ds, "Flow" + suffix, (dim,), xs, "m")
            variable(ds, "Flow" + suffix.replace("x", "y"), (dim,), ys, "m")
        variable(ds, "FlowElemGlobalNr", ("nFlowElem",), [1, 2], dtype="i4")
        variable(ds, "FlowElemDomain", ("nFlowElem",), [0, 1], dtype="i4")
        for name in "s1 s0 taus czs FlowElem_bl ucx ucy ucxq ucyq squ sqi".split():
            variable(ds, name, ("time", "nFlowElem"), [[.1, .2]], "m")
        for name in "s0_bnd s1_bnd bl_bnd sqi_bnd squ_bnd ucxq_bnd ucyq_bnd".split():
            variable(ds, name, ("time", "nFlowElemBnd"), [[.3, .4]], "m")
        for name in "unorm u0 q1 qa fvcoro hu".split():
            value = [[1, 2, 3]]
            if reversed_links and name != "hu":
                value = [[-1, -2, -3]]
            variable(ds, name, ("time", "nFlowLink"), value, "m")
        links = [[1, 3], [1, 2], [2, 4]]
        variable(ds, "FlowLink", ("nFlowLink", "nFlowLinkPts"),
                 [v[::-1] for v in links] if reversed_links else links, dtype="i4")
        variable(ds, "NetElemNode", ("nNetElem", "nNetElemMaxNode"), [[1, 2, 5, 4], [2, 3, 6, 5]], dtype="i4", start_index=1)
        variable(ds, "NetLink", ("nNetLink", "nNetLinkPts"),
                 [[1, 2], [2, 3], [4, 5], [5, 6], [1, 4], [2, 5], [3, 6]], dtype="i4", start_index=1)
        if added:
            variable(ds, "NetNode_x", ("nNetNode",), [0, 1, 2, 0, 1, 2], "m")
            variable(ds, "NetNode_y", ("nNetNode",), [0, 0, 0, 1, 1, 1], "m")
            variable(ds, "NetNode_z", ("nNetNode",), [-1] * 6, "m")
            c = ds.createVariable("projected_coordinate_system", "i4")
            c.setncatts({"grid_mapping_name": "transverse_mercator", "epsg": 32631})
            c.assignValue(0)


def series(path, times, *, encoded=False):
    with nc.Dataset(path, "w") as ds:
        ds.createDimension("time", len(times))
        ds.createDimension("station", 2)
        ds.createDimension("char", 2)
        variable(ds, "time", ("time",), times, "seconds since 2001-01-01 00:00:00 +00:00", standard_name="time")
        ids = ds.createVariable("station_id", "S1", ("station", "char"))
        ids[:] = np.asarray([[b"A", b"1"], [b"B", b"1"]], dtype="S1")
        ids.cf_role = "timeseries_id"
        if encoded:
            ids._Encoding = "utf-8"
        variable(ds, "station_x", ("station",), [0, 1], "m")
        variable(ds, "waterlevel", ("time", "station"), [[t / 1000, t / 2000] for t in times], "m")
        variable(ds, "water_balance_volume", ("time",), times, "m3")


@unittest.skipIf(nc is None, "optional run dependency not installed")
class RawContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def comparison(self, **kwargs):
        return raw.compare_datasets(self.root / "a.nc", self.root / "b.nc", [0, 10, 20], [10, 20], prep.policy(), **kwargs)

    def test_complete_clock_and_all_fields_including_seam(self):
        series(self.root / "a.nc", [0, 10, 20])
        series(self.root / "b.nc", [10, 20])
        result = self.comparison()
        self.assertTrue(result["passed"])
        self.assertEqual(result["reference_indices"], [1, 2])
        self.assertIn("water_balance_volume", result["fields"])
        with nc.Dataset(self.root / "b.nc", "a") as ds:
            ds["water_balance_volume"][0] = 0
        self.assertFalse(self.comparison()["passed"], "No counter offset/seam removal")

    def test_missing_terminal_is_not_intersection_compared(self):
        series(self.root / "a.nc", [0, 10, 20])
        series(self.root / "b.nc", [10])
        with self.assertRaisesRegex(AssertionError, "full schedule"):
            self.comparison()

    def test_cf_origin_and_calendar_handled(self):
        series(self.root / "a.nc", [0, 10, 20])
        series(self.root / "b.nc", [10, 20])
        with nc.Dataset(self.root / "b.nc", "a") as ds:
            ds["time"].units = "minutes since 2001-01-01 00:00:10 +00:00"
            ds["time"][:] = [0, 1 / 6]
        self.assertTrue(self.comparison()["passed"])
        with nc.Dataset(self.root / "b.nc", "a") as ds:
            ds["time"].calendar = "360_day"
        with self.assertRaisesRegex(AssertionError, "calendar"):
            self.comparison()

    def test_units_masks_nonfinite_and_unlisted_fields_fail(self):
        for kind in ("units", "mask", "nan", "unlisted"):
            with self.subTest(kind=kind):
                series(self.root / "a.nc", [0, 10, 20])
                series(self.root / "b.nc", [10, 20])
                with nc.Dataset(self.root / "b.nc", "a") as ds:
                    if kind == "units":
                        ds["waterlevel"].units = "cm"
                    elif kind == "mask":
                        ds["waterlevel"][0, 0] = -999
                    elif kind == "nan":
                        ds["waterlevel"][0, 0] = float("nan")
                    else:
                        ds["water_balance_volume"][1] += 1e-12
                self.assertFalse(self.comparison()["passed"])

    def test_matching_wrong_quantity_units_also_fail(self):
        series(self.root / "a.nc", [0, 10, 20])
        series(self.root / "b.nc", [10, 20])
        for name in ("a.nc", "b.nc"):
            with nc.Dataset(self.root / name, "a") as ds:
                ds["waterlevel"].units = "cm"
        self.assertFalse(self.comparison()["fields"]["waterlevel"]["passed"])

    def test_pa_alias_requires_explicit_reanalysis_without_tolerance_change(self):
        for name, times in (("a.nc", [0, 10, 20]), ("b.nc", [10, 20])):
            series(self.root / name, times)
            with nc.Dataset(self.root / name, "a") as ds:
                variable(ds, "tausx", ("time", "station"), [[.1, .2]] * len(times), "Pa")
        self.assertFalse(self.comparison()["fields"]["tausx"]["passed"])
        result = self.comparison(unit_aliases={"N m-2": {"N m-2", "Pa"}})
        self.assertTrue(result["passed"])
        self.assertEqual(result["fields"]["tausx"]["atol"], prep.policy()["tolerances"]["stress"]["atol"])

    def test_auto_chartostring_and_canonical_station_id(self):
        series(self.root / "a.nc", [0, 10, 20], encoded=True)
        series(self.root / "b.nc", [10, 20], encoded=True)
        self.assertTrue(self.comparison()["passed"])
        with nc.Dataset(self.root / "b.nc", "a") as ds:
            ds["station_id"][:] = np.array(["A1", "A1"], dtype="U2")
        with self.assertRaisesRegex(AssertionError, "Ambiguous station"):
            self.comparison()

    def test_raw_topology_and_crs_are_not_dimension_counts(self):
        mesh(self.root / "a.nc", mapped=True)
        mesh(self.root / "b.nc", mapped=True)
        with nc.Dataset(self.root / "b.nc", "a") as ds:
            ds["mesh2d_face_nodes"][0] = [0, 4, 1, 3]
        with self.assertRaises(AssertionError):
            raw.compare_datasets(self.root / "a.nc", self.root / "b.nc", [0, 10, 120], [0, 10, 120], prep.policy())

    def assembly_fixture(self):
        mesh(self.root / "mesh.nc")
        sources = []
        for rank in (0, 1):
            mesh(self.root / f"map{rank}.nc", mapped=True)
            mesh(self.root / f"net{rank}.nc")
            state(self.root / f"rst{rank}.nc", reversed_links=rank == 1)
            sources.append({"rank": rank, "restart": self.root / f"rst{rank}.nc",
                            "map": self.root / f"map{rank}.nc", "net": self.root / f"net{rank}.nc"})
        state(self.root / "assembled.nc", added=True)
        return sources

    def test_all_39_checkpoint_variables_and_oriented_links(self):
        sources = self.assembly_fixture()
        result = raw.audit_assembly(self.root / "assembled.nc", self.root / "mesh.nc", sources)
        self.assertEqual(result["source_variable_count"], 39)
        self.assertEqual(result["output_variable_count"], 43)
        self.assertEqual(len(result["checks"]), 78)
        self.assertEqual(result["native_consumption"], "not_performed")
        self.assertFalse(result["filename_selects_spatial_remap"])

    def test_checkpoint_hidden_state_not_just_waterlevel(self):
        sources = self.assembly_fixture()
        with nc.Dataset(self.root / "assembled.nc", "a") as ds:
            ds["fvcoro"][0, 1] += .001
        with self.assertRaisesRegex(AssertionError, "fvcoro"):
            raw.audit_assembly(self.root / "assembled.nc", self.root / "mesh.nc", sources)

    def test_raw_consumption_does_not_apply_provenance_sign_correction(self):
        self.assembly_fixture()
        # A serial-style checkpoint does not carry FlowLink orientation.
        with nc.Dataset(self.root / "rst1.nc", "a") as ds:
            ds.renameVariable("FlowLink", "unusedFlowLink")
        # Use a separate clone excluding topology fields, like actual native
        # serial checkpoints; only known solver/coordinate arrays are retained.
        source = self.root / "rst1.nc"
        target = self.root / "serial.nc"
        with nc.Dataset(source) as a, nc.Dataset(target, "w") as b:
            for name, d in a.dimensions.items():
                b.createDimension(name, len(d))
            for name, v in a.variables.items():
                if name in {"unusedFlowLink", "NetElemNode", "NetLink", "FlowElemDomain", "FlowElemGlobalNr"}:
                    continue
                attrs = raw.metadata(v)
                out = b.createVariable(name, v.dtype, v.dimensions, fill_value=attrs.pop("_FillValue", None))
                out.setncatts(attrs)
                out[:] = v[:]
        report = raw.consumption_audit(self.root / "assembled.nc", target, self.root / "mesh.nc", prep.policy())
        self.assertFalse(report["coordinate_matched_stored_state_equal"])
        self.assertFalse(report["fields"]["q1"]["passed"])
        self.assertTrue(report["fields"]["hu"]["passed"])
        self.assertEqual(report["normal_correction"], "none")

    def test_adapter_complete_fields_and_native_ghost_normal(self):
        mesh(self.root / "mesh.nc")
        state(self.root / "source.nc", added=True)
        adapted = self.root / "continuation_merged_rst.nc"
        shutil.copyfile(self.root / "source.nc", adapted)
        with nc.Dataset(adapted, "a") as ds:
            for name in ("unorm", "u0", "q1", "qa", "fvcoro"):
                ds[name][:] = ds[name][:] * np.asarray([-1, 1, -1])[None, :]
            pairs = ds["FlowLink"][:]
            pairs[0] = pairs[0, ::-1]
            pairs[2] = pairs[2, ::-1]
            ds["FlowLink"][:] = pairs
            ds["NetNode_z"].coordinates = "NetNode_x NetNode_y"
        result = raw.audit_reader_adapter(self.root / "source.nc", adapted, self.root / "mesh.nc")
        self.assertEqual(result["variable_count"], 43)
        self.assertEqual(result["reoriented_links"], 2)
        with nc.Dataset(adapted, "a") as ds:
            ds["ucxq_bnd"][0, 0] += .000001
        with self.assertRaisesRegex(AssertionError, "ucxq_bnd"):
            raw.audit_reader_adapter(self.root / "source.nc", adapted, self.root / "mesh.nc")

    def test_checkpoint_missing_var_and_wrong_link_normal(self):
        sources = self.assembly_fixture()
        with nc.Dataset(self.root / "rst1.nc", "a") as ds:
            ds["qa"][0, 0] *= -1
        with self.assertRaisesRegex(AssertionError, "qa"):
            raw.audit_assembly(self.root / "assembled.nc", self.root / "mesh.nc", sources)

    def test_equal_counts_foreign_checkpoint_coordinates_rejected(self):
        sources = self.assembly_fixture()
        with nc.Dataset(self.root / "assembled.nc", "a") as ds:
            ds["NetNode_x"][0] = .01
        with self.assertRaisesRegex(AssertionError, "nodes differ"):
            raw.audit_assembly(self.root / "assembled.nc", self.root / "mesh.nc", sources)


class PreparationTests(unittest.TestCase):
    def test_narrow_bc_and_clock_edits(self):
        bc = b"Function = timeseries\r\n0 0\r\n120 0\r\nFunction = timeseries\r\n0 0\r\n120 0\r\n"
        self.assertEqual(prep.extend_bc(bc), bc.replace(b"120 0", b"240 0"))
        original = b"# keep\r\nTStart = 0\r\nTStop = 120\r\nStartDateTime = 20010101000000\r\nStopDateTime = 20010101000200\r\nOther = preserved\r\n"
        patched = prep.patch_mdu(original, 120, 240)
        self.assertIn(b"TStart = 120\r\n", patched)
        self.assertIn(b"StopDateTime = 20010101000400\r\n", patched)
        self.assertTrue(patched.endswith(b"Other = preserved\r\n"))
        with self.assertRaises(AssertionError):
            prep.extend_bc(bc.replace(b"120 0", b"121 0"))

    def test_existing_output_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(AssertionError, "NEW"):
                prep.prepare(root, root)
            with self.assertRaisesRegex(AssertionError, "escapes"):
                prep.inside(root, Path(__file__))

    def test_probes_cannot_launch_or_apply(self):
        with self.assertRaises(AssertionError):
            prep.probe(Path("."), "bad", ["run", "start"], Path("."))
        with self.assertRaises(AssertionError):
            prep.probe(Path("."), "bad", ["restart", "prepare", "--apply"], Path("."))

    def test_missing_or_unverified_native_proof_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text(json.dumps({"schema_version": 3, "route": "direct",
                "state": "completed", "returncode": 0, "ownership": {"method": "windows_job_object",
                "assigned_before_resume": True, "final_job_pids": [99]}}))
            with self.assertRaisesRegex(AssertionError, "cleanup"):
                prep.native_record(root, 240)

    def test_another_valid_model_cannot_replace_matched_forcing(self):
        prepared = {"files": {"boundaries.bc": "predeclared", "model.mdu": "not-reached"}}
        record = {"inputs": [{"relative_path": "boundaries.bc", "sha256": "another-valid-forcing"}]}
        with self.assertRaisesRegex(AssertionError, "Unmatched native forcing"):
            prep.bind_model(record, Path("."), prepared)

    def test_ambiguous_duplicate_settings_rejected(self):
        with self.assertRaisesRegex(AssertionError, "duplicate"):
            prep.settings(b"[time]\nTStart=0\nTStart=120\n")

    def test_oracles_have_no_product_or_other_verifier_imports(self):
        for module in (prep, raw):
            tree = ast.parse(Path(module.__file__).read_text())
            names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(n and (n.startswith("dfm_cli") or n.endswith("verify_parallel") or
                                       n.endswith("verify_restart")) for n in names))
        self.assertEqual(prep.product_requirements()["status"], "wired_explicit_assembled_pending_native")


if __name__ == "__main__":
    unittest.main()
