"""Independent B11 public contract tests: hand-authored bytes, no I helpers.

Only the public CLI entry point is imported from the product. All selected block
spans, coefficient ordering/defaults, raw rows and expected edits are read here.
No optional scientific packages or installed suite are required.
"""
import base64
import contextlib
from contextlib import ExitStack
from decimal import Decimal
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch


MDU = """# independent portable B11 model; mesh is opaque here
[General]
FileVersion = 1.09
FileType = modelDef
Program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh.nc
Kmx = 0
BedlevType = 3
WaterLevIni = 0
[time]
RefDate = 20260101
TZone = 0
TUnit = S
TStart = 0
TStop = 120
StartDateTime = 20260101000000
StopDateTime = 20260101000200
[external forcing]
ExtForceFile =
ExtForceFileNew = boundaries.ext
[output]
HisInterval = 10
MapInterval = 10
"""
EXT = """[General]
fileVersion = 2.01
fileType = extForce
[Boundary]
quantity = waterlevelbnd
locationFile = east.pli
forcingFile = signals.bc
[Boundary]
quantity = waterlevelbnd
locationFile = west.pli
forcingFile = signals.bc
"""


def number(token):
    return Decimal(token.replace("D", "E").replace("d", "e"))


def independent_blocks(raw):
    """Keep byte spans/order; first Quantity separates global from late fields."""
    headers, cursor = [], 0
    for line in raw.splitlines(keepends=True):
        match = re.fullmatch(rb"[ \t]*\[([A-Za-z ]+)\][ \t]*", line.rstrip(b"\r\n"))
        if match:
            headers.append((cursor, match[1]))
        cursor += len(line)
    blocks = []
    for i, header in enumerate(headers):
        start, end = header[0], headers[i+1][0] if i+1 < len(headers) else len(raw)
        if header[1].strip().lower() != b"forcing":
            continue
        fields, rows, row_details, first_quantity = [], [], [], None
        offset = start
        first_line = len(raw[:start].splitlines())+1
        for local_line, line in enumerate(raw[start:end].splitlines(keepends=True)):
            code = line.split(b"#", 1)[0].strip()
            if code and not code.startswith((b"[", b";")):
                if b"=" in code:
                    m = re.match(rb"[ \t]*([^=]+?)\s*=[ \t]*([^#\r\n]*?)[ \t]*(?:#.*)?(?:\r\n|\r|\n)?$", line)
                    if not m:
                        raise AssertionError("Fixture field cannot be parsed independently")
                    key, value = m[1].strip().decode().lower(), m[2].decode()
                    if key == "quantity" and first_quantity is None:
                        first_quantity = offset
                    fields.append({"key": key, "value": value, "start": offset+m.start(2), "end": offset+m.end(2), "line_start": offset, "line": first_line+local_line})
                else:
                    rows.append(code.split())
                    tokens = list(re.finditer(rb"\S+", line.split(b"#", 1)[0]))
                    row_details.append({"bytes": line, "line": first_line+local_line,
                        "tokens": [{"text": t[0].decode(), "start": offset+t.start(), "end": offset+t.end()} for t in tokens]})
            offset += len(line)
        names = [f["value"] for f in fields if f["key"] == "name"]
        if len(names) != 1:
            raise AssertionError("Fixture name ambiguous")
        coefficients = {}
        for key, default in (("factor", "1"), ("offset", "0")):
            found = [f for f in fields if f["key"] == key]
            early = [f for f in found if first_quantity is not None and f["line_start"] < first_quantity]
            coefficients[key] = {"token": early[-1]["value"] if early else default,
                                 "explicit": bool(early), "occurrences": found,
                                 "late": any(f["line_start"] >= first_quantity for f in found)}
        raw_values = [[number(t.decode()) for t in row] for row in rows]
        factor, offset = [float(number(coefficients[k]["token"])) for k in ("factor", "offset")]
        effective = []
        for row in raw_values:
            if len(row) != 2:
                continue
            product = float(row[1])*factor
            value = product+offset
            effective.append({"time": str(row[0]), "raw": str(row[1]), "multiply": product, "effective": value,
                              "finite_stages": math.isfinite(product) and math.isfinite(value)})
        blocks.append({"name": names[0], "start": start, "end": end, "raw": raw[start:end],
                       "fields": fields, "first_quantity": first_quantity, "coefficients": coefficients,
                       "rows": rows, "row_details": row_details, "effective": effective})
    return blocks


