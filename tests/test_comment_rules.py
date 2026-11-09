"""INI-ALIGN-I: engine comment rules of the other line parsers (Contract ini-star-align.md R1-R2).

Each parser follows the rule of the file kind it reads:

* INI (new EXT, inifield): first byte after the optional BOM and ASCII spaces is ``*``.
* PLI (``read1polylin`` / ``reapol``): column-1 ``*`` before a polyline label only.
* ``.bc`` header scan: column-1 ``!``, ``#``, ``%`` or ``*`` outside numeric data rows.

Tests marked NEW fail on the base; controls pass on both.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from dfm_cli import boundary, boundary_locations_graph as locations, layers_inputs, project_files
from dfm_cli.common import DfmError


def b(text: str) -> bytes:
    return text.encode()


def strip_lines(report):
    """Drop line numbers, byte offsets and hashes: they legitimately shift with an inserted comment."""
    if isinstance(report, dict):
        return {key: strip_lines(value) for key, value in report.items()
                if key not in {"line", "block", "input_sha256", "files", "amplitude_byte_start", "amplitude_byte_end",
                               "references"}}
    if isinstance(report, list):
        return [strip_lines(item) for item in report]
    return report


class Tmp(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-comment-rules-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)


# --------------------------------------------------------------------------------------------- INI rule

EXT = """[General]
fileVersion=2.02
fileType=extForce
[Boundary]
quantity=waterlevelbnd
locationFile=sea.pli
forcingFile=sea.bc
"""
EXT_COMMENTED = """* leading note
[General]
* after header
fileVersion=2.02
   * spaces then star
fileType=extForce
[Boundary]
* quantity=bogus
quantity=waterlevelbnd
locationFile=sea.pli
   * forcingFile=other.bc
forcingFile=sea.bc
* trailing
"""
PLI = "L1\n3 2\n0.5 0.5 L1_0001\n1.5 0.5 L1_0002\n2.5 0.5 L1_0003\n"
BC = """[General]
fileVersion=1.01
fileType=boundConds

