"""Independent public B04 projection fixture, subprocess client and byte oracle.

No product imports. The frozen independent M3 writer is used read-only to
author a fresh real NetFile in research mode. Portable as-is cases deliberately
use an opaque .nc leaf, demonstrating that this path needs no NetCDF reader.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ".dfm-boundary-locations/inventory.json"
NUMBER = rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?"
ROW = re.compile(rb"(?m)^[ \t]*(?P<x>"+NUMBER+rb")[ \t]+(?P<y>"+NUMBER+rb")[ \t]+[A-Za-z][A-Za-z0-9_]*_[0-9]{4}(?=[ \t#;\r\n]|$)")
POINTS = ((3.0, 0.0), (4.0, 50.0), (2.0, 20.0))


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def snapshot(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def directories(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_dir())


def fingerprints(root):
    return {name: {"sha256": sha(raw), "bytes": len(raw)} for name,raw in snapshot(root).items()}


def coordinate_tokens(raw):
    return [[row.group("x"), row.group("y")] for row in ROW.finditer(raw)]


def xy(raw):
    return [[float(v.replace(b"D", b"E").replace(b"d", b"e")) for v in row] for row in coordinate_tokens(raw)]


def skeleton(raw):
    """Retain EVERY byte except the six known coordinate-token spans."""
    patches = [(match.start(axis), match.end(axis)) for match in ROW.finditer(raw) for axis in ("x", "y")]
    require(len(patches) == 6, "Independent fixture requires exactly three labelled XY rows")
    result, last = bytearray(), 0
    for start, end in patches:
        result.extend(raw[last:start]); result.extend(b"<COORDINATE>"); last = end
    result.extend(raw[last:])
    return bytes(result)


def with_coordinate_tokens(raw, tokens):
    """Reconstruct incoming PLI with output coordinates; never calls producer."""
    matches = list(ROW.finditer(raw))
    require(len(matches) == len(tokens) == 3, "Independent coordinate count mismatch")
    spans = [(match.start(axis), match.end(axis), word) for match, words in zip(matches,tokens) for axis, word in zip(("x","y"),words)]
    pieces, cursor = [], 0
    for start,end,word in spans:
        pieces.extend((raw[cursor:start],word)); cursor=end
    pieces.append(raw[cursor:])
    return b"".join(pieces)


def projection_receipt(result, fixture, before, geometry_raw):
    """Validate public receipt against actual input/output bytes, not itself."""
    receipts = []
    def visit(value):
        if type(value) is dict:
            if value.get("contract") == "boundary-location-projection-adapter-v1":
                receipts.append(value)
            for nested in value.values(): visit(nested)
        elif type(value) is list:
            for nested in value: visit(nested)
    visit(result)
    require(receipts, "Public transform omitted the independently attributable projection receipt")
    projected_source = with_coordinate_tokens(fixture.source.read_bytes(),coordinate_tokens(geometry_raw))
    require(skeleton(projected_source) == skeleton(fixture.source.read_bytes()), "Independent projected source reconstruction damaged metadata")
    for receipt in receipts:
        require(receipt.get("source_raw_sha256") == sha(fixture.source.read_bytes()) and receipt.get("result_sha256") == sha(projected_source), "Receipt does not bind actual raw/transformed source bytes")
        model = receipt.get("target_model",{})
        require(model.get("netfile_reference") == "geometry/grid.nc" and model.get("mesh",{}).get("sha256") == sha(before["geometry/grid.nc"]) and
                model.get("mdu",{}).get("sha256") == sha(before["channel.mdu"]), "Receipt target MDU/NetFile fingerprints differ from actual inputs")
        require(Path(model["mesh"]["path"]).resolve() == fixture.net.resolve() and Path(model["mdu"]["path"]).resolve() == fixture.mdu.resolve(), "Receipt attributed CRS to the wrong input path")
        crs = model.get("horizontal_crs",{})
        require(crs.get("mapping_variable") == "projected_coordinate_system" and crs.get("epsg") == 32631 and crs.get("unit") == "m" and
                crs.get("coordinate_order") == ["mesh2d_node_x","mesh2d_node_y"], "Receipt did not attribute CRS to actual node X/Y mapping")
        axes=crs.get("node_coordinates",[])
        require(len(axes)==2 and all(axis.get("grid_mapping")=="projected_coordinate_system" and axis.get("units")=="m" for axis in axes), "Receipt XY grid mapping/units mismatch")
        transform=receipt.get("transformation",{})
        require(transform.get("source",{}).get("declaration")=="EPSG:4326" and transform.get("target",{}).get("declaration")=="EPSG:32631" and
                transform["source"].get("unit")=="degree" and transform["target"].get("unit")=="m" and transform.get("axis_order")=="file_xy", "Receipt CRS/unit declarations mismatch")
        require(transform.get("operation",{}).get("network_enabled") is False and transform["operation"].get("ballpark_allowed") is False, "Receipt lacks strict offline operation proof")
        require(receipt.get("native_validation")=="not_performed" and receipt.get("engine_binding")=="unbound_authoring_only" and
                receipt.get("mdu_mesh_source_modified") is False, "Receipt falsely promotes authoring to native/engine validation")
    return {"receipt_count":len(receipts),"projected_source_sha256":sha(projected_source),"raw_source_sha256":sha(fixture.source.read_bytes()),"actual_mesh_sha256":sha(before["geometry/grid.nc"])}


def sections(raw):
    """Independent fixture-only active section fields; comments remain in bytes."""
    result = []
    for line in raw.decode("utf-8").splitlines():
        code = re.split(r"[#;]", line, maxsplit=1)[0].strip()
        if code.startswith("[") and code.endswith("]"):
            result.append({"kind": code[1:-1].lower(), "fields": []})
        elif code and "=" in code and result:
            key, value = code.split("=", 1)
            result[-1]["fields"].append((key.strip().lower(), value.strip()))
    return result


def expected_active_bc(fixture, original, *, replacement):
    """Independent exact-slice expectation: no retired text in active BC."""
    result=original
    if replacement:
        for name,block in fixture.bc_blocks.items():
            if name.startswith("north_"):
                require(result.count(block)==1,"Retired fixture BC slice is missing/ambiguous")
                result=result.replace(block,b"",1)
    return result


class Fixture:
    def __init__(self, root, *, real_mesh=False):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=False)
        self.model = self.root/"dedicated model"; self.model.mkdir()
        self.incoming = self.root/"incoming"; self.incoming.mkdir()
        self.out = self.root/"new output"
        self.mdu = self.model/"channel.mdu"
        self.net = self.model/"geometry/grid.nc"; self.net.parent.mkdir()
        self.source = self.incoming/"north.pli"
        self.mdu.write_bytes(b"# independent public projection test\r\n[General]\r\nFileVersion = 1.09\r\nFileType = modelDef\r\nPathsRelativeToParent = 0\r\n[Geometry]\r\nNetFile = geometry/grid.nc # attributable mesh\r\nBedlevType = 3\r\n[External Forcing]\r\nExtForceFileNew = conditions.ext\r\n[Output]\r\nOutputDir = output\r\n")
        if real_mesh:
            from .channel_fixture import write_mesh
            write_mesh(self.net)
        else:
            self.net.write_bytes(b"OPAQUE AS-IS LEAF; NO NETCDF READER SHOULD OPEN THIS\n")
        self.pli = {}
        for label, x in (("north", 500000), ("south", 500120)):
            raw = (f"# ORIGINAL {label} retained preamble\r\n  {label} # identity\r\n 3\t2 # dimensions\r\n"
                   f" {x}.0000\t5700000.0 {label}_0001 # support one\r\n"
                   f" +{x}.0  5700010.000 {label}_0002 # support two\n"
                   f" {x}.000000\t5700020.0 {label}_0003 # support three\r\n# original trailing metadata\r\n").encode()
            (self.model/(label+".pli")).write_bytes(raw); self.pli[label] = raw
        self.bc_blocks = {}
        bc = b"# SHARED SIGNALS opaque comment\r\n[General]\r\nfileVersion = 1.01\r\nfileType = boundConds\r\n\r\n"
        for label in ("north", "south"):
            for row in range(1, 4):
                name = f"{label}_{row:04d}"
                block = (f"[Forcing]\r\nName = {name}\r\nFunction = timeseries\r\nTime-interpolation = linear\r\nQuantity = time\r\nUnit = seconds since 2026-01-01 00:00:00\r\nQuantity = waterlevelbnd\r\nUnit = m\r\n0 {row}.125\r\n120 {row}.250\r\n# retained {name} tail\r\n\r\n").encode()
                self.bc_blocks[name] = block; bc += block
        (self.model/"signals.bc").write_bytes(bc)
        ext = b"# EXT retained header\r\n[General]\r\nfileVersion = 2.01\r\nfileType = extForce\r\n\r\n"
        self.ext_blocks = {}
        for label in ("north", "south"):
            block = (f"[Boundary]\r\nQuantity = waterlevelbnd\r\nLocationFile = {label}.pli\r\nForcingFile = signals.bc\r\n# {label} edge retained note\r\n\r\n").encode()
            self.ext_blocks[label] = block; ext += block
        (self.model/"conditions.ext").write_bytes(ext)
        (self.model/"unknown.bin").write_bytes(b"unknown vendor bytes\0\xff\xfe")
        (self.model/"empty folder").mkdir()
        self.write_source()

    def write_source(self, *, label="north", basename="north.pli"):
        self.source = self.incoming/basename
        raw = (f"# INCOMING original source archive\n; standalone preserved comment\n\t{label}  # label\r\n3 2 # source dimension comment\n"
               f" +3.0000D+00\t0.000000 {label}_0001 # exact equator control\r\n"
               f" 4.000000  +5.0000E+01 {label}_0002 # noncentral point\n"
               f" 2.0000\t20.000000 {label}_0003 # third control\r\n# incoming tail must remain\n").encode()
        self.source.write_bytes(raw)
        return raw

    def place_selected_bc_last(self):
        """Author the opposite ordering before preview, reproducing #130's tail."""
        path=self.model/"signals.bc"
        raw=path.read_bytes();header=raw[:raw.index(b"[Forcing]")]
        path.write_bytes(header+b"".join(self.bc_blocks[f"{label}_{row:04d}"] for label in ("south","north") for row in range(1,4)))

    def mutate_mesh(self, kind):
        """Each case owns a fresh synthetic file; never edits retained/original evidence."""
        from netCDF4 import Dataset
        with Dataset(self.net, "a") as ds:
            mapping = ds.variables["projected_coordinate_system"]
            x, y = ds.variables["mesh2d_node_x"], ds.variables["mesh2d_node_y"]
            if kind == "conflicting_epsg":
                mapping.EPSG_code = "EPSG:32632"
            elif kind == "absent_crs":
                for key in list(mapping.ncattrs()):
                    mapping.delncattr(key)
                mapping.assignValue(0)
            elif kind == "orphan_mapping":
                x.delncattr("grid_mapping"); y.delncattr("grid_mapping")
            elif kind == "conflicting_xy_mapping":
                extra = ds.createVariable("unrelated_crs", "i4")
                extra.EPSG_code = "EPSG:32632"; y.grid_mapping = "unrelated_crs"
            elif kind == "wrong_axis_units":
                x.units = "degree"
            elif kind == "absent_axis_units":
                y.delncattr("units")
            elif kind == "wrong_axis_role":
                x.standard_name = "projection_y_coordinate"
            elif kind == "unrelated_spoof":
                mapping.EPSG_code = "EPSG:32632"; mapping.epsg = 32632
                extra = ds.createVariable("unrelated_crs", "i4"); extra.EPSG_code = "EPSG:32631"
            elif kind == "only_uppercase_epsg":
                for key in ("epsg", "epsg_code", "proj4_params"):
                    if key in mapping.ncattrs(): mapping.delncattr(key)
            else:
                raise ValueError(kind)

    def mesh_metadata(self):
        from netCDF4 import Dataset
        with Dataset(self.net, "r") as ds:
            mapping = ds.variables["projected_coordinate_system"]
            # Raw evidence is deliberately independent of product mesh parsers.
            return {"NetFile": "geometry/grid.nc", "sha256": sha(self.net.read_bytes()),
                    "topology_node_coordinates": ds.variables["mesh2d"].getncattr("node_coordinates"),
                    "mapping_attributes": {key: str(mapping.getncattr(key)) for key in mapping.ncattrs()},
                    "axes": {name: {key: str(ds.variables[name].getncattr(key)) for key in ("grid_mapping", "units", "standard_name") if key in ds.variables[name].ncattrs()}
                             for name in ("mesh2d_node_x", "mesh2d_node_y")}}