def forcing(name, *, factor=None, offset=None, newline=b"\r\n"):
    lines = [b"[Forcing]", b"Name = "+name.encode(), b"Function = timeseries", b"Time-interpolation = linear"]
    if factor is not None:
        lines.append(b"  fAcToR  = "+factor.encode()+b"  # retain coefficient annotation")
    if offset is not None:
        lines.append(b"Offset\t= "+offset.encode()+b"\t# retain datum annotation")
    lines += [b"# literal Quantity below is the global-header boundary", b"Quantity = time",
              b"Unit = seconds since 2026-01-01 00:00:00 +00:00", b"Quantity = waterlevelbnd", b"Unit = m",
              b"0.000   +0.0000   # raw zero", b"60  +2.5000D-1", b"1.20E+2\t-0.125000", b""]
    return newline.join(lines)+newline


def fixture(folder, *, mixed=False, active=(1, 2, 3), newline=b"\r\n", bom=False):
    folder.mkdir(parents=True, exist_ok=True)
    (folder/"model.mdu").write_bytes(MDU.replace("\n", newline.decode()).encode())
    (folder/"boundaries.ext").write_bytes(EXT.replace("\n", newline.decode()).encode())
    (folder/"mesh.nc").write_bytes(b"opaque portable mesh marker; no NetCDF dependency")
    for name, x, count in (("east", 500120, 3), ("west", 500000, 2)):
        lines = [name, str(count)+" 2"]+[f"{x} {5700000+20*i}" for i in range(count)]
        (folder/(name+".pli")).write_bytes(newline.join(s.encode() for s in lines)+newline)
    general = (b"\xef\xbb\xbf" if bom else b"")+newline.join([b"# own mixed-case/comments fixture", b"[General]", b"fileVersion = 1.01", b"fileType = boundConds", b""])+newline
    blocks = []
    for i in active:
        f, o = (("+1.2500D+0", "-0.062500") if i == 1 else ("-0.5000", None) if i == 2 else (None, "+0.03125")) if mixed else (None, None)
        blocks.append(forcing("east_"+str(i).zfill(4), factor=f, offset=o, newline=newline))
    # West is interleaved and has pre-existing coefficients of its own.
    blocks.insert(min(1, len(blocks)), forcing("west_0001", factor="3.000", offset="0.500", newline=newline))
    blocks.append(forcing("west_0002", newline=newline))
    (folder/"signals.bc").write_bytes(general+b"".join(blocks)+b"# trailing evidence must remain byte-identical"+newline)
    return folder/"model.mdu"


def expected_edit(raw, key, literal):
    """Manual value-token splice or literal global-header line insertion."""
    patches = []
    for block in independent_blocks(raw):
        if not block["name"].startswith("east_") or not block["rows"]:
            continue
        fields = block["coefficients"][key]["occurrences"]
        if fields:
            if len(fields) != 1 or block["coefficients"][key]["late"]:
                raise AssertionError("Manual edit only defined for unique global fields")
            field, = fields
            patches.append((field["start"], field["end"], literal.encode()))
        else:
            nl = b"\r\n" if b"\r\n" in block["raw"] else b"\r" if b"\r" in block["raw"] else b"\n"
            patches.append((block["first_quantity"], block["first_quantity"], key.title().encode()+b" = "+literal.encode()+nl))
    for start, end, new in sorted(patches, reverse=True):
        raw = raw[:start]+new+raw[end:]
    return raw


class IndependentOracleSelfTests(unittest.TestCase):
    def test_defaults_and_manual_global_insertion(self):
        raw = forcing("east_0001")
        b, = independent_blocks(raw)
        self.assertFalse(b["coefficients"]["factor"]["explicit"])
        self.assertEqual([r["effective"] for r in b["effective"]], [0, .25, -.125])
        changed = expected_edit(raw, "factor", "-2")
        self.assertEqual(changed, raw.replace(b"Quantity = time", b"Factor = -2\r\nQuantity = time", 1))
        b, = independent_blocks(changed)
        self.assertEqual([r["effective"] for r in b["effective"]], [0, -.5, .25])

    def test_late_header_ignored_by_source_oracle_not_cli_admitted(self):
        raw = forcing("east_0001").replace(b"Unit = m", b"Factor = 100\r\nUnit = m")
        b, = independent_blocks(raw)
        self.assertTrue(b["coefficients"]["factor"]["late"])
        self.assertFalse(b["coefficients"]["factor"]["explicit"])
        self.assertEqual([r["effective"] for r in b["effective"]], [0, .25, -.125])