[Forcing]
name = L1_0001
function = harmonic
quantity = harmonic component
unit = minutes
quantity = waterlevelbnd amplitude
unit = m
quantity = waterlevelbnd phase
unit = deg
0 0 0
750 1.5 3
"""


class IniRule(Tmp):
    def model(self, ext: str, pli: str = PLI, bc: str = BC, *, bom: bool = False):
        (self.root / "flow.mdu").write_bytes(b("[General]\nPathsRelativeToParent = 1\n[geometry]\nNetFile = mesh.nc\n"
                                               "[external forcing]\nExtForceFile =\nExtForceFileNew = sea.ext\n"))
        (self.root / "sea.ext").write_bytes((b"\xef\xbb\xbf" if bom else b"") + b(ext))
        (self.root / "sea.pli").write_bytes(b(pli))
        (self.root / "sea.bc").write_bytes(b(bc))
        (self.root / "mesh.nc").write_bytes(b"opaque")
        return self.root / "flow.mdu"

    def inspect(self, *args, **kwargs):
        return strip_lines(boundary._load(self.model(*args, **kwargs)).report())

    def test_boundary_ext_star_lines_read_like_the_same_file_without_them(self):  # NEW
        plain = self.inspect(EXT)
        self.assertEqual(self.inspect(EXT_COMMENTED), plain)
        self.assertEqual(self.inspect(EXT_COMMENTED, bom=True), plain)
        self.assertEqual(self.inspect(EXT_COMMENTED.replace("\n", "\r\n")), plain)

    def test_boundary_ext_tab_before_star_keeps_current_refusal(self):  # control
        with self.assertRaises(DfmError):
            self.inspect(EXT.replace("[Boundary]\n", "[Boundary]\n\t* tab comment\n"))

    def test_boundary_ext_star_inside_value_or_key_keeps_meaning(self):  # control
        report = self.inspect(EXT.replace("quantity=waterlevelbnd", "quantity=waterlevelbnd"))
        self.assertEqual(report["boundaries"][0]["quantity"], "waterlevelbnd")
        with self.assertRaises(DfmError):
            self.inspect(EXT.replace("forcingFile=sea.bc", "forcingFile=*sea.bc"))

    def test_locations_blocks_star_lines(self):  # NEW
        def shape(raw):
            return [(item.kind, item.fields) for item in locations.blocks(b(raw), Path("sea.ext"))]
        self.assertEqual(shape(EXT_COMMENTED), shape(EXT))
        self.assertEqual(shape("\n".join(line for line in EXT_COMMENTED.splitlines()) + "\n"), shape(EXT))

    def test_locations_blocks_tab_star_control(self):  # control (non-comment: ignored like any data line before)
        raw = b(EXT.replace("[Boundary]\n", "[Boundary]\n\t* tab comment\n"))
        self.assertEqual([(item.kind, item.fields) for item in locations.blocks(raw, Path("x"))],
                         [(item.kind, item.fields) for item in locations.blocks(b(EXT), Path("x"))])

    def test_locations_comment_block_keeps_star_lines_byte_for_byte(self):  # NEW
        raw = b("[Boundary]\n* keep me\n  * and me\nquantity=waterlevelbnd\n# old\n")
        block = locations.Block("boundary", 0, len(raw), [])
        changed = locations.comment_block(raw, block).splitlines(keepends=True)
        self.assertEqual(changed[1:3], [b"* keep me\n", b"  * and me\n"])
        self.assertTrue(changed[0].startswith(b"# boundary-location-import removed: "))
        self.assertTrue(changed[3].startswith(b"# boundary-location-import removed: "))
        self.assertEqual(changed[4], b"# old\n")

    def test_layers_blocks_inifield_and_ext_star_lines(self):  # NEW
        ini = "[General]\nfileVersion=2.02\nfileType=iniField\n[Initial]\nquantity=salinity\ndataFile=p.pli\n"
        commented = ("* top\n[General]\n  * x = y\nfileVersion=2.02\nfileType=iniField\n[Initial]\n"
                     "* quantity=bogus\nquantity=salinity\ndataFile=p.pli\n* end\n")
        for plain, noted in ((ini, commented), (EXT, EXT_COMMENTED)):
            with self.subTest(plain[:20]):
                self.assertEqual([(i.kind, i.fields, i.rows) for i in layers_inputs.blocks(b(noted))],
                                 [(i.kind, i.fields, i.rows) for i in layers_inputs.blocks(b(plain))])
                self.assertEqual([(i.kind, i.fields) for i in layers_inputs.blocks(b"\xef\xbb\xbf" + b(noted))],
                                 [(i.kind, i.fields) for i in layers_inputs.blocks(b(plain))])

    def test_layers_blocks_tab_star_control(self):  # control
        with self.assertRaises(DfmError):
            layers_inputs.blocks(b("\t* tab\n[General]\n"))

    def test_boundary_set_apply_keeps_star_lines_byte_for_byte(self):  # NEW
        pli = "* pli head\nL1\n3 2\n0.5 0.5 L1_0001\n1.5 0.5 L1_0002\n2.5 0.5 L1_0003\n"
        bc = BC.replace("[General]\n", "* bc top\n[General]\n").replace("0 0 0\n", "! bang\n% pct\n0 0 0\n") + "\n"
        mdu = self.model(EXT_COMMENTED, pli, bc)
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}

        def run(*extra):
            done = subprocess.run([sys.executable, "-m", "dfm_cli", "boundary", "set", str(mdu), "--point", "L1_0001",
                                   "--period-minutes", "750", "--amplitude-m", "1.75", *extra],
                                  capture_output=True, timeout=30)
            return json.loads(done.stdout)
        preview = run()
        self.assertTrue(preview["ok"], preview)
        applied = run("--apply", "--expect-sha256", preview["result"]["input_sha256"])
        self.assertTrue(applied["ok"], applied)
        after = {p.name: p.read_bytes() for p in self.root.iterdir()}
        expected = dict(before)
        expected["sea.bc"] = before["sea.bc"].replace(b"750 1.5 3", b"750 1.75 3")
        self.assertEqual(after, expected)


# --------------------------------------------------------------------------------------------- PLI rule

MULTI = "L1\n2 2\n0 0\n1 0\nL2\n2 2\n0 1\n1 1\n"


class PliRule(Tmp):
    def points(self, text):
        label, points = boundary._pli(b(text), Path("x.pli"))
        return label, [(p["name"], p["coordinates"]) for p in points]

    def test_boundary_pli_star_before_label_and_after_rows(self):  # NEW
        expected = self.points(PLI)
        for text in ("* a\n* b\n" + PLI,
                     "\ufeff* a\n" + PLI):
            with self.subTest(text[:12]):
                self.assertEqual(self.points(text), expected)

    def test_boundary_pli_star_elsewhere_keeps_refusal(self):  # control
        for text in ("L1\n* inside\n3 2\n0.5 0.5\n1.5 0.5\n2.5 0.5\n",
                     "L1\n3 2\n0.5 0.5\n* row\n1.5 0.5\n2.5 0.5\n",
                     "L1\n3 2\n0.5 0.5\n1.5 0.5\n2.5 0.5\n* row?\n3.5 0.5\n",
                     "  * indented\n" + PLI,
                     "\t* tab\n" + PLI,
                     PLI + "* tail\n",                      # R5.1: single-polyline reader, only before the first label
                     PLI + "* a\n* b\n"):
            with self.subTest(text[:14]), self.assertRaises(DfmError):
                self.points(text)

    def test_locations_pli_multi_polyline(self):  # NEW
        def shape(raw):
            return [(item["label"], [[t[2] for t in p["tokens"]] for p in item["points"]])
                    for item in locations.pli(b(raw), Path("x.pli"))]
        expected = shape(MULTI)
        for text in ("* a\n" + MULTI, "L1\n2 2\n0 0\n1 0\n* between\n* more\nL2\n2 2\n0 1\n1 1\n",
                     "* a\nL1\n2 2\n0 0\n1 0\n* b\nL2\n2 2\n0 1\n1 1\n"):
            with self.subTest(text[:12]):
                self.assertEqual(shape(text), expected)

    def test_locations_pli_star_elsewhere_keeps_refusal(self):  # control
        for text in ("L1\n2 2\n* row\n0 0\n1 0\n", "L1\n2 2\n0 0\n* row\n1 0\n", "L1\n* c\n2 2\n0 0\n1 0\n",
                     "  * indented\n" + MULTI,
                     MULTI + "* tail\n",                    # R5.1: no next label follows
                     "* only\n* stars\n"):
            with self.subTest(text[:14]), self.assertRaises(DfmError):
                locations.pli(b(text), Path("x.pli"))

    def test_layers_polyline_and_profile_table(self):  # NEW
        line = "L1\n2 2\n0 0\n1 0\n"
        self.assertEqual(layers_inputs.polyline(b("* a\n* b\n" + line)), layers_inputs.polyline(b(line)))
        profile = "P\n3 2\n-3 30\n-2 20\n-1 10\n"
        self.assertEqual(layers_inputs.profile_table(b("* a\n" + profile)), layers_inputs.profile_table(b(profile)))
        self.assertEqual(layers_inputs.profile_table(b("\ufeff* a\n" + profile)), layers_inputs.profile_table(b(profile)))

    def test_layers_polyline_and_profile_table_star_elsewhere_control(self):  # control
        for call, text in ((layers_inputs.polyline, "L1\n2 2\n0 0\n1 0\n* tail\n"),      # R5.1: only before the label
                           (layers_inputs.profile_table, "P\n3 2\n-3 30\n-2 20\n-1 10\n* tail\n"),
                           (layers_inputs.polyline, "L1\n2 2\n* r\n0 0\n1 0\n"),
                           (layers_inputs.polyline, "L1\n2 2\n0 0\n* r\n1 0\n"),
                           (layers_inputs.polyline, "  * x\nL1\n2 2\n0 0\n1 0\n"),
                           (layers_inputs.profile_table, "P\n3 2\n-3 30\n* r\n-2 20\n-1 10\n"),
                           (layers_inputs.profile_table, "P\n* r\n3 2\n-3 30\n-2 20\n-1 10\n")):
            with self.subTest(text[:14]), self.assertRaises(DfmError):
                call(b(text))


# --------------------------------------------------------------------------------------------- BC rule

BC_NOTED = """* top
! bang
% pct
# hash
[General]
! in general
fileVersion=1.01
% mid
fileType=boundConds
* between

