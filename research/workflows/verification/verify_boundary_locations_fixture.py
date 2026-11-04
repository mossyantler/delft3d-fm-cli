"""B04-PLI-V independent authoring fixture and file oracle; no native entrypoints.

Only PublicAPI calls the producer, via a bounded public CLI subprocess.
All expected blocks/coordinates are authored here, without producer parsers,
identity helpers, planned_inventory or changed_files as an oracle.
"""
from contextvars import ContextVar
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = ContextVar("B04_PLI_V_artifacts", default=None)
INVENTORY = ".dfm-boundary-locations/inventory.json"
QUANTITIES = ("waterlevelbnd", "salinitybnd", "temperaturebnd")
FUNCTIONS = ("timeseries", "constant", "harmonic")
RAW_BC_ALERT = ("RAW BC RETIREMENT ALERT: selected Forcing byte slices must be physically absent from active BC; "
                "commenting/semantic normalization is insufficient. B04-PLI-G-east-contrast-02 observed "
                "0.18169346451759338 m waterlevel error despite zero exits; original bytes belong in event/originals only.")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def snapshot(root):
    """Actual relative file bytes, independent of producer manifests."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def fingerprints(root):
    return {name: {"sha256": sha(raw), "bytes": len(raw)} for name, raw in snapshot(root).items()}


def directories(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_dir())


def require(condition, message):
    # Evidence checks must remain active even if Python is run with -O.
    if not condition:
        raise AssertionError(message)


def without_authored_blocks(raw, retired):
    """Expected physical deletion from our known, independently authored bytes.

    No producer parser, byte spans, manifest or normalization supplies the oracle.
    Every other byte, including all whitespace/comments, stays exactly as-is.
    """
    spans = []
    for block_raw in retired:
        require(raw.count(block_raw) == 1, "Independent fixture block is missing or byte-ambiguous")
        start = raw.index(block_raw)
        spans.append((start, start + len(block_raw)))
    cursor = 0
    pieces = []
    for start, end in sorted(spans):
        require(start >= cursor, "Independent fixture block spans overlap")
        pieces.append(raw[cursor:start])
        cursor = end
    return b"".join(pieces) + raw[cursor:]


def require_raw_bc(actual, expected):
    require(actual == expected, RAW_BC_ALERT)


def sections(raw):
    """Small independent active INI oracle, preserving exact section slices.

    Fixture syntax only: comments begin # or ;, and no escaped delimiters.
    Duplicate quantity keys are retained as lists, not flattened.
    """
    result = []
    current = None
    for line in raw.decode("utf-8-sig").splitlines(keepends=True):
        code = line.split("#", 1)[0].strip()
        if code.startswith(";"):
            code = ""
        match = re.fullmatch(r"\[([^]]+)\]", code)
        if match:
            current = {"kind": match[1].strip().lower(), "fields": {}, "text": ""}
            result.append(current)
        if current is not None:
            current["text"] += line
            if "=" in code:
                key, value = code.split("=", 1)
                current["fields"].setdefault(key.strip().lower(), []).append(value.strip())
    return result


def forcing(raw):
    return [b for b in sections(raw) if b["kind"] == "forcing"]


def edges(raw):
    return [b["fields"] for b in sections(raw) if b["kind"] == "boundary"]


def pli_data(raw):
    lines = []
    for line in raw.decode("utf-8-sig").splitlines():
        code = line.split("#", 1)[0].strip()
        if code and not code.startswith(";"):
            lines.append(code)
    label = lines[0]
    rows, cols = map(int, lines[1].split())
    require(cols == 2 and len(lines) == rows + 2, "Unexpected independent PLI shape")
    data = [line.split() for line in lines[2:]]
    for index, row in enumerate(data, 1):
        require(len(row) in (2, 3), "Expected XY plus optional text support ID")
        if len(row) == 3:
            require(row[2] == f"{label}_{index:04d}", "Wrong independent support identity")
    return label, data


def xy(raw):
    label, data = pli_data(raw)
    return label, [tuple(Decimal(t.replace("D", "E").replace("d", "e")) for t in row[:2]) for row in data]


def support_ids(raw):
    return [row[2] if len(row) == 3 else None for row in pli_data(raw)[1]]


def block(name, quantity, function, ordinal):
    # Repeated Name across quantities/functions is intentional, not a map key.
    common = (f"[Forcing]\r\n  Name = {name}\r\n  Function = {function}\r\n"
              f"  V_unknown = keep-{ordinal} # unrecognized metadata\r\n")
    if function == "timeseries":
        body = ("  Time-interpolation = linear\r\n  Quantity = time\r\n"
                "  Unit = seconds since 2026-03-02 00:00:00 +00:00\r\n"
                f"  Quantity = {quantity}\r\n  Unit = m\r\n  0.0 {ordinal}.125\r\n  120.0 {ordinal}.875\r\n")
    elif function == "constant":
        body = f"  Quantity = {quantity}\r\n  Unit = ppt\r\n  {ordinal}.250\r\n"
    else:
        body = ("  Quantity = harmonic component\r\n  Unit = degrees/hour\r\n"
                f"  Quantity = {quantity} amplitude\r\n  Unit = degC\r\n"
                f"  Quantity = {quantity} phase\r\n  Unit = degrees\r\n  28.9841042 {ordinal}.5 13.25\r\n")
    return (common + body + f"# tail-marker-{ordinal}\r\n\r\n").encode()


class Fixture:
    """Two independent XY lines, three points, one BC shared by six EXT edges."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.model = self.root / "dedicated model"
        self.model.mkdir()
        self.incoming = self.root / "external sources"
        self.incoming.mkdir()
        self.mdu = self.model / "independent.mdu"
        self.bc = self.model / "signals.bc"
        self.ext = self.model / "conditions.ext"
        self.source = self.incoming / "north.pli"
        self.out = self.root / "new working copy"
        self.mdu.write_bytes(b"# independently authored, not an engine-ready mesh\r\n[General]\r\nFileVersion = 1.09\r\nFileType = modelDef\r\nPathsRelativeToParent = 0\r\n[Geometry]\r\nNetFile = geometry/grid.nc\r\n[External Forcing]\r\nExtForceFileNew = conditions.ext # retain inline note\r\n[Output]\r\nOutputDir = output\r\n[Independent]\r\nCustom = untouched metadata\r\n")
        self.original_pli = {}
        for line, x in (("north", "101.250"), ("south", "901.750")):
            raw = (f"# {line} original preamble\r\n  {line}  # exact identity\r\n  3   2 # row count\r\n"
                   f" {x}  11.00 # first-support\r\n {x}\t22.00 # middle-support\r\n {x}  33.00 # end-support\r\n# preserve trailing note\r\n").encode()
            (self.model / (line + ".pli")).write_bytes(raw)
            self.original_pli[line] = raw
        self.ext_blocks = []
        for line in ("north", "south"):
            for quantity in QUANTITIES:
                self.ext_blocks.append((line, quantity,
                    (f"[Boundary]\r\nquantity = {quantity}\r\nlocationFile = {line}.pli\r\n"
                     f"forcingFile = signals.bc\r\n# EXT-{line}-{quantity}-keep\r\n\r\n").encode()))
        self.ext.write_bytes(b"# independent EXT header\r\n[General]\r\nfileVersion = 2.01\r\nfileType = extForce\r\n\r\n" + b"".join(b for _, _, b in self.ext_blocks))
        self.signal_blocks = []
        for n, line in enumerate(("north", "south")):
            for point in range(1, 4):
                for q, (quantity, function) in enumerate(zip(QUANTITIES, FUNCTIONS)):
                    self.signal_blocks.append((line, block(f"{line}_{point:04d}", quantity, function, 100*n+10*point+q)))
        # Whole-line and inactive support identities must also be cleared.
        self.signal_blocks += [("north", block("north", "waterlevelbnd", "constant", 401)),
                               ("north", block("north_9999", "salinitybnd", "constant", 402)),
                               ("unrelated", block("northwest_0001", "waterlevelbnd", "constant", 403))]
        self.bc_header = b"# shared BC preserved header\r\n[General]\r\nfileVersion = 1.01\r\nfileType = boundConds\r\n\r\n"
        self.bc.write_bytes(self.bc_header + b"".join(b for _, b in self.signal_blocks) + b"[Vendor]\r\nopaque = do not rewrite\r\n")
        (self.model / "geometry").mkdir()
        (self.model / "geometry/grid.nc").write_bytes(b"not-a-netcdf; opaque file-only sentinel\x00\x01")
        (self.model / "output").mkdir()
        (self.model / "output/old.bin").write_bytes(bytes(range(256)))
        (self.model / "empty folder").mkdir()
        (self.model / "unknown.txt").write_bytes(b"arbitrary\r\nnon-model\x00bytes\xff")
        self.write_source()

    def write_source(self, label="north", basename="north.pli", count=3):
        # A differently cased path to an existing file does not create a
        # differently cased *physical basename* on Windows. Use a new directory.
        folder = self.incoming
        previous = getattr(self, "source", None)
        if previous is not None and previous.name != basename and previous.name.casefold() == basename.casefold():
            folder = self.incoming / "distinct physical basename"
            folder.mkdir(exist_ok=False)
        self.source = folder / basename
        self.source.write_bytes((f"# independent incoming geometry\n{label}\n{count} 2\n" +
                                 "".join(f"205.500 {31+i*10}.250\n" for i in range(count))).encode())
        return self.source