class PublicCLI:
    def __init__(self, folder, *, no_site=False):
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=False)
        self.no_site, self.calls = no_site, []

    def invoke(self, args):
        require(args[:2] == ["boundary", "location-import"], "Native-free verifier CLI allowlist violated")
        argv = [sys.executable, "-B", *(["-S"] if self.no_site else []), "-m", "dfm_cli", *map(str, args)]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT/"src")
        record = {"argv": argv, "cwd": str(ROOT), "no_site": self.no_site, "timeout_seconds": 30}
        process = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, timeout=30)
        prefix = self.folder/f"{len(self.calls)+1:03d}"
        prefix.with_suffix(".stdout").write_bytes(process.stdout)
        prefix.with_suffix(".stderr").write_bytes(process.stderr)
        record.update(returncode=process.returncode, stdout_sha256=sha(process.stdout), stderr_sha256=sha(process.stderr))
        if "--help" in args:
            record["help"] = process.stdout.decode("utf-8")
        else:
            payload = json.loads(process.stdout)
            require(payload.get("protocol_version") == 2 and (process.returncode == 0) == (payload.get("ok") is True), "Public protocol/exit mismatch")
            require(payload.get("error", {}).get("code") not in {"internal_error", "io_or_data_error"}, "Unhandled product error")
            record.update(payload)
        save(prefix.with_suffix(".json"), record); self.calls.append(record)
        return record

    def call(self, fixture, *, coordinates="transform", source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="degree", target_unit="m", apply=False, expect_sha256=None):
        args = ["boundary", "location-import", fixture.mdu, "--source", fixture.source, "--out", fixture.out, "--coordinates", coordinates]
        for flag, value in (("source-crs", source_crs), ("target-crs", target_crs), ("source-unit", source_unit), ("target-unit", target_unit)):
            if value is not None:
                args.extend(["--"+flag, value])
        if apply: args.append("--apply")
        if expect_sha256 is not None: args.extend(["--expect-sha256", expect_sha256])
        return self.invoke(args)


