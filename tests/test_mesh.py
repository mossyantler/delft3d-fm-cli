"""Independent M4 public-command acceptance; these tests never start an engine."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_mesh import (
    X0, Y0, PublicCLI, build, check_grid, check_m3_mapping,
    fingerprints, m3_model_spec, mesh_spec, raw_mesh, topology,
)


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "Optional netCDF4/run extra required")
class PublicMeshAcceptance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-mesh-independent-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cli = PublicCLI(self.root / "commands")
        self.serial = 0

    def built(self, spec=None):
        self.serial += 1
        spec = mesh_spec() if spec is None else spec
        result = build(self.cli, spec, self.root / f"spec-{self.serial}.json", self.root / f"mesh-{self.serial}")
        return Path(result["net_file"]), result

    def rejected(self, spec, expected=4):
        self.serial += 1
        source = self.root / f"invalid-{self.serial}.json"
        source.write_text(json.dumps(spec), encoding="utf-8")
        output = self.root / f"rejected-{self.serial}"
        before = fingerprints(self.root)
        result = self.cli.invoke("mesh", "build", source, "--out", output, code=expected)
        self.assertNotIn(result["code"], ("internal_error", "usage"))
        self.assertFalse(output.exists(), "Rejected build published output")
        after = fingerprints(self.root)
        self.assertEqual({k: v for k, v in after.items() if not k.startswith("commands/")},
                         {k: v for k, v in before.items() if not k.startswith("commands/")})
        return result

    def test_public_commands_discoverable(self):
        schema = self.cli.invoke("schema", "inspect")
        for command in ("mesh build", "mesh inspect"):
            self.assertIn(command, schema["commands"])

    def test_known_rectangle_coordinates_bed_datum_and_topology(self):
        mesh, result = self.built()
        checked = check_grid(mesh)
        self.assertEqual((checked["nodes"], checked["edges"], checked["faces"]), (65, 112, 48))
        grid = raw_mesh(mesh)
        self.assertEqual(set(grid["nodes"]), {(X0+x, Y0+y) for x in range(0, 121, 10) for y in range(0, 41, 10)})
        self.assertEqual(checked["area_m2"], 4800)
        self.assertEqual(checked["bed_range_m"], [-3, -3])
        self.assertEqual(result["validation"]["simulation"], "not_performed")
        inspected = self.cli.invoke("mesh", "inspect", mesh)
        for key in ("nodes", "edges", "faces", "boundary_edges"):
            self.assertEqual(inspected["quality"][key], checked[key])
        self.assertEqual(inspected["quality"]["area_m2"]["total"], checked["area_m2"])
        self.assertAlmostEqual(inspected["quality"]["minimum_interior_angle_deg"], 90)

    def test_positive_down_depth_requires_reference_and_converts_to_elevation(self):
        spec = mesh_spec()
        spec["bathymetry"].update(quantity="depth", positive="down", value=5, reference_level_m=2)
        mesh, _ = self.built(spec)
        check_grid(mesh, lambda x, y: -3)
        del spec["bathymetry"]["reference_level_m"]
        self.rejected(spec)
        spec["bathymetry"].update(reference_level_m=2, value=-5)
        self.rejected(spec)

    def test_concave_boundary_is_clipped_to_polygon_not_bounding_rectangle(self):
        spec = mesh_spec()
        spec["geometry"]["boundary"] = [[X0, Y0], [X0+120, Y0], [X0+120, Y0+20],
                                          [X0+60, Y0+20], [X0+60, Y0+40], [X0, Y0+40]]
        mesh, _ = self.built(spec)
        checked = check_grid(mesh, area=3600, rectangle=False)
        grid = raw_mesh(mesh)
        self.assertEqual(checked["faces"], 36)
        expected = {(X0+x, Y0+y) for x in range(0, 121, 10) for y in range(0, 41, 10) if x <= 60 or y <= 20}
        self.assertEqual(set(grid["nodes"]), expected)
        for face in grid["faces"]:
            x, y = [sum(grid["nodes"][i][dim] for i in face)/len(face) for dim in (0, 1)]
            self.assertTrue(x < X0+60 or y < Y0+20, "Generated a cell outside the L polygon")

    def test_crs_units_datum_and_sign_conflicts_are_refused_without_conversion(self):
        mutations = [("crs", "unit", "km"), ("crs", "epsg", 4326),
                     ("bathymetry", "unit", "cm"), ("bathymetry", "positive", "down"),
                     ("bathymetry", "vertical_datum", "NAP"), ("initial_water_level", "unit", "cm"),
                     ("initial_water_level", "vertical_datum", "NAP"), ("roughness", "unit", "m"),
                     ("roughness", "law", "Chezy")]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                spec = mesh_spec()
                spec[section][key] = value
                self.rejected(spec)
        for missing in ("vertical_datum", "vertical_datum_provenance"):
            with self.subTest(missing=missing):
                spec = mesh_spec()
                del spec[missing]
                self.rejected(spec)

    def test_analytic_plane_and_bilinear_cross_term_are_interpolated_at_nodes(self):
        spec = mesh_spec()
        spec["bathymetry"].update(method="plane", value=-3, origin=[X0, Y0], gradient=[.005, -.01])
        mesh, _ = self.built(spec)
        check_grid(mesh, lambda x, y: -3+.005*(x-X0)-.01*(y-Y0))
        field = spec["bathymetry"]
        for key in ("value", "origin", "gradient"):
            del field[key]
        formula = lambda x, y: -5+(x-X0)/120+(y-Y0)/40+(x-X0)*(y-Y0)/4800
        field.update(method="linear", samples=[[x, y, formula(x, y)] for x in (X0, X0+120) for y in (Y0, Y0+40)])
        mesh, _ = self.built(spec)
        check_grid(mesh, formula)

    def test_linear_missing_and_outside_coverage_follow_declared_policy(self):
        for case in ("missing", "outside"):
            with self.subTest(case=case):
                spec = mesh_spec()
                field = spec["bathymetry"]
                del field["value"]
                xmax = X0+60 if case == "outside" else X0+120
                field.update(method="linear", samples=[[x, y, -3] for x in (X0, xmax) for y in (Y0, Y0+40)])
                if case == "missing":
                    field["samples"][-1][-1] = None
                self.rejected(spec)
                field["missing"] = {"policy": "constant", "value": -9}
                mesh, result = self.built(spec)
                grid = raw_mesh(mesh)
                for (x, y), z in zip(grid["nodes"], grid["z"]):
                    expected = (-9 if x > xmax else -3) if case == "outside" else (-3 if x == X0 or y == Y0 else -9)
                    self.assertEqual(z, expected, (x, y, z))
                self.assertGreater(result["bathymetry"]["filled_node_count"], 0)

    def test_nearest_max_distance_and_explicit_tie_order(self):
        spec = mesh_spec()
        field = spec["bathymetry"]
        del field["value"]
        field.update(method="nearest", samples=[[X0, Y0, -2], [X0+20, Y0, -4]], max_distance_m=10)
        self.rejected(spec)
        field["missing"] = {"policy": "constant", "value": -8}
        mesh, _ = self.built(spec)
        values = dict(zip(raw_mesh(mesh)["nodes"], raw_mesh(mesh)["z"]))
        self.assertEqual(values[X0+10, Y0], -2, "Nearest ties must preserve declared sample order")
        self.assertEqual(values[X0+120, Y0+40], -8)
        self.assertEqual(values[X0+20, Y0], -4)

    def test_positive_down_missing_fill_is_converted_in_its_declared_quantity(self):
        spec = mesh_spec()
        field = spec["bathymetry"]
        del field["value"]
        field.update(quantity="depth", positive="down", reference_level_m=2, method="nearest",
                     samples=[[X0, Y0, 5]], max_distance_m=1, missing={"policy": "constant", "value": 7})
        mesh, _ = self.built(spec)
        grid = raw_mesh(mesh)
        for xy, z in zip(grid["nodes"], grid["z"]):
            self.assertEqual(z, -3 if xy == (X0, Y0) else -5)

    def test_local_refinement_preserves_same_strip_far_cells_and_is_conforming(self):
        coarse, _ = self.built()
        spec = mesh_spec()
        spec["geometry"]["refinements"] = [{"bounds": [X0+20, Y0+10, X0+40, Y0+30], "factor": 2}]
        fine, _ = self.built(spec)
        result = check_grid(fine)
        self.assertGreater(result["faces"], 48)
        self.assertLess(result["cell_area_min_m2"], 100)
        old, new = raw_mesh(coarse), raw_mesh(fine)
        signatures = lambda g: {frozenset(g["nodes"][i] for i in f) for f in g["faces"]}
        cell = [(X0+90, Y0+10), (X0+100, Y0+10), (X0+100, Y0+20), (X0+90, Y0+20)]
        self.assertIn(frozenset(cell), signatures(old))
        self.assertTrue(frozenset(cell) in signatures(new), "Refinement propagated across a distant strip")
        grid_areas = result["face_areas_m2"]
        fine_roi = [a for face, a in zip(new["faces"], grid_areas)
                    if X0+20 < sum(new["nodes"][i][0] for i in face)/len(face) < X0+40
                    and Y0+10 < sum(new["nodes"][i][1] for i in face)/len(face) < Y0+30]
        self.assertTrue(fine_roi)
        self.assertLessEqual(max(fine_roi), 25)

    def test_local_refinement_distant_same_x_strip_cell_preserved(self):
        spec = mesh_spec()
        spec["geometry"]["refinements"] = [{"bounds": [X0+20, Y0, X0+40, Y0+10], "factor": 2}]
        mesh, _ = self.built(spec)
        checked = check_grid(mesh)
        grid = raw_mesh(mesh)
        distant = frozenset([(X0+20, Y0+30), (X0+30, Y0+30), (X0+30, Y0+40), (X0+20, Y0+40)])
        self.assertTrue(distant in {frozenset(grid["nodes"][i] for i in face) for face in grid["faces"]}, "Distant same-x-strip cell changed")
        self.assertEqual(checked["t_junctions"], 0)

    def test_invalid_polygons_duplicate_samples_and_absent_missing_policy_refused(self):
        for case in ("diagonal", "self_cross", "duplicate_sample", "missing_policy", "initial_dry"):
            with self.subTest(case=case):
                spec = mesh_spec()
                if case == "diagonal":
                    spec["geometry"]["boundary"][1][1] += 1
                elif case == "self_cross":
                    b = spec["geometry"]["boundary"]
                    spec["geometry"]["boundary"] = [b[0], b[2], b[1], b[3]]
                elif case == "duplicate_sample":
                    del spec["bathymetry"]["value"]
                    spec["bathymetry"].update(method="nearest", max_distance_m=1000, samples=[[X0, Y0, -3], [X0, Y0, -4]])
                elif case == "missing_policy":
                    del spec["bathymetry"]["missing"]
                else:
                    spec["initial_water_level"]["value"] = -4
                self.rejected(spec)

    def test_stale_preview_missing_hash_and_existing_output_refused(self):
        source, out = self.root / "stale.json", self.root / "stale-output"
        spec = mesh_spec()
        source.write_text(json.dumps(spec))
        preview = self.cli.invoke("mesh", "build", source, "--out", out)
        self.cli.invoke("mesh", "build", source, "--out", out, "--apply", code=2)
        spec["roughness"]["value"] = .04
        source.write_text(json.dumps(spec))
        self.cli.invoke("mesh", "build", source, "--out", out, "--apply", "--expect-sha256", preview["input_sha256"], code=4)
        self.assertFalse(out.exists())
        out.mkdir()
        (out / "user-file").write_bytes(b"preserve me\x00\r\n")
        before = fingerprints(out)
        self.cli.invoke("mesh", "build", source, "--out", out, code=4)
        self.assertEqual(fingerprints(out), before)

    def test_imported_input_changed_after_preview_refused(self):
        from netCDF4 import Dataset
        mesh, _ = self.built()
        spec = mesh_spec()
        spec["geometry"] = {"kind": "ugrid", "path": str(mesh)}
        source, out = self.root / "import.json", self.root / "stale-import"
        source.write_text(json.dumps(spec))
        preview = self.cli.invoke("mesh", "build", source, "--out", out)
        with Dataset(mesh, "r+") as ds:
            ds.history = "Independent concurrent metadata change"
        before = mesh.read_bytes()
        self.cli.invoke("mesh", "build", source, "--out", out, "--apply", "--expect-sha256", preview["input_sha256"], code=4)
        self.assertFalse(out.exists())
        self.assertEqual(mesh.read_bytes(), before)

    def test_extreme_scalar_resolution_and_refinement_bounds_refused(self):
        for case in ("huge_bed", "overflow_plane", "outside_refinement", "zero_resolution"):
            with self.subTest(case=case):
                spec = mesh_spec()
                if case == "huge_bed":
                    spec["bathymetry"]["value"] = float("inf")
                elif case == "overflow_plane":
                    spec["bathymetry"].update(method="plane", origin=[X0, Y0], gradient=[1e308, 0])
                elif case == "outside_refinement":
                    spec["geometry"]["refinements"] = [{"bounds": [X0-10, Y0, X0+10, Y0+10], "factor": 2}]
                else:
                    spec["geometry"]["cell_size"]["x"] = 0
                self.rejected(spec)

    def test_import_preserves_coordinates_topology_and_explicitly_replaces_bed(self):
        original, _ = self.built()
        spec = mesh_spec()
        spec["geometry"] = {"kind": "ugrid", "path": str(original)}
        spec["bathymetry"]["value"] = -4
        before = original.read_bytes()
        imported, _ = self.built(spec)
        check_grid(imported, lambda x, y: -4)
        a, b = raw_mesh(original), raw_mesh(imported)
        self.assertEqual(a["nodes"], b["nodes"])
        self.assertEqual({frozenset(f) for f in a["faces"]}, {frozenset(f) for f in b["faces"]})
        self.assertEqual(original.read_bytes(), before)

    def test_import_unit_datum_and_topology_corruptions_rejected(self):
        from netCDF4 import Dataset
        source, _ = self.built()
        raw = source.read_bytes()
        for case in ("unit", "datum", "edge", "reverse", "unused_node"):
            with self.subTest(case=case):
                source.write_bytes(raw)
                with Dataset(source, "r+") as ds:
                    if case == "unit":
                        ds["mesh2d_node_x"].units = "km"
                    elif case == "datum":
                        ds.vertical_datum = "different datum"
                    elif case == "edge":
                        ds["mesh2d_edge_nodes"][0] = ds["mesh2d_edge_nodes"][1]
                    elif case == "reverse":
                        # A consistently reversed imported face may be
                        # normalized; the independent oracle must catch it.
                        ds["mesh2d_face_nodes"][0] = ds["mesh2d_face_nodes"][0, ::-1]
                    else:
                        ds["mesh2d_face_nodes"][0, 0] = 9999
                if case == "reverse":
                    with self.assertRaises(AssertionError):
                        check_grid(source)
                else:
                    spec = mesh_spec()
                    spec["geometry"] = {"kind": "ugrid", "path": str(source)}
                    self.rejected(spec)
        source.write_bytes(raw)

    def test_nondefault_uniform_settings_reach_m3_actual_mdu(self):
        spec = mesh_spec()
        spec["initial_water_level"]["value"] = .25
        spec["roughness"]["value"] = .041
        mesh, result = self.built(spec)
        model = m3_model_spec(mesh, spec)
        path = self.root / "model.json"
        path.write_text(json.dumps(model))
        out = self.root / "model-inputs"
        self.cli.invoke("model", "create", path, "--out", out)
        mapping = check_m3_mapping(out, spec)
        self.assertEqual(mapping["geometry/waterlevini"], .25)
        self.assertEqual(mapping["physics/uniffrictcoef"], .041)
        self.assertEqual((out / "mesh_net.nc").read_bytes(), mesh.read_bytes())
        self.assertEqual(result["mdu_settings"]["physics/UnifFrictCoef"], .041)


class IndependentTopologyOracle(unittest.TestCase):
    def test_oracle_rejects_t_junction_even_when_area_and_face_orientation_hold(self):
        points = [(0, 0), (1, 0), (1, 2), (0, 2), (2, 0), (2, 1), (1, 1), (2, 2)]
        faces = [(0, 1, 2, 3), (1, 4, 5, 6), (6, 5, 7, 2)]
        edges = list({tuple(sorted((a, b))) for f in faces for a, b in zip(f, f[1:]+f[:1])})
        with self.assertRaisesRegex(AssertionError, "T junction"):
            topology(points, faces, edges, 4)

    def test_oracle_rejects_reverse_duplicate_edges_and_dangling_nodes(self):
        nodes = [(0, 0), (1, 0), (1, 1), (0, 1)]
        faces = [(0, 1, 2, 3)]
        edges = [(0, 1), (1, 2), (2, 3), (0, 3)]
        self.assertEqual(topology(nodes, faces, edges, 1)["area_m2"], 1)
        for n, f, e in [(nodes, [tuple(reversed(faces[0]))], edges),
                        (nodes, faces, edges+[edges[0]]), (nodes+[(2, 2)], faces, edges)]:
            with self.subTest(nodes=n, faces=f, edges=e), self.assertRaises(AssertionError):
                topology(n, f, e, 1)


if __name__ == "__main__":
    unittest.main()