class PublicAPI:
    """Actual public dfm entrypoint; no producer imports or temporary parser wiring.

    Only schema inspect and boundary location-import may be invoked. Each bounded
    Python CLI process has its raw stdout/stderr and actual exit code retained.
    """
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else None
        self.calls = []
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=False)

    def invoke(self, arguments):
        if not (arguments == ["schema", "inspect"] or arguments[:2] == ["boundary", "location-import"]):
            raise AssertionError("Portable verifier command allowlist violated")
        argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)]
        row = {"interface": "public dfm CLI", "argv": argv, "cwd": str(ROOT), "timeout_seconds": 30}
        raw_stdout = raw_stderr = b""
        try:
            process = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=30)
            raw_stdout, raw_stderr = process.stdout, process.stderr
            payload = json.loads(raw_stdout)
            if payload.get("protocol_version") != 2 or (process.returncode == 0) != (payload.get("ok") is True):
                raise AssertionError(f"Public JSON/exit protocol mismatch: {process.returncode}, {payload}")
            row.update(payload)
            row["returncode"] = process.returncode
            if not row["ok"]:
                row["error"]["exit_code"] = process.returncode
            if raw_stderr:
                raise AssertionError(f"Unexpected public CLI stderr: {raw_stderr!r}")
        except Exception as exc:
            row.update(ok=False, unexpected_exception={"type": type(exc).__name__, "message": str(exc)})
            raise
        finally:
            self.calls.append(row)
            if self.folder:
                prefix = self.folder / f"{len(self.calls):03d}"
                prefix.with_suffix(".stdout.json").write_bytes(raw_stdout)
                prefix.with_suffix(".stderr.txt").write_bytes(raw_stderr)
                save(prefix.with_suffix(".json"), row)
        return row

    def call(self, fixture, **options):
        options = {"coordinates": "as-is", **options}
        args = ["boundary", "location-import", fixture.mdu, "--source", fixture.source, "--out", fixture.out]
        for key, value in options.items():
            if value is None or value is False:
                continue
            args.append("--" + key.replace("_", "-"))
            if value is not True:
                args.append(value)
        return self.invoke(args)