[Forcing]
* name = bogus
name = L1_0001
function = harmonic
! quantity = bogus
quantity = harmonic component
unit = minutes
quantity = waterlevelbnd amplitude
unit = m
quantity = waterlevelbnd phase
unit = deg
* before first row
0 0 0
750 1.5 3
"""


class BcRule(Tmp):
    def signals(self, text):
        return strip_lines(boundary._bc(b(text), Path("x.bc")))

    def test_boundary_bc_header_comment_lines(self):  # NEW
        expected = self.signals(BC)
        self.assertEqual(self.signals(BC_NOTED), expected)
        self.assertEqual(self.signals("\ufeff" + BC_NOTED), expected)
        self.assertEqual(self.signals(BC_NOTED.replace("\n", "\r\n")), expected)

    def test_boundary_bc_keeps_refusals_outside_the_rule(self):  # control
        for text in (BC.replace("750 1.5 3\n", "* row\n750 1.5 3\n"),      # data row
                     BC.replace("0 0 0\n", "0 0 0\n! row\n"),
                     BC.replace("0 0 0\n", "0 0 0\n% row\n"),
                     BC.replace("750 1.5 3\n", "750 1.5 3\n* after last row\n"),   # R5.2: until the next block header
                     BC.replace("0 0 0\n", "  * indented\n0 0 0\n"),         # not column 1
                     BC.replace("0 0 0\n", "\t! tab\n0 0 0\n"),
                     BC.replace("name = L1_0001\n", "x* = 1\nname = L1_0001\n")):
            with self.subTest(text[-40:]), self.assertRaises(DfmError):
                self.signals(text)

    def test_layers_signals_bc(self):  # NEW
        clock = {"start": "2000-01-01T00:00:00", "duration_seconds": 100}
        plain = ("[General]\nfileVersion=1.01\nfileType=boundConds\n[Forcing]\nName = L1_0001\nFunction = timeseries\n"
                 "Time-interpolation = linear\nQuantity = time\nUnit = seconds since 2000-01-01 00:00:00 +00:00\n"
                 "Quantity = waterlevelbnd\nUnit = m\n0 0.5\n100 0.6\n")
        noted = ("* top\n! bang\n[General]\n% p\nfileVersion=1.01\nfileType=boundConds\n* between\n[Forcing]\n"
                 "! name = bogus\nName = L1_0001\nFunction = timeseries\nTime-interpolation = linear\n"
                 "Quantity = time\nUnit = seconds since 2000-01-01 00:00:00 +00:00\nQuantity = waterlevelbnd\n"
                 "Unit = m\n* before rows\n0 0.5\n100 0.6\n")
        expected = layers_inputs.signals(b(plain), clock)
        expected[("l1_0001", "waterlevelbnd")].pop("source_line")
        got = layers_inputs.signals(b(noted), clock)
        got[("l1_0001", "waterlevelbnd")].pop("source_line")
        self.assertEqual(got, expected)

    def test_layers_signals_data_row_star_keeps_refusal(self):  # control
        clock = {"start": "2000-01-01T00:00:00", "duration_seconds": 100}
        text = ("[General]\nfileVersion=1.01\nfileType=boundConds\n[Forcing]\nName = L1_0001\nFunction = timeseries\n"
                "Time-interpolation = linear\nQuantity = time\nUnit = seconds since 2000-01-01 00:00:00 +00:00\n"
                "Quantity = waterlevelbnd\nUnit = m\n0 0.5\n* row\n100 0.6\n")
        with self.assertRaises(DfmError):
            layers_inputs.signals(b(text), clock)

    def write(self, text):
        path = self.root / "x.bc"
        path.write_bytes(b(text))
        return path

    def test_project_files_bc_references_and_semantics(self):  # NEW
        timeseries = ("[General]\nfileVersion=1.01\nfileType=boundConds\n[Forcing]\nName = L1_0001\nFunction = timeseries\n"
                      "Quantity = time\nUnit = seconds since 2000-01-01 00:00:00 +00:00\nQuantity = waterlevelbnd\nUnit = m\n"
                      "0 0.5\n100 0.6\n")
        noted = ("* top\n! bang\n[General]\n% p\nfileVersion=1.01\nfileType=boundConds\n* between\n[Forcing]\n"
                 "* name = bogus\nName = L1_0001\nFunction = timeseries\n! unit = bogus\nQuantity = time\n"
                 "Unit = seconds since 2000-01-01 00:00:00 +00:00\nQuantity = waterlevelbnd\nUnit = m\n"
                 "* before rows\n0 0.5\n100 0.6\n")
        project_files._bc_references(self.write(noted))
        self.assertEqual(project_files._bc_semantics(self.write(noted)),
                         project_files._bc_semantics(self.write(timeseries)))

    def test_project_files_bc_data_row_and_indent_controls(self):  # control
        base = ("[General]\nfileVersion=1.01\nfileType=boundConds\n[Forcing]\nName = L1_0001\nFunction = timeseries\n"
                "Quantity = time\nUnit = seconds since 2000-01-01 00:00:00 +00:00\nQuantity = waterlevelbnd\nUnit = m\n")
        with self.assertRaises(DfmError):
            project_files._bc_references(self.write(base + "0 0.5\n* a = b\n100 0.6\n"))
        with self.assertRaises(DfmError):
            project_files._bc_semantics(self.write(base + "0 0.5\n* row\n100 0.6\n"))
        with self.assertRaises(DfmError):
            project_files._bc_semantics(self.write(base + "0 0.5\n! row\n100 0.6\n"))
        with self.assertRaises(DfmError):
            project_files._bc_references(self.write("[General]\n  * indented\nfileVersion=1.01\n"))
        with self.assertRaises(DfmError):
            project_files._bc_references(self.write("[General]\n\t! tab\nfileVersion=1.01\n"))


class ProjectFilesBundle(Tmp):
    """R5.3: internal coverage of the project reference audit (model_bundle) and BC comparison."""

    def models(self):
        from tests.test_project import portable_model
        plain = portable_model(self.root / "plain")
        noted = portable_model(self.root / "noted")
        bc = noted.parent / "f34_001.bc"
        text = bc.read_text(encoding="utf-8")
        text = ("* top\n" + text.replace("[General]\n", "[General]\n! note\n", 1)
                .replace("[Forcing]\n", "[Forcing]\n% before name\n* x = bogus\n")
                .replace("0 0 0\n", "! head\n* head\n0 0 0\n"))
        bc.write_bytes(text.encode())
        return plain, noted

    def test_model_bundle_and_bc_semantics_ignore_header_comment_lines(self):  # NEW
        plain, noted = self.models()
        names = lambda mdu: [item["relative_path"] for item in project_files.model_bundle(mdu)["files"]]
        self.assertEqual(names(noted), names(plain))
        self.assertEqual(project_files._bc_semantics(noted.parent / "f34_001.bc"),
                         project_files._bc_semantics(plain.parent / "f34_001.bc"))

    def test_model_bundle_data_row_star_keeps_refusal(self):  # control (R5.2)
        plain, noted = self.models()
        bc = plain.parent / "f34_001.bc"
        bc.write_text(bc.read_text(encoding="utf-8").replace("750 1.625 0\n", "750 1.625 0\n* row = 1\n", 1), encoding="utf-8")
        with self.assertRaises(DfmError):
            project_files.model_bundle(plain)


if __name__ == "__main__":
    unittest.main()
