"""CONSUMERS-I: the other callers of ``boundary._blocks`` use the comment rule of the file kind they read.

Contract ``research/notes/delivery/ini-align-consumers.md`` R1-R2. New EXT and inifield files treat ``*`` after
leading ASCII spaces as a comment; ``.bc`` files treat column-1 ``!``, ``%`` and ``*`` before a block's first numeric
row as comments. Each public command family below reads a model whose files carry such comment lines and must give
the same result as the same model without them; edits keep the comment lines byte for byte. Tests marked NEW fail on
the base; controls (tab-led ``*``, ``*`` in ``.bc`` data rows, files without comments) pass on both.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

from dfm_cli import boundary_constituents as constituents
from dfm_cli import source_sink as sources, source_sink_author as author
from dfm_cli.common import DfmError

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
from source_sink_test_fixtures import SourceSinkFixture, BC as SOURCE_SINK_BC  # noqa: E402
import test_boundary_constituents as constituents_fixture  # noqa: E402
import test_boundary_vertical_public as vertical_fixture  # noqa: E402

MARK = b"cmt-note"
BOM = b"\xef\xbb\xbf"


# ------------------------------------------------------------------------------------------ comment insertion

def note_ini(raw: bytes) -> bytes:
    """Put an engine ``*`` comment (alternately indented by spaces) before every non-blank line."""
    bom = raw.startswith(BOM)
    out, count = [], 0
    for line in (raw[len(BOM):] if bom else raw).splitlines(keepends=True):
        if line.strip():
            eol = b"\r\n" if line.endswith(b"\r\n") else b"\n"
            out.append((b"  " if count % 2 else b"") + b"* " + MARK + b" %d" % count + eol)
            count += 1
        out.append(line)
    return (BOM if bom else b"") + b"".join(out)


def note_bc(raw: bytes) -> bytes:
    """Put a column-1 ``*``/``!``/``%`` comment before every header line and each block's first numeric row.

    Nothing is inserted between a block's numeric rows or before a header that follows numeric rows: those
    positions are not comments for the engine.
    """
    bom = raw.startswith(BOM)
    out, count, in_data = [], 0, False
    for line in (raw[len(BOM):] if bom else raw).splitlines(keepends=True):
        text = line.strip()
        code = re.split(rb"[#;]", text, 1)[0].strip()
        if text and not text.startswith((b"#", b";")):
            header = code.startswith(b"[")
            if header and in_data:
                in_data = False                      # a comment before this header is not allowed
            elif not in_data:
                eol = b"\r\n" if line.endswith(b"\r\n") else b"\n"
                out.append(b"*!%"[count % 3:count % 3 + 1] + b" " + MARK + b" %d" % count + eol)
                count += 1
            if header:
                in_data = False
            elif code and b"=" not in code:
                in_data = True
        out.append(line)
    return (BOM if bom else b"") + b"".join(out)


def is_note(line: bytes) -> bool:
    body = line[len(BOM):] if line.startswith(BOM) else line
    return MARK in body and body.lstrip(b" ")[:1] in (b"*", b"!", b"%")


def without_notes(raw: bytes) -> bytes:
    bom = BOM if raw.startswith(BOM) else b""
    body = raw[len(bom):]
    return bom + b"".join(line for line in body.splitlines(keepends=True) if not is_note(line))


def notes(raw: bytes) -> list[bytes]:
    body = raw[len(BOM):] if raw.startswith(BOM) else raw
    return [line for line in body.splitlines(keepends=True) if is_note(line)]


# ------------------------------------------------------------------------------------------ result comparison

DROPPED = re.compile(r"(^|_)(line|lines)$|byte|sha|hash|digest|offset|span|size|mtime|inode|ino$|identit|token", re.I)


def norm(value, *roots):
    """Drop line numbers, offsets and hashes (they shift with an inserted comment); mask the model folder."""
    if isinstance(value, dict):
        return {norm(key, *roots): norm(item, *roots) for key, item in value.items() if not DROPPED.search(key)}
    if isinstance(value, list):
        return [norm(item, *roots) for item in value]
    if isinstance(value, str):
        for root in roots:
            for spelling in (str(root), root.as_posix()):
                value = value.replace(spelling, "<M>")
        return value
    return value


def run_cli(*args, cwd=None):
    done = subprocess.run([sys.executable, "-B", "-m", "dfm_cli", *map(str, args)], capture_output=True,
                          timeout=120, cwd=cwd)
    return done.returncode, json.loads(done.stdout)


def snapshot(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


class Tmp(unittest.TestCase):
    def setUp(self):
        # Ordinary inheritance: mkdtemp(mode 0700) makes explicit Windows ACEs that the edit writers refuse.
        parent = Path(tempfile.gettempdir()).resolve()
        self.root = parent / ("dfm-consumers-" + uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.addCleanup(shutil.rmtree, self.root)


# ------------------------------------------------------------------------------------------ 2-D timeseries model

UNIT = "seconds since 2026-01-01 00:00:00 +00:00"
MDU = (b"[General]\nPathsRelativeToParent=0\n[geometry]\nNetFile=mesh.nc\nKmx=0\n"
       b"[time]\nRefDate=20260101\nTZone=0\nTUnit=S\nTStart=0\nTStop=120\n"
       b"StartDateTime=20260101000000\nStopDateTime=20260101000200\n"
       b"[external forcing]\nExtForceFile=\nExtForceFileNew=boundaries.ext\n")
EXT = (b"[General]\nfileVersion=2.02\nfileType=extForce\n"
       b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=west.pli\nforcingFile=boundaries.bc\n"
       b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=east.pli\nforcingFile=boundaries.bc\n")
PLI = {"east.pli": b"east\n2 2\n500120 5700000\n500120 5700040\n",
       "west.pli": b"west\n2 2\n500000 5700000\n500000 5700040\n"}
GENERAL = b"[General]\nfileVersion=1.01\nfileType=boundConds\n# global comment\n\n"


def signal(name, values=("0.000", "0.030", "0.060", "0.090", "0.120"), times=("0", "30", "60", "90", "120")):
    head = (f"[Forcing]\nName = {name}\nFunction = timeseries\nTime-interpolation = linear\n# header {name}\n"
            f"Quantity = time\nUnit = {UNIT}\nQuantity = waterlevelbnd\nUnit = m\n").encode()
    return head + b"".join(f"  {t}\t{v} # row\n".encode() for t, v in zip(times, values)) + b"\n"


def star_row(bc: bytes, name: str, line: bytes) -> bytes:
    """Put ``line`` between the first two numeric rows of the Forcing block ``name`` (a data-row position)."""
    start = bc.index(b"Name = " + name.encode())
    row = bc.index(b"  30\t", start)
    return bc[:row] + line + bc[row:]


BC = GENERAL + signal("west_0001") + signal("east_0001") + signal("east_0002") + signal("west_0002")
SOURCE_BC = GENERAL + signal("east_0001", ("1.000", "1.030", "1.060", "1.090", "1.120")) \
    + signal("east_0002", ("2.000", "2.030", "2.060", "2.090", "2.120"))


def build_model(folder: Path, *, noted: bool, bc: bytes = BC, ext: bytes = EXT, extra: dict | None = None) -> Path:
    folder.mkdir(parents=True)
    files = {"model.mdu": MDU, "boundaries.ext": note_ini(ext) if noted else ext,
             "boundaries.bc": note_bc(bc) if noted else bc, "mesh.nc": b"opaque mesh, not a native fixture",
             **PLI, **(extra or {})}
    for name, raw in files.items():
        (folder / name).write_bytes(raw)
    return folder / "model.mdu"


class Model2D(Tmp):
    """Plain and commented copies of one model, and the same command run on both."""

    def models(self, **kwargs):
        self.plain = build_model(self.root / "plain", noted=False, **kwargs)
        self.noted = build_model(self.root / "noted", noted=True, **kwargs)
        return self.plain, self.noted

    def same(self, *argv, **kwargs):
        """The commented model gives the same normalized result as the plain one; returns the plain result."""
        results = []
        for mdu in self.models(**kwargs):
            code, value = run_cli(*[mdu if item is None else item for item in argv])
            self.assertEqual((code, value["ok"]), (0, True), value)
            results.append(norm(value["result"], mdu.parent))
        self.assertEqual(results[1], results[0])
        return results[0]

    def edit_both(self, build_argv, **kwargs):
        """Preview and apply on both models; the commented result is the plain result plus its comment lines."""
        self.models(**kwargs)
        before = {name: snapshot(mdu.parent) for name, mdu in (("plain", self.plain), ("noted", self.noted))}
        previews = {}
        for name, mdu in (("plain", self.plain), ("noted", self.noted)):
            code, value = run_cli(*build_argv(mdu))
            self.assertEqual((code, value["ok"]), (0, True), value)
            self.assertEqual(snapshot(mdu.parent), before[name], "Preview wrote files")
            previews[name] = value["result"]
        for name, mdu in (("plain", self.plain), ("noted", self.noted)):
            token = previews[name].get("input_sha256") or previews[name]["sha256"]
            code, value = run_cli(*build_argv(mdu), "--apply", "--expect-sha256", token)
            self.assertEqual((code, value["ok"]), (0, True), value)
        after = {name: snapshot(mdu.parent) for name, mdu in (("plain", self.plain), ("noted", self.noted))}
        changed = [path for path in after["plain"] if after["plain"][path] != before["plain"][path]]
        self.assertTrue(changed, "The edit changed nothing")
        for path in after["noted"]:
            if path in changed:
                self.assertEqual(without_notes(after["noted"][path]), after["plain"][path], path)
                self.assertEqual(notes(after["noted"][path]), notes(before["noted"][path]), path)
            else:
                self.assertEqual(after["noted"][path], before["noted"][path], path)
        return changed


class SeriesFamily(Model2D):
    def values(self, **extra):
        path = self.root / "values.json"
        path.write_text(json.dumps({"time_unit": UNIT, "value_unit": "m", "changes": [
            {"time": "30", "value": "0.5"}, {"time": "90", "value": "0.25"}], **extra}))
        return path

    def rows(self):
        path = self.root / "rows.json"
        path.write_text(json.dumps({"time_unit": UNIT, "value_unit": "m", "insert": [{"time": "45", "value": "0.105"}],
                                    "delete": []}))
        return path

    def test_series_inspect_reads_commented_ext_and_bc_like_plain(self):  # NEW
        result = self.same("boundary", "series-inspect", None, "--point", "east_0001")
        self.assertEqual([k["time"] for k in result["series"]["knots"]], ["0", "30", "60", "90", "120"])

    def test_series_set_edits_keep_comment_lines_byte_for_byte(self):  # NEW
        values = self.values()
        changed = self.edit_both(lambda m: ("boundary", "series-set", m, "--point", "east_0001", "--values", values))
        self.assertEqual(changed, ["boundaries.bc"])

    def test_series_rows_edits_keep_comment_lines_byte_for_byte(self):  # NEW
        rows = self.rows()
        changed = self.edit_both(lambda m: ("boundary", "series-rows", m, "--point", "east_0001", "--rows", rows))
        self.assertEqual(changed, ["boundaries.bc"])

    def test_series_data_row_star_keeps_current_refusal(self):  # control
        for line in (b"* row\n", b"! row\n", b"% row\n"):
            with self.subTest(line):
                mdu = build_model(self.root / ("row-" + hex(line[0])), noted=False, bc=star_row(BC, "east_0001", line))
                code, value = run_cli("boundary", "series-inspect", mdu, "--point", "east_0001")
                self.assertNotEqual(code, 0, value)
                self.assertNotIn(value["error"]["code"], ("internal_error", "usage"))

    def test_series_tab_led_star_in_ext_keeps_current_refusal(self):  # control
        mdu = build_model(self.root / "tab", noted=False, ext=EXT.replace(b"[Boundary]\n", b"[Boundary]\n\t* tab\n", 1))
        code, value = run_cli("boundary", "series-inspect", mdu, "--point", "east_0001")
        self.assertNotEqual(code, 0, value)

    def test_series_files_without_comments_are_unchanged(self):  # control
        code, value = run_cli("boundary", "series-inspect", build_model(self.root / "plain", noted=False), "--point",
                              "east_0001")
        self.assertEqual((code, value["ok"]), (0, True), value)


class ExportFamily(Model2D):
    def argv(self, mdu):
        return ("boundary", "export", mdu, "--out", mdu.parent.parent / ("out-" + mdu.parent.name), "--group-by", "all")

    def test_export_reads_commented_ext_and_bc_like_plain(self):  # NEW
        outputs = {}
        for mdu in self.models():
            code, preview = run_cli(*self.argv(mdu))
            self.assertEqual((code, preview["ok"]), (0, True), preview)
            out = Path(self.argv(mdu)[4])
            code, applied = run_cli(*self.argv(mdu), "--apply", "--expect-sha256", preview["result"]["input_sha256"])
            self.assertEqual((code, applied["ok"]), (0, True), applied)
            outputs[mdu.parent.name] = snapshot(out)
        self.assertEqual(outputs["plain"].keys(), outputs["noted"].keys())
        for name, raw in outputs["noted"].items():
            if name.endswith(".bc"):
                # Source block bytes are copied as they are; header comment lines inside a block travel with it.
                self.assertEqual(without_notes(raw), outputs["plain"][name], name)
                self.assertTrue(notes(raw), name)

    def test_export_data_row_star_is_still_data_and_travels_with_its_block(self):  # control
        mdu = build_model(self.root / "row", noted=False, bc=star_row(BC, "east_0001", b"* row\n"))
        code, preview = run_cli(*self.argv(mdu))
        self.assertEqual((code, preview["ok"]), (0, True), preview)
        code, applied = run_cli(*self.argv(mdu), "--apply", "--expect-sha256", preview["result"]["input_sha256"])
        self.assertEqual((code, applied["ok"]), (0, True), applied)
        exported = [raw for name, raw in snapshot(Path(self.argv(mdu)[4])).items() if name.endswith(".bc")]
        self.assertEqual(sum(raw.count(b"* row\n") for raw in exported), 1)


class ImportFamily(Model2D):
    def argv(self, mdu):
        return ("boundary", "import", mdu, "--boundary", "east", "--source", mdu.parent / "source.bc", "--format",
                "bc", "--mode", "replace")

    def models(self, **kwargs):
        plain = build_model(self.root / "plain", noted=False, extra={"source.bc": SOURCE_BC})
        noted = build_model(self.root / "noted", noted=True, extra={"source.bc": note_bc(SOURCE_BC)})
        self.plain, self.noted = plain, noted
        return plain, noted

    def test_import_reads_commented_destination_and_source_like_plain(self):  # NEW
        self.models()
        results = []
        for mdu in (self.plain, self.noted):
            code, value = run_cli(*self.argv(mdu))
            self.assertEqual((code, value["ok"]), (0, True), value)
            results.append(norm(value["result"], mdu.parent))
        self.assertEqual(results[1], results[0])

    def test_import_apply_keeps_comment_lines_byte_for_byte(self):  # NEW
        self.models()
        before = {n: snapshot(m.parent) for n, m in (("plain", self.plain), ("noted", self.noted))}
        for mdu in (self.plain, self.noted):
            code, preview = run_cli(*self.argv(mdu))
            self.assertEqual((code, preview["ok"]), (0, True), preview)
            code, applied = run_cli(*self.argv(mdu), "--apply", "--expect-sha256", preview["result"]["input_sha256"])
            self.assertEqual((code, applied["ok"]), (0, True), applied)
        plain_after, noted_after = snapshot(self.plain.parent), snapshot(self.noted.parent)
        self.assertNotEqual(plain_after["boundaries.bc"], before["plain"]["boundaries.bc"])
        self.assertEqual(without_notes(noted_after["boundaries.bc"]), plain_after["boundaries.bc"])
        self.assertEqual(notes(noted_after["boundaries.bc"]), notes(before["noted"]["boundaries.bc"]))
        self.assertEqual(noted_after["source.bc"], before["noted"]["source.bc"])

    def test_import_data_row_star_in_source_keeps_current_refusal(self):  # control
        bad = star_row(SOURCE_BC, "east_0001", b"* row\n")
        self.models()
        (self.plain.parent / "source.bc").write_bytes(bad)
        code, value = run_cli(*self.argv(self.plain))
        self.assertNotEqual(code, 0, value)
        self.assertNotIn(value["error"]["code"], ("internal_error", "usage"))


class PreviewFamily(Model2D):
    def test_preview_reads_commented_ext_and_bc_like_plain(self):  # NEW
        result = self.same("boundary", "preview", None, "--point", "east_0001", "--quantity", "waterlevelbnd",
                           "--time", "30", "--time-unit", UNIT)
        self.assertEqual(result["kind"], "boundary_input_preview")

    def test_preview_data_row_star_keeps_current_refusal(self):  # control
        mdu = build_model(self.root / "row", noted=False, bc=star_row(BC, "east_0001", b"* row\n"))
        code, value = run_cli("boundary", "preview", mdu, "--point", "east_0001", "--quantity", "waterlevelbnd",
                              "--time", "30", "--time-unit", UNIT)
        self.assertNotEqual(code, 0, value)
        self.assertNotIn(value["error"]["code"], ("internal_error", "usage"))


# ------------------------------------------------------------------------------------------ constituents (B14)

class ConstituentsFamily(Tmp):
    def build(self, name, *, noted):
        mdu, request = constituents_fixture.fixture(self.root / name)
        if noted:
            for file, note in (("boundary.ext", note_ini), ("boundary.bc", note_bc)):
                path = mdu.parent / file
                path.write_bytes(note(path.read_bytes()))
        return mdu, request

    def test_constituents_inspect_reads_commented_inputs_like_plain(self):  # NEW
        plain_mdu = self.build("plain", noted=False)[0]
        plain = constituents.inspect(plain_mdu, "west")
        mdu = self.build("noted", noted=True)[0]
        noted = constituents.inspect(mdu, "west")
        self.assertEqual(norm(noted, mdu.parent), norm(plain, plain_mdu.parent))

    def test_constituents_set_keeps_comment_lines_byte_for_byte(self):  # NEW
        outputs = {}
        for name in ("plain", "noted"):
            mdu, request = self.build(name, noted=(name == "noted"))
            before = (mdu.parent / "boundary.bc").read_bytes()
            preview = constituents.assign(mdu, "west", request, points=["west_0001"], create_missing=True)
            result = constituents.assign(mdu, "west", request, points=["west_0001"], create_missing=True, apply=True,
                                         expect_sha256=preview["input_sha256"])
            self.assertTrue(result["publication"]["committed"])
            outputs[name] = (before, (mdu.parent / "boundary.bc").read_bytes())
        self.assertNotEqual(outputs["plain"][0], outputs["plain"][1])
        self.assertEqual(without_notes(outputs["noted"][1]), outputs["plain"][1])
        self.assertEqual(notes(outputs["noted"][1]), notes(outputs["noted"][0]))

    def test_constituents_data_row_star_keeps_current_refusal(self):  # control
        mdu, request = self.build("row", noted=False)
        path = mdu.parent / "boundary.bc"
        path.write_bytes(path.read_bytes().replace(b"S2 .20 30\n", b"S2 .20 30\n* row\n", 1))
        with self.assertRaises(DfmError):
            constituents.assign(mdu, "west", request, points=["west_0001"], create_missing=True)

    def test_constituents_tab_led_star_in_ext_keeps_current_refusal(self):  # control
        mdu, request = self.build("tab", noted=False)
        path = mdu.parent / "boundary.ext"
        path.write_bytes(path.read_bytes().replace(b"[Boundary]\n", b"[Boundary]\n\t* tab\n", 1))
        with self.assertRaises(DfmError):
            constituents.inspect(mdu, "west")


# ------------------------------------------------------------------------------------------ vertical (B13)

class VerticalFamily(Tmp):
    def build(self, name, *, noted):
        folder = self.root / name
        vertical_fixture.fixture(folder)
        if noted:
            for file, note in (("boundaries.ext", note_ini), ("initial.ini", note_ini), ("boundaries.bc", note_bc)):
                path = folder / file
                path.write_bytes(note(path.read_bytes()))
        return folder / "model.mdu"

    def call(self, *argv):
        code, value = run_cli(*argv)
        self.assertEqual((code, value["ok"]), (0, True), value)
        return value["result"]

    def inspect(self, mdu):
        return self.call("boundary", "vertical-inspect", mdu, "--boundary", "west", "--point", "west_0001",
                         "--quantity", "salinitybnd")

    def edit(self, mdu, *extra):
        return self.call("boundary", "vertical-set", mdu, "--boundary", "west", "--point", "west_0001", "--quantity",
                         "salinitybnd", "--time", "2.0e1", "--time-unit", vertical_fixture.TIME_UNIT, "--position",
                         "0.4", "--position-type", "percBed", "--value", "22.5000", "--unit", "ppt", *extra)

    def test_vertical_inspect_reads_commented_ext_inifield_and_bc_like_plain(self):  # NEW
        plain, noted = self.build("plain", noted=False), self.build("noted", noted=True)
        self.assertEqual(norm(self.inspect(noted), noted.parent), norm(self.inspect(plain), plain.parent))

    def test_vertical_set_keeps_comment_lines_byte_for_byte(self):  # NEW
        models = {name: self.build(name, noted=name == "noted") for name in ("plain", "noted")}
        before = {name: snapshot(mdu.parent) for name, mdu in models.items()}
        for mdu in models.values():
            preview = self.edit(mdu)
            self.edit(mdu, "--apply", "--expect-sha256", preview["input_sha256"])
        after = {name: snapshot(mdu.parent) for name, mdu in models.items()}
        changed = [p for p in after["plain"] if after["plain"][p] != before["plain"][p]]
        self.assertEqual(changed, ["boundaries.bc"])
        for path in after["noted"]:
            if path in changed:
                self.assertEqual(without_notes(after["noted"][path]), after["plain"][path])
                self.assertEqual(notes(after["noted"][path]), notes(before["noted"][path]))
            else:
                self.assertEqual(after["noted"][path], before["noted"][path], path)

    def test_vertical_tab_led_star_and_data_row_star_keep_current_refusal(self):  # control
        for file, old, new in (("boundaries.ext", b"[General]\n", b"[General]\n\t* tab\n"),
                               ("initial.ini", b"[Initial]\n", b"[Initial]\n\t* tab\n"),
                               ("boundaries.bc", b"2.0e1\t31", b"* row\r\n2.0e1\t31")):
            with self.subTest(file):
                mdu = self.build("c-" + file, noted=False)
                path = mdu.parent / file
                raw = path.read_bytes()
                self.assertIn(old, raw)
                path.write_bytes(raw.replace(old, new, 1))
                code, value = run_cli("boundary", "vertical-inspect", mdu, "--boundary", "west", "--point",
                                      "west_0001", "--quantity", "salinitybnd")
                self.assertNotEqual(code, 0, value)
                self.assertNotIn(value["error"]["code"], ("internal_error", "usage"))


# ------------------------------------------------------------------------------------------ source-sink (B06)

class SourceSinkFamily(SourceSinkFixture, unittest.TestCase):
    def note_files(self):
        for file, note in (("sources.ext", note_ini), ("sources.bc", note_bc)):
            path = self.root / file
            path.write_bytes(note(path.read_bytes()))

    def test_source_inspect_reads_commented_ext_and_bc_like_plain(self):  # NEW
        plain = norm(sources.inspect(self.mdu), self.root)
        self.note_files()
        self.assertEqual(norm(sources.inspect(self.mdu), self.root), plain)

    def edit(self, request, **kwargs):
        write = self.root / "request.json"
        write.write_text(json.dumps(request))
        preview = author.change(self.mdu, write, **kwargs)
        author.change(self.mdu, write, apply=True, expect_sha256=preview["sha256"], **kwargs)

    def test_source_set_keeps_comment_lines_byte_for_byte(self):  # NEW
        plain_before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.edit({"version": 1, "name": "new display name"}, id="Outfall+A")
        plain_after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        for name, raw in plain_before.items():
            (self.root / name).write_bytes(raw)
        self.note_files()
        noted_before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.edit({"version": 1, "name": "new display name"}, id="Outfall+A")
        noted_after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual({n for n in plain_before if plain_after[n] != plain_before[n]}, {"sources.ext"})
        self.assertEqual(without_notes(noted_after["sources.ext"]), plain_after["sources.ext"])
        self.assertEqual(notes(noted_after["sources.ext"]), notes(noted_before["sources.ext"]))
        for name in noted_before:
            if name != "sources.ext":
                self.assertEqual(noted_after[name], noted_before[name], name)

    def test_source_add_reads_commented_bc_and_ext(self):  # NEW
        (self.root / "intake.bc").write_bytes(SOURCE_SINK_BC.replace("Outfall+A", "Intake-B").replace("\n", "\r\n").encode())
        spec = {"version": 1, "id": "Intake-B", "location": {"coordinates": [["25", "15"], ["95", "25"]]},
                "discharge": {"bc": "intake.bc"}, "constituents": {"salinityDelta": {"bc": "intake.bc"}}, "area": "0"}
        self.note_files()
        (self.root / "intake.bc").write_bytes(note_bc((self.root / "intake.bc").read_bytes()))
        before = (self.root / "sources.ext").read_bytes()
        self.edit(spec, add=True)
        after = (self.root / "sources.ext").read_bytes()
        self.assertEqual(notes(after)[:len(notes(before))], notes(before))
        self.assertEqual([s["id"] for s in sources.inspect(self.mdu)["sources"]], ["Outfall+A", "Intake-B"])

    def test_source_data_row_star_and_tab_led_star_keep_current_refusal(self):  # control
        self.replace("sources.bc", b"120 0.1 5\r\n", b"* row\r\n120 0.1 5\r\n")
        self.error("", sources.inspect, self.mdu)

    def test_source_tab_led_star_in_ext_keeps_current_refusal(self):  # control
        self.replace("sources.ext", b"[SourceSink]\r\n", b"[SourceSink]\r\n\t* tab\r\n")
        self.error("", sources.inspect, self.mdu)


if __name__ == "__main__":
    unittest.main()