class BoundaryCoefficientsPublicTests(unittest.TestCase):
    def setUp(self):
        from dfm_cli.cli import main
        self.main = main
        temporary = tempfile.TemporaryDirectory(prefix="dfm-b11-public-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root/"model with spaces"
        self.path = fixture(self.folder)
        self.bc = self.folder/"signals.bc"
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        self.guards.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("Public coefficients must never launch a process")))
        self.guards.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("No external process allowed")))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() if p.is_file() else None for p in self.root.rglob("*")}

    def split_bc_files(self):
        raw = self.bc.read_bytes()
        blocks = independent_blocks(raw)
        general = raw[:blocks[0]["start"]]
        self.bc.write_bytes(general+b"".join(b["raw"] for b in blocks if b["name"].startswith("east_")))
        other = self.folder/"west.bc"
        other.write_bytes(general+b"".join(b["raw"] for b in blocks if b["name"].startswith("west_")))
        ext = self.folder/"boundaries.ext"
        before, after = ext.read_bytes().rsplit(b"forcingFile = signals.bc", 1)
        ext.write_bytes(before+b"forcingFile = west.bc"+after)
        return other

    def replace_with_harmonic(self, name):
        raw = self.bc.read_bytes()
        block, = [b for b in independent_blocks(raw) if b["name"] == name]
        harmonic = ("[Forcing]\r\nName = "+name+"\r\nFunction = harmonic\r\n"
                    "Quantity = harmonic component\r\nUnit = minutes\r\n"
                    "Quantity = waterlevelbnd amplitude\r\nUnit = m\r\n"
                    "Quantity = waterlevelbnd phase\r\nUnit = deg\r\n"
                    "750.0 0.1250 15.000\r\n\r\n").encode()
        self.bc.write_bytes(raw[:block["start"]]+harmonic+raw[block["end"]:])

    def cli(self, *args, boundary="east", quantity="waterlevelbnd"):
        argv = ["boundary", "coefficients", str(self.path), "--boundary", boundary, "--quantity", quantity, *map(str, args)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.main(argv)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "", "No unexpected traceback/log on public portable path")
        self.assertEqual(payload["protocol_version"], 2)
        self.assertEqual(payload["ok"], code == 0)
        evidence = os.environ.get("B11_PUBLIC_EVIDENCE")
        if evidence:
            with Path(evidence).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"test": self.id(), "argv": argv, "exit_code": code, "payload": payload}, allow_nan=False)+"\n")
        return code, payload

    def success(self, *args, **kwargs):
        code, payload = self.cli(*args, **kwargs)
        self.assertEqual(code, 0, payload)
        return payload["result"]

    def refusal(self, *args, **kwargs):
        before = self.snapshot()
        code, payload = self.cli(*args, **kwargs)
        self.assertIn(code, {2, 3, 4}, payload)
        self.assertNotEqual(payload["error"]["code"], "internal_error")
        expected = {
            "test_late_factor_after_time_quantity_refused": {"boundary_coefficients_late_coefficient"},
            "test_late_offset_after_physical_quantity_refused": {"boundary_coefficients_late_coefficient"},
            "test_duplicate_global_coefficients_even_identical_refused": {"boundary_coefficients_duplicate_coefficient"},
            "test_global_plus_late_duplicate_refused": {"boundary_coefficients_duplicate_coefficient"},
            "test_unknown_selected_metadata_refused": {"boundary_coefficients_metadata"},
            "test_multi_physical_quantity_is_not_per_column_edit": {"boundary_import_columns"},
            "test_wrong_selected_units_refused": {"boundary_import_columns"},
            "test_offset_requires_exact_explicit_m_unit": {"boundary_coefficients_units", "usage"},
            "test_factor_and_inspect_refuse_unit_claim": {"boundary_coefficients_units", "boundary_coefficients_request"},
            "test_mutually_exclusive_factor_and_offset": {"usage"},
            "test_apply_requires_change_and_preview_hash": {"expected_hash_required", "boundary_coefficients_request"},
            "test_boundary_and_quantity_exact_identity": {"boundary_import_boundary", "usage"},
            "test_argument_nonfinite_and_engine_range_refusals": {"invalid_scalar", "numeric_out_of_range", "numeric_underflow", "boundary_series_number"},
            "test_multiplication_overflow_not_hidden_by_decimal_cancellation": {"boundary_coefficients_arithmetic_overflow"},
            "test_addition_overflow_refused": {"boundary_coefficients_arithmetic_overflow"},
            "test_existing_nonfinite_coefficient_refused": {"invalid_scalar"},
            "test_wrong_clock_timezone_refused": {"boundary_series_clock"},
            "test_nonmonotonic_and_short_series_refused": {"boundary_series_time_collision", "boundary_series_coverage"},
            "test_wrong_origin_refused_when_coverage_lost": {"boundary_series_coverage"},
            "test_harmonic_not_implicitly_admitted": {"unsupported_bc"},
            "test_valid_selected_harmonic_refused_including_inspection": {"boundary_coefficients_function"},
            "test_empty_selected_line_cannot_claim_successful_edit": {"boundary_coefficients_no_active_signals"},
            "test_meteo_shared_consumer_refused": {"boundary_import_dependency"},
            "test_mdu_output_alias_refused": {"aliased_input"},
            "test_hardlinked_target_refused": {"boundary_import_alias"},
            "test_external_reference_path_refused": {"unsupported_path"},
        }.get(self._testMethodName, {"stale_preview"})
        self.assertIn(payload["error"]["code"], expected, "Unexpected refusal is not proof of the intended negative control")
        self.assertEqual(self.snapshot(), before, "Refusal must not publish any byte or temporary artifact")
        return payload["error"]

    def assert_point_evidence(self, result, before, after):
        old = {b["name"]: b for b in independent_blocks(before)}
        new = {b["name"]: b for b in independent_blocks(after)}
        points = {p["name"]: p for p in result["points"]}
        self.assertEqual(set(points), {"east_0001", "east_0002", "east_0003"})
        self.assertEqual(result["before_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(result["after_sha256"], hashlib.sha256(after).hexdigest())
        counts = {"active": 0, "empty": 0, "absent": 0}
        for name, point in points.items():
            b, a = old.get(name), new.get(name)
            state = "absent" if b is None else "active" if b["rows"] else "empty"
            counts[state] += 1
            self.assertEqual(point["state"], state)
            if state == "absent":
                self.assertIsNone(point["coefficients_before"])
                self.assertIsNone(point["coefficients_after"])
                self.assertNotIn("evidence", point)
                continue
            self.assertTrue(point["raw_data_unchanged"])
            for frame, block in (("before", b), ("after", a)):
                for key in ("factor", "offset"):
                    observed = point["coefficients_"+frame][key]
                    expected = block["coefficients"][key]
                    self.assertEqual(observed["value"], expected["token"])
                    self.assertEqual(observed["explicit"], expected["explicit"])
                    self.assertEqual(observed["unit"], "m" if key == "offset" else "1")
                    if not expected["explicit"]:
                        self.assertIsNone(observed["source"])
                    else:
                        field, = expected["occurrences"]
                        self.assertEqual(observed["source"]["path"], str(self.bc))
                        self.assertEqual(observed["source"]["line"], field["line"])
                        self.assertEqual(observed["source"]["byte_start"], field["start"])
                        self.assertEqual(observed["source"]["byte_end"], field["end"])
                        self.assertEqual(observed["source"]["snapshot"], "before_edit" if frame == "before" else "intended_after_edit")
            evidence = point["evidence"]
            count = len(b["rows"])
            indices = sorted(set(range(min(4, count))) | set(range(max(0, count-4), count)))
            self.assertEqual((evidence["total"], evidence["shown"], evidence["omitted"], evidence["limit"]),
                             (count, len(indices), count-len(indices), 8))
            records = []
            for i, row in enumerate(b["row_details"]):
                time, value = row["tokens"]
                before_value, after_value = b["effective"][i]["effective"], a["effective"][i]["effective"]
                records.append({"time": time["text"], "raw_value": value["text"],
                    "effective_before": {"decimal": repr(before_value), "binary64_hex": before_value.hex()},
                    "effective_after": {"decimal": repr(after_value), "binary64_hex": after_value.hex()},
                    "source": {"path": str(self.bc), "line": row["line"], "time_byte_start": time["start"], "time_byte_end": time["end"],
                               "value_byte_start": value["start"], "value_byte_end": value["end"]}})
            self.assertEqual(evidence["samples"], [records[i] for i in indices])
            encoded = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            self.assertEqual(evidence["all_samples_sha256"], hashlib.sha256(encoded).hexdigest())
            self.assertEqual(evidence["all_original_numeric_row_bytes_sha256"], hashlib.sha256(b"".join(r["bytes"] for r in b["row_details"])).hexdigest())
            if state == "empty":
                self.assertIsNone(point["coverage"])
        for state, count in counts.items():
            self.assertEqual(result[state+"_count"], count)
        for key in ("engine_initialization", "simulation", "scientific_validation"):
            self.assertEqual(result["validation"][key], "not_performed")

    def preview_apply(self, key, literal, *, unit=True):
        before, raw = self.snapshot(), self.bc.read_bytes()
        request = ["--"+key, literal]+(["--unit", "m"] if key == "offset" and unit else [])
        preview = self.success(*request)
        self.assertFalse(preview["applied"])
        self.assertEqual(self.snapshot(), before)
        self.assertRegex(preview["input_sha256"], r"^[a-f0-9]{64}$")
        expected = expected_edit(raw, key, literal)
        self.assert_point_evidence(preview, raw, expected)
        applied = self.success(*request, "--apply", "--expect-sha256", preview["input_sha256"])
        self.assertTrue(applied["applied"])
        self.assert_point_evidence(applied, raw, expected)
        self.assertEqual(self.bc.read_bytes(), expected, "Only independently declared coefficient spans may change")
        after = self.snapshot()
        self.assertEqual({k:v for k,v in after.items() if k != "model with spaces/signals.bc"},
                         {k:v for k,v in before.items() if k != "model with spaces/signals.bc"})
        old = {b["name"]: b for b in independent_blocks(raw)}
        new = {b["name"]: b for b in independent_blocks(expected)}
        self.assertEqual(set(old), set(new))
        for name, block in old.items():
            self.assertEqual(block["rows"], new[name]["rows"])
            if name.startswith("west_"):
                self.assertEqual(block["raw"], new[name]["raw"])
            elif block["rows"]:
                self.assertEqual(number(new[name]["coefficients"][key]["token"]), number(literal))
                other = "offset" if key == "factor" else "factor"
                self.assertEqual(block["coefficients"][other]["token"], new[name]["coefficients"][other]["token"])
            else:
                self.assertEqual(block["raw"], new[name]["raw"])
        return preview

    def test_inspect_implicit_defaults_read_only(self):
        before = self.snapshot()
        result = self.success()
        self.assertFalse(result["applied"])
        self.assertEqual(self.snapshot(), before)
        self.assert_point_evidence(result, self.bc.read_bytes(), self.bc.read_bytes())

    def test_factor_insertion_all_active_points(self):
        self.preview_apply("factor", "2")

    def test_offset_insertion_all_active_points(self):
        self.preview_apply("offset", "0.125")

    def test_factor_existing_mixed_tokens_preserves_other_coefficient(self):
        fixture(self.folder, mixed=True)
        self.preview_apply("factor", "-2")

    def test_offset_existing_mixed_tokens_preserves_other_coefficient(self):
        fixture(self.folder, mixed=True)
        self.preview_apply("offset", "-0.25")

    def test_zero_and_negative_coefficients_valid(self):
        for key, value in (("factor", "0"), ("factor", "-1"), ("offset", "0"), ("offset", "-0.125")):
            with self.subTest(key=key, value=value):
                fixture(self.folder, mixed=True)
                self.preview_apply(key, value)

    def test_sparse_active_points_no_new_signal_for_inactive_point(self):
        fixture(self.folder, active=(1, 3))
        self.preview_apply("factor", "2")
        self.assertNotIn(b"east_0002", self.bc.read_bytes())

    def test_empty_present_support_is_preserved_while_active_points_edit(self):
        raw = self.bc.read_bytes()
        block, = [b for b in independent_blocks(raw) if b["name"] == "east_0002"]
        prefix = block["raw"].split(b"0.000", 1)[0]
        self.bc.write_bytes(raw[:block["start"]]+prefix+b"\r\n"+raw[block["end"]:])
        self.preview_apply("factor", "2")
        empty, = [b for b in independent_blocks(self.bc.read_bytes()) if b["name"] == "east_0002"]
        self.assertEqual(empty["rows"], [])
        self.assertNotIn(b"Factor =", empty["raw"])

    def test_LF_and_BOM_preserved(self):
        fixture(self.folder, newline=b"\n", bom=True)
        self.preview_apply("offset", "0.125")

    def test_CR_physical_newline_preserved(self):
        fixture(self.folder, newline=b"\r")
        self.preview_apply("factor", "2")

    def test_inspect_mixed_explicit_coefficients_and_effective_values(self):
        fixture(self.folder, mixed=True)
        before = self.snapshot()
        result = self.success()
        self.assert_point_evidence(result, self.bc.read_bytes(), self.bc.read_bytes())
        self.assertEqual(self.snapshot(), before)

    def test_bounded_evidence_includes_digest_of_unshown_samples(self):
        old = b"0.000   +0.0000   # raw zero\r\n60  +2.5000D-1\r\n1.20E+2\t-0.125000\r\n"
        longer = b"".join((str(t)+"\t"+str(Decimal(t)/Decimal(512))+" # retained sample\r\n").encode() for t in range(0, 121, 5))
        self.bc.write_bytes(self.bc.read_bytes().replace(old, longer))
        preview = self.preview_apply("factor", "-2")
        self.assertEqual(preview["points"][0]["evidence"]["omitted"], 17)

    def test_request_literal_precision_and_fortran_exponent_preserved(self):
        self.preview_apply("factor", "+2.000D+0")

    def test_late_factor_after_time_quantity_refused(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"Unit = seconds", b"Factor = 2\r\nUnit = seconds", 1))
        self.refusal("--factor", "3")
        self.refusal()

    def test_late_offset_after_physical_quantity_refused(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"Unit = m", b"Offset = .125\r\nUnit = m", 1))
        self.refusal("--offset", "0", "--unit", "m")

    def test_duplicate_global_coefficients_even_identical_refused(self):
        for key in ("Factor", "Offset"):
            with self.subTest(key=key):
                fixture(self.folder)
                self.bc.write_bytes(self.bc.read_bytes().replace(b"Quantity = time", (key+" = 1\r\n"+key+" = 1\r\nQuantity = time").encode(), 1))
                self.refusal("--factor", "2")

    def test_global_plus_late_duplicate_refused(self):
        raw = self.bc.read_bytes().replace(b"Quantity = time", b"Factor = 2\r\nQuantity = time", 1)
        self.bc.write_bytes(raw.replace(b"Unit = m", b"Factor = 3\r\nUnit = m", 1))
        self.refusal("--factor", "4")

    def test_unknown_selected_metadata_refused(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"Quantity = time", b"FactorExtra = 2\r\nQuantity = time", 1))
        self.refusal("--factor", "3")

    def test_multi_physical_quantity_is_not_per_column_edit(self):
        raw = self.bc.read_bytes().replace(b"Unit = m", b"Unit = m\r\nQuantity = salinitybnd\r\nUnit = ppt", 1)
        self.bc.write_bytes(raw)
        self.refusal("--factor", "2")

    def test_wrong_selected_units_refused(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"Unit = m\r\n", b"Unit = cm\r\n", 1))
        self.refusal("--offset", "0.125", "--unit", "m")

    def test_offset_requires_exact_explicit_m_unit(self):
        self.refusal("--offset", "0.125")
        for unit in ("cm", "metre", "M", "s"):
            with self.subTest(unit=unit):
                self.refusal("--offset", "0.125", "--unit", unit)

    def test_factor_and_inspect_refuse_unit_claim(self):
        self.refusal("--factor", "2", "--unit", "m")
        self.refusal("--unit", "m")

    def test_mutually_exclusive_factor_and_offset(self):
        self.refusal("--factor", "2", "--offset", "0.125", "--unit", "m")

    def test_apply_requires_change_and_preview_hash(self):
        self.refusal("--factor", "2", "--apply")
        self.refusal("--apply")
        self.refusal("--factor", "2", "--apply", "--expect-sha256", "not-a-hash")

    def test_boundary_and_quantity_exact_identity(self):
        self.refusal("--factor", "2", boundary="East")
        self.refusal("--factor", "2", boundary="missing")
        self.refusal("--factor", "2", quantity="salinitybnd")

    def test_argument_nonfinite_and_engine_range_refusals(self):
        for value in ("NaN", "Infinity", "1e309", "1e-9999", "1,2", "\u22122", ""):
            with self.subTest(value=value):
                self.refusal("--factor", value)

    def test_multiplication_overflow_not_hidden_by_decimal_cancellation(self):
        # raw=2, F=1e308, O=-1e308: exact decimal final=1e308,
        # but FM binary64 multiplication overflows before addition.
        raw = self.bc.read_bytes().replace(b"Quantity = time", b"Offset = -1e308\r\nQuantity = time", 1)
        self.bc.write_bytes(raw.replace(b"60  +2.5000D-1", b"60  2.0", 1))
        self.refusal("--factor", "1e308")

    def test_addition_overflow_refused(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"60  +2.5000D-1", b"60  1e308", 1))
        self.refusal("--offset", "1e308", "--unit", "m")

    def test_existing_nonfinite_coefficient_refused(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"Quantity = time", b"Factor = NaN\r\nQuantity = time", 1))
        self.refusal("--factor", "2")

    def test_wrong_clock_timezone_refused(self):
        self.path.write_bytes(self.path.read_bytes().replace(b"TZone = 0", b"TZone = 1"))
        self.refusal("--factor", "2")

    def test_nonmonotonic_and_short_series_refused(self):
        for old, new in ((b"60  +2.5000D-1", b"0  +2.5000D-1"), (b"1.20E+2\t-0.125000", b"119\t-0.125000")):
            with self.subTest(new=new):
                fixture(self.folder)
                self.bc.write_bytes(self.bc.read_bytes().replace(old, new, 1))
                self.refusal("--factor", "2")

    def test_wrong_origin_refused_when_coverage_lost(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"2026-01-01 00:00:00", b"2026-01-02 00:00:00", 1))
        self.refusal("--factor", "2")

    def test_harmonic_not_implicitly_admitted(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"Function = timeseries", b"Function = harmonic", 1))
        self.refusal("--factor", "2")

    def test_valid_selected_harmonic_refused_including_inspection(self):
        self.replace_with_harmonic("east_0001")
        for args in ((), ("--factor", "2"), ("--offset", "0.125", "--unit", "m")):
            with self.subTest(args=args):
                error = self.refusal(*args)
                self.assertEqual(error["code"], "boundary_coefficients_function")

    def test_unrelated_valid_harmonic_is_preserved(self):
        self.replace_with_harmonic("west_0001")
        self.preview_apply("factor", "2")

    def test_separate_unselected_BC_is_preserved(self):
        self.split_bc_files()
        self.preview_apply("offset", "0.125")

    def test_stale_unselected_separate_BC_refused(self):
        other = self.split_bc_files()
        preview = self.success("--factor", "2")
        other.write_bytes(other.read_bytes()+b"# unrelated line changed\r\n")
        error = self.refusal("--factor", "2", "--apply", "--expect-sha256", preview["input_sha256"])
        self.assertEqual(error["code"], "stale_preview")

    def test_empty_selected_line_cannot_claim_successful_edit(self):
        fixture(self.folder, active=())
        before = self.snapshot()
        result = self.success()
        self.assertFalse(result["applied"])
        self.assert_point_evidence(result, self.bc.read_bytes(), self.bc.read_bytes())
        self.assertEqual(before, self.snapshot())
        self.refusal("--factor", "2")

    def test_stale_request_bound_factor_not_reused_for_offset(self):
        preview = self.success("--factor", "2")
        error = self.refusal("--offset", "0.125", "--unit", "m", "--apply", "--expect-sha256", preview["input_sha256"])
        self.assertEqual(error["code"], "stale_preview")

    def test_stale_changed_factor_request(self):
        preview = self.success("--factor", "2")
        error = self.refusal("--factor", "3", "--apply", "--expect-sha256", preview["input_sha256"])
        self.assertEqual(error["code"], "stale_preview")

    def test_inspect_hash_not_edit_consent(self):
        inspected = self.success()
        error = self.refusal("--factor", "2", "--apply", "--expect-sha256", inspected["input_sha256"])
        self.assertEqual(error["code"], "stale_preview")

    def test_stale_all_connected_graph_files(self):
        for name in ("model.mdu", "boundaries.ext", "east.pli", "west.pli", "signals.bc"):
            with self.subTest(name=name):
                fixture(self.folder)
                preview = self.success("--factor", "2")
                path = self.folder/name
                path.write_bytes(path.read_bytes()+b"# same graph, changed bytes\r\n")
                error = self.refusal("--factor", "2", "--apply", "--expect-sha256", preview["input_sha256"])
                self.assertEqual(error["code"], "stale_preview")

    def test_same_size_changed_content_with_restored_mtime_refused(self):
        preview = self.success("--factor", "2")
        previous = self.bc.stat()
        raw = self.bc.read_bytes()
        replacement = self.folder/"replacement.tmp"
        replacement.write_bytes(raw.replace(b"+2.5000D-1", b"+5.0000D-1", 1))
        self.assertEqual(len(raw), replacement.stat().st_size)
        os.replace(replacement, self.bc)
        os.utime(self.bc, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        error = self.refusal("--factor", "2", "--apply", "--expect-sha256", preview["input_sha256"])
        self.assertEqual(error["code"], "stale_preview")

    def test_same_bytes_replaced_during_publish_refused_by_identity(self):
        preview = self.success("--factor", "2")
        before, raw, original = self.snapshot(), self.bc.read_bytes(), self.bc.stat()
        real_fsync, real_replace = os.fsync, os.replace
        triggered = []
        def interfere(fd):
            real_fsync(fd)
            if not triggered:
                replacement = self.folder/"external-writer.tmp"
                replacement.write_bytes(raw)
                real_replace(replacement, self.bc)
                os.utime(self.bc, ns=(original.st_atime_ns, original.st_mtime_ns))
                observed = self.bc.stat()
                self.assertNotEqual(observed.st_ino, original.st_ino, "Control must replace the actual file identity")
                self.assertEqual(observed.st_size, original.st_size)
                self.assertEqual(observed.st_mtime_ns, original.st_mtime_ns)
                triggered.append({"before_inode": original.st_ino, "after_inode": observed.st_ino})
        with patch("os.fsync", side_effect=interfere):
            code, payload = self.cli("--factor", "2", "--apply", "--expect-sha256", preview["input_sha256"])
        self.assertTrue(triggered, "Must exercise the real pre-publication window")
        self.assertEqual(code, 4, payload)
        self.assertEqual(payload["error"]["code"], "boundary_support_publication")
        self.assertEqual(payload["error"]["details"]["cause"], "stale_preview")
        self.assertEqual(payload["error"]["details"]["target"], str(self.bc))
        self.assertIn("changed", payload["error"]["details"]["reason"])
        self.assertEqual(payload["error"]["details"]["cleanup"]["state"], "removed_exact_owned_stage")
        self.assertEqual(payload["error"]["details"]["rollback"], "not_attempted; raw source input remains unchanged")
        self.assertEqual(self.snapshot(), before)

    def test_meteo_shared_consumer_refused(self):
        ext = self.folder/"boundaries.ext"
        ext.write_bytes(ext.read_bytes()+b"[Meteo]\r\nquantity = windxy\r\nforcingFile = signals.bc\r\n")
        self.refusal("--factor", "2")

    def test_mdu_output_alias_refused(self):
        self.path.write_bytes(self.path.read_bytes()+b"HisFile = signals.bc\r\n")
        self.refusal("--factor", "2")

    def test_hardlinked_target_refused(self):
        os.link(self.bc, self.folder/"hardlinked.bc")
        self.refusal("--factor", "2")

    def test_external_reference_path_refused(self):
        external = self.root/"outside.bc"
        external.write_bytes(self.bc.read_bytes())
        ext = self.folder/"boundaries.ext"
        ext.write_bytes(ext.read_bytes().replace(b"forcingFile = signals.bc", b"forcingFile = ../outside.bc"))
        self.refusal("--factor", "2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