def author_target_last(fixture):
    """Author west-first/east-last independently; both BC and EXT end at target.

    EOF deliberately lacks a newline. No producer helper/export or native model
    is used to manufacture the expected surviving west signals.
    """
    for old, new in (("north", "east"), ("south", "west")):
        source = fixture.model / (old + ".pli")
        target = fixture.model / (new + ".pli")
        source.rename(target)
        target.write_bytes(target.read_bytes().replace(old.encode(), new.encode()))
    fixture.write_source(label="east", basename="east.pli")
    signals = {"west": [], "east": []}
    ext = {"west": [], "east": []}
    for line, base in (("west", 500), ("east", 700)):
        for point in range(1, 4):
            for q, (quantity, function) in enumerate(zip(QUANTITIES, FUNCTIONS)):
                signals[line].append(block(f"{line}_{point:04d}", quantity, function, base + point*10 + q))
        for quantity in QUANTITIES:
            ext[line].append((f"[Boundary]\r\nquantity = {quantity}\r\nlocationFile = {line}.pli\r\n"
                              f"forcingFile = signals.bc\r\n# target-last-{line}-{quantity}\r\n\r\n").encode())
    prefix = fixture.bc_header + b"[Vendor]\r\nopaque = preserve before signals\r\n\r\n"
    fixture.bc.write_bytes(prefix + b"".join(signals["west"]) + b"".join(signals["east"]).rstrip(b"\r\n"))
    ext_prefix = b"# independent target-last EXT\r\n[General]\r\nfileVersion = 2.01\r\nfileType = extForce\r\n\r\n"
    fixture.ext.write_bytes(ext_prefix + b"".join(ext["west"]) + b"".join(ext["east"]).rstrip(b"\r\n"))
    return signals, ext, prefix, ext_prefix