def verify_copy(fixture, before, result, *, replacement, transformed=True):
    after = snapshot(fixture.out)
    require(snapshot(fixture.model) == before, "Original model input bytes changed")
    label = "north" if replacement else "new_line"
    geometry = "north.pli" if replacement else ".dfm-boundary-locations/objects/new_line/new_line.pli"
    expected_skeleton = before["north.pli"] if replacement else fixture.source.read_bytes()
    require(skeleton(after[geometry]) == skeleton(expected_skeleton), "Bytes outside coordinate tokens changed")
    if transformed:
        from .verify_boundary_location_crs_controls import forward, FORWARD_TOLERANCE_M
        expected = [forward(*point) for point in POINTS]
        require(len(xy(after[geometry])) == 3 and all(max(abs(a-b) for a,b in zip(actual, target)) <= FORWARD_TOLERANCE_M for actual,target in zip(xy(after[geometry]),expected)), "Public geometry differs from independent UTM controls")
    else:
        require(coordinate_tokens(after[geometry]) == coordinate_tokens(fixture.source.read_bytes()), "As-is changed coordinate spellings")
    changed = {"north.pli", "conditions.ext", "signals.bc"} if replacement else set()
    for name, raw in before.items():
        if name not in changed:
            require(after[name] == raw, "Unrelated copied input changed: "+name)
    forcing = [dict(row["fields"]).get("name") for row in sections(after["signals.bc"]) if row["kind"] == "forcing"]
    expected_forcing = [f"{owner}_{row:04d}" for owner in (("south",) if replacement else ("north", "south")) for row in range(1,4)]
    require(forcing == expected_forcing, "Active forcing graph changed beyond selected line")
    require(after["signals.bc"]==expected_active_bc(fixture,before["signals.bc"],replacement=replacement),
            "Active BC must equal original minus exact retired blocks; commented retirement is physically unsafe")
    for name, block in fixture.bc_blocks.items():
        if not replacement or name.startswith("south_"):
            require(block in after["signals.bc"], "Unrelated forcing bytes changed")
    edges = [dict(row["fields"]).get("locationfile") for row in sections(after["conditions.ext"]) if row["kind"] == "boundary"]
    require(edges == (["south.pli"] if replacement else ["north.pli", "south.pli"]), "Wrong active EXT graph")
    require(fixture.ext_blocks["south"] in after["conditions.ext"], "Other EXT boundary bytes changed")
    inventory = json.loads(after[INVENTORY])
    imported = [obj for obj in inventory["objects"] if obj["label"] == label]
    require(len(imported) == 1 and imported[0]["status"] == "unbound" and imported[0]["engine_bindings"] == [], "False engine binding")
    archive = fixture.out/".dfm-boundary-locations/imports"/result["input_sha256"]
    require((archive/"source"/fixture.source.name).read_bytes() == fixture.source.read_bytes(), "Raw incoming PLI archive lost")
    for name in changed:
        require((archive/"originals"/name).read_bytes() == before[name], "Original archive differs: "+name)
    require(inventory["output_files"] == {name:{"sha256":sha(raw),"bytes":len(raw)} for name,raw in after.items() if name != INVENTORY}, "Inventory differs from actual output files")
    require(sha(after[INVENTORY]) == result["inventory_sha256"], "Inventory hash differs")
    require(inventory["CRS"]["transformation_performed"] is transformed, "Transformation declaration wrong")
    require((fixture.out/"empty folder").is_dir(), "Empty directory lost")
    receipt = projection_receipt(result,fixture,before,after[geometry]) if transformed else None
    if transformed:
        projected_source = with_coordinate_tokens(fixture.source.read_bytes(),coordinate_tokens(after[geometry]))
        require((archive/"projected-source"/fixture.source.name).read_bytes()==projected_source, "Archived projected PLI differs outside coordinates or from authored coordinates")
        require(result.get("projection")==inventory.get("projection") and json.loads((archive/"projection.json").read_bytes())==result.get("projection"), "Public/inventory/archived projection receipts disagree")
    return {"geometry":geometry,"coordinate_skeleton_sha256":sha(skeleton(after[geometry])),"files":fingerprints(fixture.out),"active_forcing":forcing,"active_EXT":edges,"netfile_sha256":sha(after["geometry/grid.nc"]),"projection_receipt":receipt}
