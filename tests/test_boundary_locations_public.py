"""Independent B04-PLI-V subprocess CLI cases. No GUI/native or private oracle."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_boundary_locations_fixture import (
    ARTIFACT_ROOT, Fixture, INVENTORY, PublicAPI, author_target_last, directories, edges, fingerprints, forcing,
    require_raw_bc, save, sections, sha, snapshot, support_ids, verify_copy, without_authored_blocks, xy,
)


class BoundaryLocationsPublicTests(unittest.TestCase):
    def setUp(self):
        artifact_root = ARTIFACT_ROOT.get()
        if artifact_root:
            self.root = artifact_root / self._testMethodName
            self.root.mkdir(exist_ok=False)
        else:
            temp = tempfile.TemporaryDirectory(prefix="B04-PLI-V-")
            self.addCleanup(temp.cleanup)
            self.root = Path(temp.name)
        self.fixture = Fixture(self.root / "fixture")
        self.api = PublicAPI(self.root / "public-api")

    def success(self, **options):
        row = self.api.call(self.fixture, **options)
        self.assertTrue(row["ok"], row)
        return row["result"]

    def refuse(self, suffix=None, **options):
        before = snapshot(self.fixture.root)
        before_dirs = directories(self.fixture.root)
        row = self.api.call(self.fixture, **options)
        self.assertFalse(row["ok"], row)
        self.assertNotIn("unexpected_exception", row)
        self.assertEqual(snapshot(self.fixture.root), before, "Refusal wrote or deleted files")
        self.assertEqual(directories(self.fixture.root), before_dirs, "Refusal changed directories")
        if suffix:
            expected = {"boundary_locations_" + suffix}
            if suffix == "usage":
                expected.add("usage")  # argparse's missing/invalid required option
            self.assertIn(row["error"]["code"], expected, row)
        self.assertNotIn(row["error"]["code"], ("internal_error", "io_or_data_error"))
        return row["error"]

    def refuse_declarations(self, **options):
        error = self.refuse("usage", **options)
        self.assertEqual(error["code"], "boundary_locations_usage", "Declaration must reach the public importer, not fail as an unknown CLI option")
        self.assertEqual(error["exit_code"], 2, "Missing/forbidden declarations must fail before opaque mesh/dependency work")
        return error

    def apply(self, replacement=True):
        before = snapshot(self.fixture.model)
        source = self.fixture.source.read_bytes()
        preview_before = snapshot(self.fixture.root)
        preview_dirs = directories(self.fixture.root)
        preview = self.success()
        self.assertEqual(snapshot(self.fixture.root), preview_before, "Preview wrote files")
        self.assertEqual(directories(self.fixture.root), preview_dirs, "Preview changed directories")
        self.assertFalse(self.fixture.out.exists())
        result = self.success(apply=True, expect_sha256=preview["input_sha256"])
        self.assertEqual(source, self.fixture.source.read_bytes(), "Incoming source was edited")
        self.assertEqual(result["input_sha256"], preview["input_sha256"])
        self.assertEqual(result["applied"], True)
        independent = verify_copy(self.fixture, before, result, replacement=replacement)
        save(self.root / "independent-checks.json", {"passed": True, "replacement": replacement,
             "checked_before_any_deliberate_oracle_mutation": True, **independent,
             "observed_output_files": fingerprints(self.fixture.out)})
        return result

    def test_same_basename_and_label_clears_all_target_quantities_functions_only(self):
        self.assertEqual(len(forcing(self.fixture.bc.read_bytes())), 21)
        self.assertEqual(len(edges(self.fixture.ext.read_bytes())), 6)
        result = self.apply()
        self.assertEqual(result["operation"], "replace_geometry_clear_all_forcing")
        self.assertEqual(len(forcing((self.fixture.out / "signals.bc").read_bytes())), 10)

    def test_target_last_east_removal_preserves_west_signals_and_EOF_bytes(self):
        f = self.fixture
        signals, ext_blocks, bc_prefix, ext_prefix = author_target_last(f)
        self.assertFalse(f.bc.read_bytes().endswith(b"\n"))
        self.assertFalse(f.ext.read_bytes().endswith(b"\n"))
        self.assertEqual(len(forcing(f.bc.read_bytes())), 18)
        self.assertEqual(len(edges(f.ext.read_bytes())), 6)
        before = snapshot(f.root)
        dirs_before = directories(f.root)
        baseline = snapshot(f.model)
        preview = self.success()
        self.assertEqual(snapshot(f.root), before, "Target-last preview wrote files")
        self.assertEqual(directories(f.root), dirs_before)
        self.assertFalse(f.out.exists())
        result = self.success(apply=True, expect_sha256=preview["input_sha256"])
        self.assertEqual(snapshot(f.model), baseline, "Target-last apply edited original model")
        self.assertEqual(f.source.read_bytes(), before[f.source.relative_to(f.root).as_posix()])
        after = snapshot(f.out)
        for name, raw in baseline.items():
            if name not in {"east.pli", "signals.bc", "conditions.ext"}:
                self.assertEqual(after[name], raw, "Non-target byte change: " + name)
        self.assertEqual(xy(after["east.pli"]), xy(f.source.read_bytes()))
        self.assertEqual(after["west.pli"], baseline["west.pli"])
        self.assertEqual([b["fields"] for b in forcing(after["signals.bc"])],
                         [sections(raw)[0]["fields"] for raw in signals["west"]],
                         "Trailing east removal lost west signals or left active east data")
        self.assertEqual(edges(after["conditions.ext"]), [sections(raw)[0]["fields"] for raw in ext_blocks["west"]])
        # Do not normalize comments or only count active sections: physically
        # retired target bytes must be absent even at the last numeric tail.
        require_raw_bc(after["signals.bc"], bc_prefix + b"".join(signals["west"]))
        self.assertTrue(after["conditions.ext"].startswith(ext_prefix + b"".join(ext_blocks["west"])), "West EXT bytes changed")
        self.assertFalse(after["conditions.ext"].endswith(b"\n"), "Last-target EXT EOF newline changed")
        archive = f.out / ".dfm-boundary-locations/imports" / result["input_sha256"]
        for name in ("east.pli", "signals.bc", "conditions.ext"):
            self.assertEqual((archive / "originals" / name).read_bytes(), baseline[name], "Wrong target-last before-image")
        self.assertEqual((archive / "source/east.pli").read_bytes(), f.source.read_bytes())
        inventory = json.loads(after[INVENTORY])
        objects = {o["label"]:o for o in inventory["objects"]}
        self.assertEqual(objects["east"]["status"], "unbound")
        self.assertEqual(objects["east"]["engine_bindings"], [])
        self.assertEqual(objects["west"]["status"], "engine_bound")
        self.assertEqual(len(objects["west"]["engine_bindings"]), 3)
        self.assertEqual(inventory["output_files"], {k:v for k,v in fingerprints(f.out).items() if k != INVENTORY})
        self.assertEqual(sha(after[INVENTORY]), result["inventory_sha256"])
        save(self.root / "target-last-independent-checks.json", {"passed_file_checks": True,
             "target": "east", "target_position": "last_BC_and_EXT_blocks_at_EOF_without_newline",
             "raw_BC_policy": "exact original prefix+west blocks only; east byte slices physically absent, complete original EOF bytes archived",
             "west_active_forcing_blocks": 9, "west_active_EXT_edges": 3,
             "original_model_unchanged": True, "west_and_unknown_bytes_preserved": True,
             "native_execution": "not_performed", "native_validity": "not_established",
             "actual_output_files": fingerprints(f.out)})

    def test_target_first_west_removal_preserves_east_numeric_tail_exactly(self):
        f = self.fixture
        signals, ext_blocks, _, _ = author_target_last(f)
        f.write_source(label="west", basename="west.pli")
        original = snapshot(f.model)
        source = f.source.read_bytes()
        before = snapshot(f.root)
        before_dirs = directories(f.root)
        preview = self.success()
        self.assertEqual(snapshot(f.root), before)
        self.assertEqual(directories(f.root), before_dirs)
        self.assertFalse(f.out.exists())
        result = self.success(apply=True, expect_sha256=preview["input_sha256"])
        self.assertEqual(snapshot(f.model), original)
        self.assertEqual(f.source.read_bytes(), source)
        actual = snapshot(f.out)
        for name, raw in original.items():
            if name not in {"west.pli", "signals.bc", "conditions.ext"}:
                self.assertEqual(actual[name], raw, "West removal changed unselected file: " + name)
        require_raw_bc(actual["signals.bc"], without_authored_blocks(original["signals.bc"], signals["west"]))
        self.assertEqual([b["fields"] for b in forcing(actual["signals.bc"])],
                         [sections(raw)[0]["fields"] for raw in signals["east"]])
        self.assertEqual(edges(actual["conditions.ext"]), [sections(raw)[0]["fields"] for raw in ext_blocks["east"]])
        self.assertFalse(actual["signals.bc"].endswith(b"\n"), "Unselected east EOF bytes changed")
        self.assertEqual(xy(actual["west.pli"]), xy(source))
        archive = f.out / ".dfm-boundary-locations/imports" / result["input_sha256"]
        for name in ("west.pli", "signals.bc", "conditions.ext"):
            self.assertEqual((archive / "originals" / name).read_bytes(), original[name])
        self.assertEqual((archive / "source/west.pli").read_bytes(), source)
        inventory = json.loads(actual[INVENTORY])
        objects = {o["label"]:o for o in inventory["objects"]}
        self.assertEqual(objects["west"]["status"], "unbound")
        self.assertEqual(objects["west"]["engine_bindings"], [])
        self.assertEqual(objects["east"]["status"], "engine_bound")
        self.assertEqual(len(objects["east"]["engine_bindings"]), 3)
        self.assertEqual(inventory["output_files"], {k:v for k,v in fingerprints(f.out).items() if k != INVENTORY})
        self.assertEqual(sha(actual[INVENTORY]), result["inventory_sha256"])
        save(self.root / "target-first-independent-checks.json", {"passed_file_checks": True,
             "target": "west", "target_position": "first_BC_blocks; unselected east numeric tail at EOF",
             "east_active_forcing_blocks": 9, "east_active_EXT_edges": 3,
             "raw_BC_exact_original_minus_selected_slices": True, "original_model_unchanged": True,
             "native_execution": "not_performed", "native_validity": "not_established",
             "actual_output_files": fingerprints(f.out)})

    def test_new_basename_and_new_label_is_unforced_addition(self):
        self.fixture.write_source(label="estuary", basename="estuary.pli")
        self.assertEqual(self.apply(False)["operation"], "add_unbound_geometry")

    def test_same_basename_new_label_is_unforced_not_replacement(self):
        self.fixture.write_source(label="estuary", basename="north.pli")
        self.assertEqual(self.apply(False)["operation"], "add_unbound_geometry")

    def test_existing_label_different_basename_is_ambiguous(self):
        self.fixture.write_source(label="north", basename="different.pli")
        self.refuse("ambiguous")

    def test_case_only_internal_label_collision_refused(self):
        self.fixture.write_source(label="North")
        self.refuse("ambiguous")

    def test_case_only_basename_collision_refused(self):
        self.fixture.write_source(basename="NORTH.pli")
        self.assertEqual(self.fixture.source.resolve().name, "NORTH.pli")
        self.refuse("ambiguous")

    def test_new_label_with_case_alias_basename_refused(self):
        self.fixture.write_source(label="estuary", basename="NORTH.pli")
        self.assertEqual(self.fixture.source.resolve().name, "NORTH.pli")
        self.refuse("ambiguous")

    def test_duplicate_existing_internal_labels_refused(self):
        p = self.fixture.model / "south.pli"
        p.write_bytes(p.read_bytes().replace(b"  south  #", b"  north  #"))
        self.refuse("ambiguous")

    def test_selected_support_is_another_line_label_refused(self):
        p = self.fixture.model / "south.pli"
        p.write_bytes(p.read_bytes().replace(b"  south  #", b"  north_0001  #"))
        self.refuse("ambiguous")

    def test_apply_requires_explicit_preview_consent(self):
        self.refuse("usage", apply=True)

    def test_wrong_preview_hash_refused(self):
        self.refuse("stale", apply=True, expect_sha256="0" * 64)

    def test_preview_hash_is_bound_to_output_directory(self):
        preview = self.success()
        self.fixture.out = self.fixture.root / "a different copy"
        self.refuse("stale", apply=True, expect_sha256=preview["input_sha256"])

    def test_preview_hash_binds_source_bytes_despite_same_size_and_mtime(self):
        preview = self.success()
        p = self.fixture.source
        info = p.stat()
        old = p.read_bytes()
        new = old.replace(b"205.500", b"206.500", 1)
        self.assertNotEqual(old, new)
        self.assertEqual(len(old), len(new))
        p.write_bytes(new)
        os.utime(p, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual((p.stat().st_size, p.stat().st_mtime_ns), (info.st_size, info.st_mtime_ns))
        save(self.root / "source-mutation.json", {"before_sha256": sha(old), "after_sha256": sha(new),
             "before_size": info.st_size, "after_size": p.stat().st_size,
             "before_mtime_ns": info.st_mtime_ns, "after_mtime_ns": p.stat().st_mtime_ns,
             "preview_input_sha256": preview["input_sha256"]})
        self.refuse("stale", apply=True, expect_sha256=preview["input_sha256"])

    def test_preview_hash_binds_opaque_model_bytes_same_size_and_mtime(self):
        preview = self.success()
        p = self.fixture.model / "geometry/grid.nc"
        info = p.stat()
        p.write_bytes(p.read_bytes().replace(b"sentinel", b"SENTINEL"))
        os.utime(p, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual((p.stat().st_size, p.stat().st_mtime_ns), (info.st_size, info.st_mtime_ns))
        self.refuse("stale", apply=True, expect_sha256=preview["input_sha256"])

    def test_preview_hash_binds_unknown_files_and_empty_directories(self):
        preview = self.success()
        (self.fixture.model / "new empty").mkdir()
        self.refuse("stale", apply=True, expect_sha256=preview["input_sha256"])

    def test_explicit_coordinate_mode_required(self):
        self.refuse("usage", coordinates=None)

    def test_transform_is_refused_with_explicit_horizontal_CRS(self):
        # Supersedes the v1 blanket transform refusal: this exact request still
        # lacks BOTH mandatory units and must not reach the transform adapter.
        self.refuse_declarations(coordinates="transform", source_crs="EPSG:4326", target_crs="EPSG:28992")

    def test_as_is_does_not_silently_transform_or_accept_CRS_reconciliation(self):
        self.refuse_declarations(source_crs="EPSG:4326", target_crs="EPSG:28992")

    def test_as_is_rejects_source_CRS_flag_alone(self):
        self.refuse_declarations(source_crs="EPSG:4326")

    def test_as_is_rejects_target_CRS_flag_alone(self):
        self.refuse_declarations(target_crs="EPSG:32631")

    def test_as_is_rejects_source_unit_flag_alone(self):
        self.refuse_declarations(source_unit="degree")

    def test_as_is_rejects_target_unit_flag_alone(self):
        self.refuse_declarations(target_unit="m")

    def test_transform_missing_only_source_unit_is_usage_before_mesh(self):
        self.refuse_declarations(coordinates="transform", source_crs="EPSG:4326", target_crs="EPSG:32631", target_unit="m")

    def test_transform_missing_only_target_unit_is_usage_before_mesh(self):
        self.refuse_declarations(coordinates="transform", source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="degree")

    def test_transform_missing_only_source_CRS_is_usage_before_mesh(self):
        self.refuse_declarations(coordinates="transform", target_crs="EPSG:32631", source_unit="degree", target_unit="m")

    def test_transform_missing_only_target_CRS_is_usage_before_mesh(self):
        self.refuse_declarations(coordinates="transform", source_crs="EPSG:4326", source_unit="degree", target_unit="m")

    def test_transform_rejects_noncanonical_unit_word_at_public_parser(self):
        error = self.refuse("usage", coordinates="transform", source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="metre", target_unit="m")
        self.assertEqual(error["code"], "usage")
        self.assertEqual(error["exit_code"], 2)

    def test_as_is_retains_exact_decimal_values_without_datum_claim(self):
        self.fixture.source.write_bytes(b"north\n3 2\n1.12345678901234567 2.125\n3.5D+1 -0\n4.5e1 6.2500\n")
        result = self.apply()
        self.assertEqual(xy((self.fixture.out / "north.pli").read_bytes()), xy(self.fixture.source.read_bytes()))
        self.assertFalse(result["planned_inventory"]["CRS"]["common_CRS_asserted"])

    def test_fresh_output_refuses_existing_foreign_directory(self):
        self.fixture.out.mkdir()
        (self.fixture.out / "foreign.bin").write_bytes(b"keep me")
        self.refuse("output")
        self.assertEqual((self.fixture.out / "foreign.bin").read_bytes(), b"keep me")

    def test_output_inside_model_refused(self):
        self.fixture.out = self.fixture.model / "copy"
        self.refuse("overlap")

    def test_reference_escape_refused(self):
        self.fixture.ext.write_bytes(self.fixture.ext.read_bytes().replace(b"locationFile = north.pli", b"locationFile = ../external sources/north.pli"))
        self.refuse("reference")

    def test_absolute_reference_refused(self):
        self.fixture.ext.write_bytes(self.fixture.ext.read_bytes().replace(b"locationFile = north.pli", b"locationFile = C:/foreign/north.pli"))
        self.refuse("reference")

    def test_source_with_vertical_coordinate_refused(self):
        self.fixture.source.write_bytes(b"north\n2 3\n1 2 3\n4 5 6\n")
        self.refuse("pli")

    def test_multiline_source_refused_instead_of_partial_import(self):
        self.fixture.source.write_bytes(self.fixture.source.read_bytes() + b"other\n2 2\n1 2\n3 4\n")
        self.refuse("pli")

    def test_multiline_existing_PLI_refused_instead_of_other_line_loss(self):
        p = self.fixture.model / "north.pli"
        p.write_bytes(p.read_bytes() + b"other\n2 2\n1 2\n3 4\n")
        self.refuse("pli")

    def test_nonfinite_coordinates_refused(self):
        self.fixture.source.write_bytes(b"north\n2 2\nNaN 1\n2 3\n")
        self.refuse("coordinates")

    def test_two_point_replacement_preserves_original_comment_rows(self):
        self.fixture.write_source(count=2)
        self.apply()

    def test_four_point_replacement_retains_other_line_bytes(self):
        self.fixture.write_source(count=4)
        self.apply()

    def test_new_unbound_line_can_be_replaced_without_creating_EXT_binding(self):
        f = self.fixture
        f.write_source(label="estuary", basename="estuary.pli")
        first = self.apply(False)
        prior_out = f.out
        before = snapshot(prior_out)
        f.mdu = prior_out / f.mdu.name
        f.out = f.root / "second new copy"
        f.source.write_bytes(f.source.read_bytes().replace(b"205.500", b"305.500"))
        p = self.success()
        result = self.success(apply=True, expect_sha256=p["input_sha256"])
        self.assertEqual(snapshot(prior_out), before, "Prior working copy mutated")
        for name in ("conditions.ext", "signals.bc", "north.pli", "south.pli"):
            self.assertEqual((f.out / name).read_bytes(), before[name])
        obj = result["imported_object"]
        self.assertEqual(obj["status"], "unbound")
        self.assertEqual(obj["engine_bindings"], [])
        self.assertEqual(xy((f.out / obj["path"]).read_bytes()), xy(f.source.read_bytes()))
        self.assertNotEqual(first["input_sha256"], result["input_sha256"])

    def test_last_active_boundary_disconnects_MDU_reference(self):
        f = self.fixture
        f.ext.write_bytes(f.ext.read_bytes().split(b"[Boundary]", 1)[0] + b"".join(raw for line, _, raw in f.ext_blocks if line == "north"))
        before = snapshot(f.model)
        p = self.success()
        r = self.success(apply=True, expect_sha256=p["input_sha256"])
        self.assertEqual(snapshot(f.model), before)
        self.assertEqual(edges((f.out / "conditions.ext").read_bytes()), [])
        mdu = sections((f.out / f.mdu.name).read_bytes())
        ext_section = next(s for s in mdu if s["kind"] == "external forcing")
        self.assertEqual(ext_section["fields"]["extforcefilenew"], [""])
        self.assertIn(b"# retain inline note", (f.out / f.mdu.name).read_bytes())
        self.assertEqual((f.out / "south.pli").read_bytes(), before["south.pli"])
        archive = f.out / ".dfm-boundary-locations/imports" / r["input_sha256"] / "originals"
        self.assertEqual((archive / f.mdu.name).read_bytes(), before[f.mdu.name])

    def test_hardlinked_source_refused(self):
        os.link(self.fixture.source, self.fixture.incoming / "hardlink.pli")
        self.refuse("path")

    def test_public_preview_reports_file_only_scope(self):
        p = self.success()
        self.assertEqual(p["native_execution"], "not_performed")
        self.assertEqual(p["GUI_parity"], "not_established")
        self.assertEqual(p["planned_inventory"]["engine_initialization"], "not_performed")
        self.assertEqual(p["planned_inventory"]["scientific_validation"], "not_performed")

    def test_actual_public_schema_exposes_exact_as_is_contract(self):
        row = self.api.invoke(["schema", "inspect"])
        self.assertTrue(row["ok"], row)
        schema = row["result"]
        self.assertIn("boundary location-import", schema["commands"])
        contract = schema["boundary_location_import"]
        self.assertEqual(contract["contract"], "boundary-location-import-v1")
        # Contract ID stays v1 for prior-sidecar chaining; the advertised
        # coordinate capabilities change only after public integration.
        self.assertEqual(contract["supported_coordinates"], ["as-is", "transform"])
        self.assertNotIn("transform", contract.get("unsupported_coordinates", {}))
        for flag in ("--source-crs", "--target-crs", "--source-unit", "--target-unit"):
            self.assertIn(flag, contract["command"])
        self.assertIn("--apply --expect-sha256", contract["command"])

    def test_oracle_rejects_restored_target_signal_even_with_success_report(self):
        before = snapshot(self.fixture.model)
        report = self.apply()
        p = self.fixture.out / "signals.bc"
        p.write_bytes(p.read_bytes() + self.fixture.signal_blocks[0][1])
        with self.assertRaisesRegex(AssertionError, "surviving forcing"):
            verify_copy(self.fixture, before, report, replacement=True)

    def test_raw_oracle_rejects_commented_retired_records_after_numeric_tail(self):
        signals, _, prefix, _ = author_target_last(self.fixture)
        expected = prefix + b"".join(signals["west"])
        retired = b"".join(signals["east"]).rstrip(b"\r\n")
        poisoned = expected + b"".join(b"# deliberately retired: " + line for line in retired.splitlines(keepends=True))
        self.assertEqual([b["fields"] for b in forcing(poisoned)], [b["fields"] for b in forcing(expected)],
                         "Sensitivity fixture must be invisible to active-section normalization")
        with self.assertRaisesRegex(AssertionError, "RAW BC RETIREMENT ALERT"):
            require_raw_bc(poisoned, expected)

    def test_oracle_rejects_non_target_block_metadata_corruption(self):
        before = snapshot(self.fixture.model)
        report = self.apply()
        p = self.fixture.out / "signals.bc"
        p.write_bytes(p.read_bytes().replace(b"keep-110", b"DROP-110"))
        with self.assertRaisesRegex(AssertionError, "surviving forcing|Non-target"):
            verify_copy(self.fixture, before, report, replacement=True)

    def test_oracle_rejects_new_geometry_falsely_wired_to_EXT(self):
        self.fixture.write_source(label="estuary", basename="estuary.pli")
        before = snapshot(self.fixture.model)
        report = self.apply(False)
        p = self.fixture.out / "conditions.ext"
        p.write_bytes(p.read_bytes() + b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=.dfm-boundary-locations/objects/estuary/estuary.pli\nforcingFile=signals.bc\n")
        with self.assertRaisesRegex(AssertionError, "Non-target original bytes"):
            verify_copy(self.fixture, before, report, replacement=False)

    def test_oracle_rejects_changed_coordinates_despite_unchanged_producer_report(self):
        before = snapshot(self.fixture.model)
        report = self.apply()
        p = self.fixture.out / "north.pli"
        p.write_bytes(p.read_bytes().replace(b"205.500", b"999.500", 1))
        with self.assertRaisesRegex(AssertionError, "replacement coordinates"):
            verify_copy(self.fixture, before, report, replacement=True)

    def add_existing_text_ids(self):
        p = self.fixture.model / "north.pli"
        raw = p.read_bytes()
        for i, note in enumerate((b"first-support", b"middle-support", b"end-support"), 1):
            raw = raw.replace(b"# " + note, f"north_{i:04d} # ".encode() + note)
        p.write_bytes(raw)
        return raw

    def test_canonical_source_text_IDs_are_not_height_and_archive_exactly(self):
        self.fixture.source.write_bytes(b"north\n3 2\n205.500 31.250 north_0001\n205.500 41.250 north_0002\n205.500 51.250 north_0003\n")
        self.apply()
        self.assertEqual(support_ids((self.fixture.out / "north.pli").read_bytes()), [None]*3)

    def test_existing_text_IDs_preserved_with_unlabelled_source(self):
        before = self.add_existing_text_ids()
        self.apply()
        raw = (self.fixture.out / "north.pli").read_bytes()
        self.assertEqual(support_ids(raw), ["north_0001", "north_0002", "north_0003"])
        expected = before.replace(b"101.250", b"205.500").replace(b"11.00", b"31.250").replace(b"22.00", b"41.250").replace(b"33.00", b"51.250")
        self.assertEqual(raw, expected, "Text ID/spacing/comment bytes changed beyond requested XY tokens")

    def test_text_IDs_survive_growth_with_new_canonical_ID(self):
        self.add_existing_text_ids()
        self.fixture.write_source(count=4)
        self.apply()
        self.assertEqual(support_ids((self.fixture.out / "north.pli").read_bytes()),
                         ["north_0001", "north_0002", "north_0003", "north_0004"])

    def test_text_ID_shrink_removes_obsolete_ID_but_retains_its_comment(self):
        self.add_existing_text_ids()
        self.fixture.write_source(count=2)
        self.apply()
        raw = (self.fixture.out / "north.pli").read_bytes()
        self.assertEqual(support_ids(raw), ["north_0001", "north_0002"])
        self.assertNotIn(b"north_0003", raw)
        self.assertIn(b"# end-support", raw)

    def test_new_unbound_text_ID_geometry_retains_exact_source_bytes(self):
        self.fixture.write_source(label="estuary", basename="north.pli")
        self.fixture.source.write_bytes(b"estuary\n2 2\n205.500 31.250 estuary_0001\n205.500 41.250 estuary_0002\n")
        r = self.apply(False)
        raw = (self.fixture.out / r["imported_object"]["path"]).read_bytes()
        self.assertEqual(raw, self.fixture.source.read_bytes())
        self.assertEqual(support_ids(raw), ["estuary_0001", "estuary_0002"])

    def test_numeric_third_value_with_declared_XY_is_not_a_text_ID(self):
        self.fixture.source.write_bytes(b"north\n2 2\n1 2 3\n4 5 6\n")
        self.refuse("pli")

    def test_repeated_text_support_ID_refused(self):
        self.fixture.source.write_bytes(b"north\n2 2\n1 2 north_0001\n4 5 north_0001\n")
        self.refuse("pli")

    def test_text_support_ID_with_wrong_line_label_refused(self):
        self.fixture.source.write_bytes(b"north\n2 2\n1 2 south_0001\n4 5 south_0002\n")
        self.refuse("pli")

    def test_out_of_order_text_support_ID_refused(self):
        self.fixture.source.write_bytes(b"north\n2 2\n1 2 north_0002\n4 5 north_0001\n")
        self.refuse("pli")

    def test_invalid_existing_text_support_ID_refused_before_copy(self):
        self.add_existing_text_ids()
        p = self.fixture.model / "north.pli"
        p.write_bytes(p.read_bytes().replace(b"north_0002", b"north_0001"))
        self.refuse("pli")

    def test_labelled_source_coordinate_change_same_size_mtime_invalidates_preview(self):
        self.fixture.source.write_bytes(b"north\n2 2\n1 2 north_0001\n4 5 north_0002\n")
        p = self.success()
        source = self.fixture.source
        info = source.stat()
        source.write_bytes(source.read_bytes().replace(b"1 2 north_0001", b"1 3 north_0001"))
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual((source.stat().st_size, source.stat().st_mtime_ns), (info.st_size, info.st_mtime_ns))
        self.refuse("stale", apply=True, expect_sha256=p["input_sha256"])

    def prepare_prior_inventory(self):
        """Obtain a real prior inventory through public CLI, never fabricate one."""
        f = self.fixture
        f.write_source(label="estuary", basename="estuary.pli")
        self.apply(False)
        prior = f.out
        f.mdu = prior / f.mdu.name
        f.out = f.root / "second working copy"
        f.source.write_bytes(f.source.read_bytes().replace(b"205.500", b"305.500"))
        inventory = prior / INVENTORY
        original = inventory.read_bytes()
        (self.root / "prior-inventory-before-adversary.json").write_bytes(original)
        preview = self.success()
        self.assertFalse(f.out.exists(), "Canonical prior-inventory preview created output")
        return prior, inventory, json.loads(original), preview

    def refuse_corrupt_prior_inventory(self, mutation):
        prior, inventory, document, valid_preview = self.prepare_prior_inventory()
        replacement = mutation(document)
        if replacement is not None:
            document = replacement
        # JSON can encode a lone surrogate as an ASCII escape. Exercise the
        # public reader/error boundary rather than failing in our UTF-8 writer.
        inventory.write_bytes((json.dumps(document, ensure_ascii=True, indent=2) + "\n").encode("ascii"))
        before = snapshot(self.fixture.root)
        before_dirs = directories(self.fixture.root)
        row = None
        try:
            row = self.api.call(self.fixture, apply=True, expect_sha256=valid_preview["input_sha256"])
        finally:
            # Also check preservation when a buggy CLI crashes or returns exit70.
            state = {"entire_existing_fixture_bytes_unchanged": snapshot(self.fixture.root) == before,
                     "existing_directories_unchanged": directories(self.fixture.root) == before_dirs,
                     "output_absent": not self.fixture.out.exists()}
            save(self.root / "prior-inventory-preservation.json", state)
            self.assertTrue(state["entire_existing_fixture_bytes_unchanged"], "Corrupt inventory attempt changed existing copy/source bytes")
            self.assertTrue(state["existing_directories_unchanged"], "Corrupt inventory attempt changed directories")
            self.assertTrue(state["output_absent"], "Corrupt prior inventory created an output/partial copy")
        self.assertEqual(row["returncode"], 3, row)
        self.assertFalse(row["ok"], row)
        self.assertTrue(row["error"]["code"].startswith("boundary_locations_"), row)
        self.assertNotIn(row["error"]["code"], {"internal_error", "boundary_locations_stale", "usage"})
        save(self.root / "prior-inventory-refusal-checks.json", {"passed": True,
             "returncode": row["returncode"], "diagnostic_code": row["error"]["code"],
             "prior_copy": str(prior), "entire_existing_fixture_unchanged": True,
             "output_absent": True, "actual_existing_files": fingerprints(self.fixture.root)})

    def test_prior_inventory_dot_prefixed_active_object_is_exit3_no_output(self):
        def corrupt(document):
            obj = next(o for o in document["objects"] if o["label"] == "north")
            self.assertEqual(obj["path"], "north.pli")
            obj["path"] = "./north.pli"
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_dot_prefixed_unbound_object_is_exit3_no_output(self):
        def corrupt(document):
            obj = next(o for o in document["objects"] if o["label"] == "estuary")
            self.assertIn("/objects/estuary/", obj["path"])
            obj["path"] = "./" + obj["path"]
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_backslash_alias_is_exit3_no_output(self):
        def corrupt(document):
            obj = next(o for o in document["objects"] if o["label"] == "estuary")
            obj["path"] = obj["path"].replace("/", "\\")
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_duplicate_canonical_object_is_exit3_no_output(self):
        def corrupt(document):
            document["objects"].append(dict(document["objects"][0]))
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_non_object_root_is_exit3_no_output(self):
        self.refuse_corrupt_prior_inventory(lambda document: [])

    def test_prior_inventory_wrong_kind_is_exit3_no_output(self):
        def corrupt(document):
            document["kind"] = "unrecognized_inventory_kind"
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_wrong_MDU_identity_is_exit3_no_output(self):
        def corrupt(document):
            document["mdu"] = "other-model.mdu"
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_wrong_objects_type_is_exit3_no_output(self):
        def corrupt(document):
            document["objects"] = {"north": document["objects"][0]}
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_non_object_record_is_exit3_no_output(self):
        def corrupt(document):
            document["objects"].append(False)
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_non_string_digest_is_exit3_no_output(self):
        def corrupt(document):
            document["objects"][0]["sha256"] = True
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_case_alias_duplicate_is_exit3_no_output(self):
        def corrupt(document):
            alias = dict(next(o for o in document["objects"] if o["label"] == "estuary"))
            alias["path"] = alias["path"].upper()
            document["objects"].append(alias)
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_canonical_missing_file_is_exit3_no_output(self):
        def corrupt(document):
            obj = next(o for o in document["objects"] if o["label"] == "estuary")
            obj["path"] = ".dfm-boundary-locations/objects/estuary/missing.pli"
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_lone_surrogate_path_is_exit3_no_output(self):
        def corrupt(document):
            obj = next(o for o in document["objects"] if o["label"] == "estuary")
            obj["path"] = ".dfm-boundary-locations/objects/estuary/\ud800.pli"
        self.refuse_corrupt_prior_inventory(corrupt)

    def test_prior_inventory_canonical_forward_slash_reference_reimports(self):
        prior, inventory, document, preview = self.prepare_prior_inventory()
        obj = next(o for o in document["objects"] if o["label"] == "estuary")
        path = ".dfm-boundary-locations/objects/estuary/estuary.pli"
        self.assertEqual(obj["path"], path)
        self.assertEqual(obj["engine_bindings"], [])
        before = snapshot(prior)
        before_dirs = directories(prior)
        result = self.success(apply=True, expect_sha256=preview["input_sha256"])
        self.assertEqual(snapshot(prior), before, "Canonical reimport edited prior copy")
        self.assertEqual(directories(prior), before_dirs)
        after = snapshot(self.fixture.out)
        for name, raw in before.items():
            if name not in {path, INVENTORY}:
                self.assertEqual(after[name], raw, "Canonical reimport changed non-target bytes: " + name)
        self.assertEqual(xy(after[path]), xy(self.fixture.source.read_bytes()))
        self.assertEqual(result["imported_object"]["path"], path)
        self.assertEqual(result["imported_object"]["status"], "unbound")
        self.assertEqual(result["imported_object"]["engine_bindings"], [])
        self.assertEqual(len(edges(after["conditions.ext"])), 6)
        self.assertEqual(len(forcing(after["signals.bc"])), 21)
        final = json.loads(after[INVENTORY])
        self.assertEqual(final["output_files"], {k:v for k,v in fingerprints(self.fixture.out).items() if k != INVENTORY})
        self.assertEqual(sha(after[INVENTORY]), result["inventory_sha256"])


if __name__ == "__main__":
    unittest.main()