def verify_copy(fixture, before, report, *, replacement):
    """Checks disk bytes/active signals first; producer inventory is secondary."""
    out = fixture.out
    after = snapshot(out)
    require(snapshot(fixture.model) == before, "Original tree changed")
    require((out / "empty folder").is_dir(), "Empty directory lost")
    changed = {"north.pli", "signals.bc", "conditions.ext"} if replacement else set()
    for name, raw in before.items():
        if name not in changed:
            require(after[name] == raw, f"Non-target original bytes changed: {name}")
    if replacement:
        require(xy(after["north.pli"]) == xy(fixture.source.read_bytes()), "Wrong replacement coordinates")
        for note in (b"# north original preamble", b"# exact identity", b"# row count", b"# first-support", b"# middle-support", b"# end-support", b"# preserve trailing note"):
            require(note in after["north.pli"], f"Lost selected PLI non-coordinate text: {note}")
        expected = [sections(raw)[0]["fields"] for owner, raw in fixture.signal_blocks if owner != "north"]
        require([b["fields"] for b in forcing(after["signals.bc"])] == expected, "Wrong surviving forcing or target signal survived")
        raw_expected = without_authored_blocks(before["signals.bc"],
                                               [raw for owner, raw in fixture.signal_blocks if owner == "north"])
        require_raw_bc(after["signals.bc"], raw_expected)
        for owner, raw in fixture.signal_blocks:
            if owner != "north":
                require(raw in after["signals.bc"], "Non-target forcing block bytes changed")
        require(after["signals.bc"].startswith(fixture.bc_header), "BC header bytes changed")
        require(after["signals.bc"].endswith(b"[Vendor]\r\nopaque = do not rewrite\r\n"), "Unknown metadata changed")
        expected_edges = [sections(raw)[0]["fields"] for line, _, raw in fixture.ext_blocks if line != "north"]
        require(edges(after["conditions.ext"]) == expected_edges, "Wrong active EXT edges")
        for line, _, raw in fixture.ext_blocks:
            if line != "north":
                require(raw in after["conditions.ext"], "Other EXT boundary bytes changed")
    else:
        label, _ = xy(fixture.source.read_bytes())
        geometry = f".dfm-boundary-locations/objects/{label}/{fixture.source.name}"
        require(after[geometry] == fixture.source.read_bytes(), "Unbound addition differs from source")
        require(geometry.encode() not in after["conditions.ext"], "New line falsely added to active EXT")
        require(len(edges(after["conditions.ext"])) == 6, "Addition replaced an active boundary")
    inventory = json.loads(after[INVENTORY])
    target_label = xy(fixture.source.read_bytes())[0]
    target = [o for o in inventory["objects"] if o["label"] == target_label]
    require(len(target) == 1 and target[0]["status"] == "unbound" and target[0]["engine_bindings"] == [], "False active target binding")
    # Inventory must describe actual output, not merely repeat preview assertions.
    listed = {name: {"sha256": sha(raw), "bytes": len(raw)} for name, raw in after.items() if name != INVENTORY}
    require(inventory["output_files"] == listed, "Inventory does not bind actual output bytes")
    require(sha(after[INVENTORY]) == report["inventory_sha256"], "Inventory digest mismatch")
    archive = out / ".dfm-boundary-locations/imports" / report["input_sha256"]
    require((archive / "source" / fixture.source.name).read_bytes() == fixture.source.read_bytes(), "Source archive missing")
    for name in changed:
        require((archive / "originals" / name).read_bytes() == before[name], f"Missing exact before-image: {name}")
    require(inventory["CRS"]["transformation_performed"] is False, "False transform claim")
    require(inventory["CRS"]["common_CRS_asserted"] is False, "False CRS claim")
    require(inventory["CRS"]["height_datum_assumed"] is False, "False height datum claim")
    return {"actual_files": len(after), "actual_active_forcing": len(forcing(after["signals.bc"])),
            "actual_active_EXT_edges": len(edges(after["conditions.ext"])), "inventory_sha256": sha(after[INVENTORY])}
