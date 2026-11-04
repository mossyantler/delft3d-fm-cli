"""Independent B11 raw-input/output oracle. Never launches a process or GUI.

Prepare before changed outputs exist:
  --prepare --inputs-root I_PREPARED/cases --out NEW_V_FOLDER
Verify the frozen eight cases, using {version:1,runs:[{case_id,path},...]}:
  --predeclared NEW_V_FOLDER/predeclared.json --runs RUNS.json --out NEW

No producer, product or other comparator imports. This deliberately bounded
oracle does not establish GUI attribute-table save/export parity or calibration.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, localcontext
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import uuid

import netCDF4 as nc
import numpy as np

VERSION = "B11-COEFF-V-1"
EPOCH = "seconds since 2026-01-01 00:00:00 +00:00"
TIMES = [0, 20, 120, 240]
LEVELS = {
    "east_0001": ["0", ".03125", "-.015625", ".046875"],
    "east_0002": ["0", "-.0234375", ".0390625", ".0078125"],
    "west_0001": ["0", ".015625", "-.0078125", ".0234375"],
    "west_0002": ["0", "-.015625", ".03125", "-.00390625"],
}
CASES = ["default", "east_implicit_defaults", "east_factor2", "east_factor2_manual",
         "east_offset0125", "east_offset0125_manual", "east_factor2_late_header", "east_offset0125_late_header"]
FILES = {"model.mdu", "boundaries.ext", "boundaries.bc", "boundary_east.pli", "boundary_west.pli",
         "mesh_net.nc", "observations.xyn", "create-spec.json", "create-provenance.json"}
NATIVE_INPUTS = FILES - {"create-spec.json", "create-provenance.json"}
OUTPUTS = {"history": "model_his.nc", "map": "model_map.nc",
           "restart_initial": "model_20260101_000000_rst.nc", "restart_final": "model_20260101_000200_rst.nc"}
PLAN = {
    "version": VERSION, "cases": CASES, "raw_knot_seconds": TIMES, "raw_levels_m": LEVELS,
    "target": "east waterlevelbnd at both active supports; west INPUT bytes unchanged in all eight cases",
    "quantity": "waterlevelbnd", "unit": "m", "time_unit": EPOCH, "factor_unit": "1", "offset_unit": "m",
    "source_mechanism": "FM new EXT POLY_TIM -> ecSetFileReaderProperties/provider_initialize -> ecProviderCreatePolyTimItemsBC -> ecBCInit/ecBCFilescan/processhdr; global Factor/Offset only before first Quantity",
    "arithmetic": "native source value * factor + offset; dyadic raw knots and corrections exactly representable in binary64",
    "late_header": "nondefault coefficient after the waterlevel Quantity/Unit should be ignored by this pinned FM reader; requires installed native confirmation",
    "pairs_exact": [["default", "east_implicit_defaults"], ["east_factor2", "east_factor2_manual"],
                    ["east_offset0125", "east_offset0125_manual"], ["default", "east_factor2_late_header"],
                    ["default", "east_offset0125_late_header"]],
    "numerical_tolerances": {"absolute": 0, "relative": 0, "ULPs": 0, "masked_payload": "exact storage too"},
    "comparison": "Every native variable, dimensions/unlimited flags, dtype, attributes, raw storage, decoded masks and valid values; no unlisted variable exclusions, including both complete restarts",
    "clocks": {"epoch": EPOCH, "calendar": "standard", "history_map_seconds": list(range(0, 121, 10)),
               "restart_initial_seconds": [0], "restart_final_seconds": [120]},
    "response": {"cases": ["east_factor2", "east_offset0125"], "minimum_abs_delta_m": .001,
                 "minimum_postinitial_times": 2, "history_station": "near_east", "history_variable": "waterlevel",
                 "map_variable": "mesh2d_s1", "minimum_map_faces": 2,
                 "final_restart_variable": "s1", "minimum_final_restart_elements": 2,
                 "west_output": "may respond physically; no unchanged-west-output predicate"},
    "volatile_global_metadata": ["uuid", "history", "date_created", "date_modified"],
    "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431", "installed_source_commit": "unknown",
    "scope": "48-cell cold 2D, two water-level lines, four scalar linear TS supports, 120 seconds; no harmonic/vector/other quantities, GUI/export or calibration claim",
    "native_execution_by_verifier": False,
}
NUMBER = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")
VOLATILE = set(PLAN["volatile_global_metadata"])


def need(ok, message):
    if not ok:
        raise ValueError(message)


def ordinary(path):
    path = Path(os.path.abspath(path))
    for p in (path, *path.parents):
        s = p.lstat()
        need(not stat.S_ISLNK(s.st_mode) and not getattr(s, "st_file_attributes", 0) & 0x400, "Linked/reparse route: " + str(p))
    if path.is_file():
        need(path.stat().st_nlink == 1, "Hardlinked file: " + str(path))
    return path


def sha(path):
    path = ordinary(path); before = path.stat(); h = hashlib.sha256()
    with path.open("rb") as f:
        while b := f.read(1024**2): h.update(b)
        opened = os.fstat(f.fileno())
    after = ordinary(path).stat()
    def ident(s): return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink
    need(ident(before) == ident(opened) == ident(after), "File changed during stream hash: " + str(path))
    return h.hexdigest()


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def json_read(path):
    def unique(items):
        result = {}
        for k, v in items:
            need(k not in result, "Duplicate JSON key: " + k); result[k] = v
        return result
    return json.loads(ordinary(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + v)))


def write(path, data):
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False); f.write("\n")


def inventory(folder):
    folder = ordinary(folder); result = {}
    for p in sorted(folder.rglob("*")):
        ordinary(p)
        if p.is_file():
            need(p.stat().st_size <= 256*1024**2, "Evidence file exceeds 256 MiB bound")
            result[p.relative_to(folder).as_posix()] = sha(p)
            need(len(result) <= 512, "Evidence file count exceeds 512")
    return result


def number(token):
    need(len(token) <= 128 and NUMBER.fullmatch(token), "Unsupported ASCII decimal")
    value = Decimal(token.decode("ascii").replace("d", "E").replace("D", "E"))
    need(value.is_finite() and math.isfinite(float(value)), "Nonfinite number")
    return value


def blocks(raw):
    need(len(raw) <= 2*1024**2 and not raw.startswith(b"\xef\xbb\xbf"), "Bounded no-BOM native input required")
    raw.decode("utf-8")
    result = []; offset = 0; current = None
    for line in raw.splitlines(keepends=True):
        code = line.split(b"#", 1)[0].strip()
        if code and not code.startswith(b";"):
            if code.startswith(b"["):
                m = re.fullmatch(rb"\[([^\[\]]+)\]", code); need(m, "Malformed block header")
                if current is not None: current["end"] = offset
                current = {"name": m[1].decode().strip().casefold(), "start": offset, "end": len(raw), "fields": [], "rows": []}
                result.append(current)
            else:
                need(current is not None, "Content before a block")
                if b"=" in code:
                    need(not current["rows"], "Metadata after numeric data")
                    k, v = code.split(b"=", 1)
                    current["fields"].append({"key": k.decode().strip().casefold(), "value": v.decode().strip(),
                                              "start": offset, "end": offset+len(line)})
                else:
                    body = line.split(b"#", 1)[0]
                    tokens = list(re.finditer(rb"\S+", body))
                    current["rows"].append({"tokens": [m[0] for m in tokens],
                                            "spans": [[offset+m.start(), offset+m.end()] for m in tokens],
                                            "start": offset, "end": offset+len(line)})
        offset += len(line)
    need(result, "No blocks")
    for b in result: b["raw"] = raw[b["start"]:b["end"]]
    return result


def values(block, key):
    return [f["value"] for f in block["fields"] if f["key"] == key]


def one(block, key):
    v = values(block, key); need(len(v) == 1, "Missing/duplicate " + key); return v[0]


def field_map(raw):
    result = {}
    for b in blocks(raw):
        need(not b["rows"], "Unexpected table in MDU/EXT")
        for f in b["fields"]:
            address = b["name"] + "/" + f["key"]
            need(address not in result, "Duplicate MDU setting: " + address); result[address] = f["value"]
    return result


def local(root, value):
    win = PureWindowsPath(value)
    need(value and not win.drive and not win.root and not any(c in value for c in ';:"*?<>|'), "Nonportable/list reference")
    parts = value.replace("\\", "/").split("/")
    need(all(p and p not in {".", ".."} and not p.endswith((" ", ".")) for p in parts), "Aliased/traversing reference")
    path = ordinary(root.joinpath(*parts)); need(path.is_relative_to(root), "Escaping input reference"); return path


def pli(raw):
    codes = [r.split(b"#", 1)[0].strip() for r in raw.splitlines()]
    codes = [r for r in codes if r and not r.startswith(b";")]
    need(len(codes) >= 4, "Truncated PLI")
    label = codes[0].decode(); dims = codes[1].split()
    need(len(dims) == 2 and all(re.fullmatch(rb"[0-9]+", t) for t in dims), "PLI shape")
    n, c = map(int, dims); need(n == 2 and c == 2 and len(codes) == n+2, "Expected one two-point XY boundary")
    xy = []
    for line in codes[2:]:
        t = line.split(); need(len(t) == 2, "PLI XY columns"); xy.append([str(number(x)) for x in t])
    need(xy[0] != xy[1], "Degenerate boundary")
    return label, [label+"_0001", label+"_0002"], xy


def signals(raw):
    parsed = blocks(raw); need(parsed[0]["name"] == "general", "BC General missing")
    need(one(parsed[0], "filetype").casefold() == "boundconds", "BC file type")
    result = {}; seen = set()
    allowed = {"name", "function", "time-interpolation", "quantity", "unit", "factor", "offset"}
    for b in parsed[1:]:
        need(b["name"] == "forcing", "Unknown BC block cannot be swallowed")
        name = one(b, "name"); need(name.casefold() not in seen, "Duplicate/case-aliased support")
        seen.add(name.casefold()); need(set(f["key"] for f in b["fields"]) <= allowed, "Unknown BC field")
        need(one(b, "function").casefold() == "timeseries" and one(b, "time-interpolation").casefold() == "linear", "Nonlinear/non-TS forcing")
        need(values(b, "quantity") == ["time", "waterlevelbnd"], "Ordered quantities differ")
        need(values(b, "unit") == [EPOCH, "m"], "Bound units/origin differ")
        quantity = 0; coeff = {}; coeff_fields = []
        for f in b["fields"]:
            if f["key"] == "quantity": quantity += 1
            if f["key"] in {"factor", "offset"}:
                need(f["key"] not in coeff, "Repeated coefficient")
                coeff[f["key"]] = (number(f["value"].encode()), quantity)
                coeff_fields.append(f)
        factor = coeff.get("factor", (Decimal(1), 0)); offset = coeff.get("offset", (Decimal(0), 0))
        effective_factor = factor[0] if factor[1] == 0 else Decimal(1)
        effective_offset = offset[0] if offset[1] == 0 else Decimal(0)
        times = []; levels = []; effects = []
        for row in b["rows"]:
            need(len(row["tokens"]) == 2, "Expected exactly time/value")
            t, v = [number(x) for x in row["tokens"]]
            need(not times or t > times[-1], "Nonincreasing source times")
            times.append(t); levels.append(v)
            with localcontext() as ctx:
                ctx.prec = 128; effects.append(v*effective_factor+effective_offset)
        need(times == list(map(Decimal, TIMES)), "Actual source knots/coverage differ")
        result[name] = {"block": b, "coefficient_fields": coeff_fields, "declared": coeff,
                        "applied_factor": effective_factor, "applied_offset": effective_offset,
                        "time": times, "raw": levels, "effective": effects}
    need(set(result) == set(LEVELS), "Every one of four active supports required, no unknown signal")
    return result


def strip_spans(raw, spans):
    result = []; at = 0
    for start, end in sorted(spans):
        need(at <= start <= end <= len(raw), "Overlapping raw oracle spans")
        result += [raw[at:start], b"<permitted>"]; at = end
    return b"".join(result)+raw[at:]


def normalized_block(s, manual=False):
    b = s["block"]; spans = [(f["start"]-b["start"], f["end"]-b["start"]) for f in s["coefficient_fields"]]
    # Coefficient omission/movement is permitted; all remaining bytes exact.
    raw = b["raw"]
    if manual:
        spans += [(r["spans"][1][0]-b["start"], r["spans"][1][1]-b["start"]) for r in b["rows"]]
    pieces = []; at = 0
    coefficient_spans = {(f["start"]-b["start"], f["end"]-b["start"]) for f in s["coefficient_fields"]}
    for start, end in sorted(spans):
        pieces += [raw[at:start], b"" if (start,end) in coefficient_spans else b"<value>"]; at = end
    return b"".join(pieces)+raw[at:]


def static_graph(folder):
    m = field_map((folder/"model.mdu").read_bytes())
    required = {"general/pathsrelativetoparent":"0", "geometry/netfile":"mesh_net.nc", "geometry/kmx":"0",
                "time/refdate":"20260101", "time/tzone":"0", "time/tunit":"S", "time/tstart":"0", "time/tstop":"120",
                "time/startdatetime":"20260101000000", "time/stopdatetime":"20260101000200",
                "external forcing/extforcefilenew":"boundaries.ext", "output/obsfile":"observations.xyn",
                "output/outputdir":"output", "output/hisfile":"model_his.nc", "output/mapfile":"model_map.nc",
                "output/hisinterval":"10", "output/mapinterval":"10", "output/rstinterval":"120"}
    need(all(m.get(k) == v for k,v in required.items()), "Static clock/2D/output/graph profile differs")
    allowed_refs = {"geometry/netfile", "external forcing/extforcefilenew", "output/obsfile"}
    noninputs = {"general/fileversion", "general/filetype", "output/hisfile", "output/mapfile"}
    for k,v in m.items():
        if v and "file" in k.rsplit("/",1)[-1]: need(k in allowed_refs | noninputs, "Unknown nonempty MDU file dependency: "+k)
    ext = blocks((folder/"boundaries.ext").read_bytes()); need(len(ext) == 3 and ext[0]["name"] == "general", "EXT inventory")
    need(one(ext[0], "filetype").casefold() == "extforce", "EXT format")
    boundary = []
    for b in ext[1:]:
        need(b["name"] == "boundary" and not b["rows"], "Unknown EXT container/block")
        need({f["key"] for f in b["fields"]} == {"quantity", "locationfile", "forcingfile"}, "Unknown EXT field/coefficient")
        need(one(b,"quantity") == "waterlevelbnd" and one(b,"forcingfile") == "boundaries.bc", "Wrong EXT quantity/signal")
        p = local(folder, one(b,"locationfile")); label, supports, xy = pli(p.read_bytes())
        boundary.append({"label":label,"supports":supports,"xy":xy,"PLI":p.name,"BC":"boundaries.bc"})
    need({b["label"] for b in boundary} == {"east","west"}, "Exact east/west lines required")
    need(set(s for b in boundary for s in b["supports"]) == set(LEVELS), "Support identities from actual PLI disagree")
    with nc.Dataset(folder/"mesh_net.nc") as ds:
        need("mesh2d_nFaces" in ds.dimensions and len(ds.dimensions["mesh2d_nFaces"]) == 48, "Expected actual 48-face input mesh")
    return {"boundaries":boundary,"clock":PLAN["clocks"],"physical_input_files":sorted(NATIVE_INPUTS)}


def check_inputs(root):
    root = ordinary(root)
    need({p.name for p in root.iterdir() if p.is_dir()} == set(CASES), "Exact eight case directories required")
    hashes = {}; parsed = {}; graph = None
    for case in CASES:
        folder = ordinary(root/case); inv = inventory(folder)
        need(set(inv) == FILES, "Nine-file authored inventory differs: "+case); hashes[case] = inv
        current = static_graph(folder)
        if graph is None: graph = current
        need(current == graph, "Line/support geometry differs: "+case)
        parsed[case] = signals((folder/"boundaries.bc").read_bytes())
    default = parsed["default"]; default_raw = (root/"default/boundaries.bc").read_bytes()
    east = {"east_0001", "east_0002"}
    skeleton = strip_spans(default_raw, [(default[s]["block"]["start"], default[s]["block"]["end"]) for s in east])
    report = []
    for case in CASES:
        need(all(hashes[case][p] == hashes["default"][p] for p in FILES-{"boundaries.bc"}), "Non-BC input changed: "+case)
        raw = (root/case/"boundaries.bc").read_bytes(); sig = parsed[case]
        need(strip_spans(raw,[(sig[s]["block"]["start"],sig[s]["block"]["end"]) for s in east]) == skeleton,
             "Unselected BC/preamble bytes changed: "+case)
        support_report = []
        for name,s in sig.items():
            target = name in east; manual = target and case.endswith("_manual")
            f = Decimal(2) if target and "factor2" in case else Decimal(1)
            o = Decimal(".125") if target and "offset0125" in case else Decimal(0)
            baseline = list(map(Decimal, LEVELS[name])); physical = [v*f+o for v in baseline]
            expected_raw = physical if manual else baseline
            need(s["raw"] == expected_raw, "Wrong actual raw knots: "+case+"/"+name)
            late = target and case.endswith("_late_header")
            implicit = target and case == "east_implicit_defaults"
            expected_f, expected_o = (Decimal(1),Decimal(0)) if manual or late else (f,o)
            need((s["applied_factor"],s["applied_offset"]) == (expected_f,expected_o), "Wrong applied header semantics: "+case+"/"+name)
            if implicit: need(not s["declared"], "Implicit east must omit both coefficients")
            else:
                need(set(s["declared"]) == {"factor","offset"}, "Explicit coefficient pair required")
                declared_f, declared_o = (Decimal(1),Decimal(0)) if manual else (f,o)
                need((s["declared"]["factor"][0],s["declared"]["offset"][0]) == (declared_f,declared_o), "Wrong coefficient declaration")
                need(all(q == (2 if late else 0) for value,q in s["declared"].values()), "Header placement differs from declared FM control")
            expected_effect = baseline if late else physical
            need(s["effective"] == expected_effect, "Effective signal mismatch: "+case+"/"+name)
            if target:
                need(normalized_block(s,manual) == normalized_block(default[name],manual), "Unapproved selected metadata/comments/time-cell changes")
            else: need(s["block"]["raw"] == default[name]["block"]["raw"], "Opposite-line original BC block changed")
            support_report.append({"support":name,"time_unit":EPOCH,"value_unit":"m","raw_values":[str(v) for v in s["raw"]],
                                   "effective_values":[str(v) for v in s["effective"]],"applied_factor":str(s["applied_factor"]),
                                   "applied_offset_m":str(s["applied_offset"]),"block_sha256":hashlib.sha256(s["block"]["raw"]).hexdigest()})
        report.append({"case_id":case,"supports":support_report,"all_non_BC_files_exact":True,"west_raw_blocks_exact":True})
    for a,b in PLAN["pairs_exact"]:
        need(all(parsed[a][s]["effective"] == parsed[b][s]["effective"] for s in LEVELS), "Manual/noeffect effective-pair mismatch")
    return {"root":str(root),"hashes":hashes,"graph":graph,"cases":report}


def normalize(value):
    if isinstance(value, np.ndarray):
        return {"dtype":str(value.dtype),"shape":list(value.shape),"values":normalize(value.tolist())}
    if isinstance(value, np.generic): return normalize(value.item())
    if isinstance(value, bytes): return {"bytes_hex":value.hex()}
    if isinstance(value, float) and not math.isfinite(value): return {"nonfinite":str(value)}
    if isinstance(value, (list,tuple)): return [normalize(x) for x in value]
    return value


def attributes(obj):
    return [{"name":n,"value":normalize(obj.getncattr(n))} for n in sorted(obj.ncattrs())]


def dimensions(ds):
    return [{"name":n,"size":len(v),"unlimited":v.isunlimited()} for n,v in ds.dimensions.items()]


def variable_data(v, key=Ellipsis):
    v.set_auto_chartostring(False)
    v.set_auto_maskandscale(False); storage = np.asarray(v[key])
    v.set_auto_maskandscale(True); decoded = np.ma.asarray(v[key])
    data, mask = np.asarray(decoded.data), np.ma.getmaskarray(decoded)
    need(data.dtype.kind in "biufcS", "Unsupported native variable data type: "+v.name)
    if data.dtype.kind in "fc": need(np.isfinite(data[~mask]).all(), "Unmasked nonfinite native field: "+v.name)
    return storage, data, mask


def slices(v):
    if not v.shape:
        yield Ellipsis; return
    stride = max(1, int(np.prod(v.shape[1:],dtype=np.int64))) * max(1,v.dtype.itemsize)
    width = max(1, (1024**2)//stride)
    for start in range(0,v.shape[0],width):
        yield (slice(start,min(start+width,v.shape[0])), *[slice(None)]*(v.ndim-1))


def variable_summary(v):
    rawhash, valuehash, maskhash = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    masked = 0; count = 0
    for key in slices(v):
        storage, data, mask = variable_data(v,key)
        rawhash.update(storage.tobytes()); valuehash.update(data[~mask].tobytes()); maskhash.update(mask.tobytes())
        masked += int(mask.sum()); count += int(data.size)
    return {"name":v.name,"dimensions":list(v.dimensions),"shape":list(v.shape),"dtype":str(v.dtype),
            "attributes":attributes(v),"elements":count,"masked":masked,"storage_sha256":rawhash.hexdigest(),
            "valid_values_sha256":valuehash.hexdigest(),"mask_sha256":maskhash.hexdigest()}


def clock(ds, expected):
    need("time" in ds.variables, "Missing native CF time")
    v = ds["time"]; _, data, mask = variable_data(v)
    need(v.dimensions == ("time",) and data.ndim == 1 and not mask.any(), "Malformed/masked CF clock")
    units = getattr(v,"units",None); calendar = getattr(v,"calendar","standard")
    need(units == EPOCH and calendar == "standard", "Actual clock origin/unit/calendar differs from frozen profile")
    seconds = np.asarray(nc.date2num(nc.num2date(data,units,calendar=calendar),EPOCH,calendar=calendar),dtype="f8")
    need(np.array_equal(seconds,np.asarray(expected,dtype="f8")), "Truncated/reversed/off-schedule actual native clock")
    need(len(seconds) == 1 or np.all(np.diff(seconds)>0), "Nonincreasing native clock")
    bound = getattr(v,"bounds",None)
    for name, other in ds.variables.items():
        need(name in {"time",bound} or not (getattr(other,"axis",None)=="T" or
             getattr(other,"standard_name",None)=="time" and other.dimensions==(name,)), "Unlisted alternate time coordinate")
    result = {"units":units,"calendar":calendar,"seconds":seconds.tolist()}
    if bound:
        need(bound in ds.variables, "Clock bounds reference missing")
        b = ds[bound]; _, data, mask = variable_data(b)
        need(b.dimensions[0] == "time" and data.shape == (len(seconds),2) and not mask.any(), "Clock bounds shape/mask")
        need(getattr(b,"units",units)==units and getattr(b,"calendar",calendar)==calendar, "Bounds clock metadata")
        need(np.all(data[:,0]<=seconds) and np.all(seconds<=data[:,1]), "Time outside bounds")
        result["bounds_seconds"] = data.tolist()
    return result


def expected_clock(role):
    return [0] if role == "restart_initial" else [120] if role == "restart_final" else list(range(0,121,10))


def scan_dataset(path, role):
    with nc.Dataset(ordinary(path)) as ds:
        need(not ds.groups, "Unlisted NetCDF groups")
        return {"file_sha256":sha(path),"clock":clock(ds,expected_clock(role)),"dimensions":dimensions(ds),
                "global_attributes":attributes(ds),"variables":[variable_summary(v) for v in ds.variables.values()]}


def global_metadata(a,b):
    x = {n:a.getncattr(n) for n in a.ncattrs()}; y = {n:b.getncattr(n) for n in b.ncattrs()}
    need(set(x)==set(y), "Global metadata inventory changed")
    differences = []
    for name in x:
        if normalize(x[name]) == normalize(y[name]): continue
        need(name in VOLATILE, "Unlisted global metadata divergence: "+name)
        for value in (x[name],y[name]):
            need(isinstance(value,str), "Nontext creation metadata")
            if name == "uuid": uuid.UUID(value)
            elif name == "history":
                m = re.fullmatch(r"Created on (.+), D-Flow FM",value)
                need(m is not None,"Unlisted history provenance content"); datetime.fromisoformat(m[1])
            else: datetime.fromisoformat(value)
        differences.append({"name":name,"before":x[name],"after":y[name]})
    return differences


def exact_variable(a,b):
    need(a.dimensions==b.dimensions and a.shape==b.shape and a.dtype==b.dtype, "Native dimensions/type differ: "+a.name)
    need(attributes(a)==attributes(b), "Native variable attributes/units differ: "+a.name)
    for key in slices(a):
        ar,av,am = variable_data(a,key); br,bv,bm = variable_data(b,key)
        need(np.array_equal(am,bm), "Native CF mask differs: "+a.name)
        need(ar.tobytes()==br.tobytes(), "Native raw storage differs: "+a.name)
        need(np.array_equal(av[~am],bv[~bm]), "Native decoded values differ: "+a.name)


def compare_dataset(a,b,role):
    with nc.Dataset(ordinary(a)) as x, nc.Dataset(ordinary(b)) as y:
        need(not x.groups and not y.groups, "NetCDF groups unsupported")
        need(dimensions(x)==dimensions(y), "Native dimension/unlimited inventory differs")
        need(list(x.variables)==list(y.variables), "Native variable inventory/order differs")
        ca,cb = clock(x,expected_clock(role)),clock(y,expected_clock(role))
        need(ca==cb,"Actual clocks differ")
        reports = []
        for name in x.variables:
            exact_variable(x[name],y[name]); reports.append(variable_summary(y[name]))
        return {"state":"passed","role":role,"clock":cb,"every_variable_exact":len(reports),"variables":reports,
                "permitted_creation_metadata_differences":global_metadata(x,y)}


def load_run(run, case, frozen):
    run = ordinary(run); manifest_path = run/"manifest.json"; m = json_read(manifest_path)
    need(m.get("schema_version")==3 and m.get("state")=="completed" and m.get("returncode")==0, "Run not completed manifest3/native0: "+case)
    need(m.get("route")=="direct" and m.get("executable_sha256")==frozen["engine_sha256"], "Unexpected route/engine: "+case)
    need(ordinary(m["run_directory"])==run and ordinary(m["working_directory"])==run/"model", "Manifest run/working path mismatch")
    need(ordinary(m["staged_mdu"])==run/"model/model.mdu", "Manifest MDU mismatch")
    cmd = m.get("argv")
    need(isinstance(cmd,list) and len(cmd)==3 and cmd[1:]==["--autostartstop","model.mdu"], "Unrecognized engine argv")
    need(m.get("environment_overrides",{}).get("OMP_NUM_THREADS")=="1" and
         m.get("environment_overrides",{}).get("MKL_NUM_THREADS")=="1", "Unpinned thread environment")
    need(m.get("runtime_versions",{}).get("fm")=="1.2.184.Unknown", "Unverified native engine version")
    own = m.get("ownership",{}); terminal = own.get("normal_exit",{})
    need(own.get("assigned_before_resume") is True and terminal.get("root_exit_confirmed") is True and
         terminal.get("job_empty") is True and terminal.get("all_owned_members_exit_confirmed") is True and
         terminal.get("unobserved_member_count")==0 and terminal.get("termination_attempted") is False,
         "Missing recorded original-job/retained-member terminal proof")
    inputs = m.get("inputs"); need(isinstance(inputs,list),"Manifest input records missing")
    indexed = {}
    for record in inputs:
        name = record["relative_path"].replace("\\","/")
        need(name not in indexed,"Repeated manifest input"); indexed[name] = record
    need(set(indexed)==NATIVE_INPUTS, "Incomplete/unlisted manifest native input graph")
    for name,record in indexed.items():
        source = Path(frozen["inputs"]["root"])/case/name
        need(ordinary(record["path"])==ordinary(source), "Manifest input source belongs to another case")
        need(record["sha256"]==frozen["inputs"]["hashes"][case][name]==sha(run/"model"/name), "Stale/reversed staged input: "+case+"/"+name)
        need(record["bytes"]==(run/"model"/name).stat().st_size,"Manifest input byte count")
    outputs = {}; output_records = {}
    for record in m.get("outputs",[]):
        name = record["path"].replace("\\","/"); need(name not in output_records,"Duplicate manifest output")
        output_records[name] = record
    folder = ordinary(run/"model/output")
    need({p.name for p in folder.glob("*.nc")}==set(OUTPUTS.values()), "Missing/unlisted native NetCDF artifact")
    for role,name in OUTPUTS.items():
        path = folder/name; relative = "model/output/"+name
        need(relative in output_records,"Native artifact not recorded in manifest")
        need(output_records[relative]["sha256"]==sha(path) and output_records[relative]["bytes"]==path.stat().st_size,
             "Stale native output/manifest: "+name)
        outputs[role] = {"path":str(path),**scan_dataset(path,role)}
    logs = []
    for key in ("stdout","stderr"):
        path = ordinary(m[key]); need(path.is_relative_to(run), "Log outside owned run")
        logs.append({"kind":key,"path":str(path),"sha256":sha(path)})
    return {"case_id":case,"run":str(run),"manifest_sha256":sha(manifest_path),"command":cmd,
            "engine_sha256":m["executable_sha256"],"runtime_versions":m["runtime_versions"],
            "ownership":"recorded original-job and member terminal proof checked; no new OS queries",
            "logs":logs,"outputs":outputs}


def station_names(v):
    _,a,mask = variable_data(v)
    need(a.ndim==2 and a.dtype==np.dtype("S1"), "Fixed-width station IDs expected")
    result = []
    for row,m in zip(a,mask):
        end = int(np.flatnonzero(m)[0]) if m.any() else len(row)
        need(not m.any() or m[end:].all(), "Interior masked station ID")
        raw = b"".join(row[:end]).rstrip(b" \0"); need(raw and b"\0" not in raw,"Malformed station ID")
        result.append(raw.decode("utf-8"))
    need(len(set(result))==len(result),"Duplicate native station ID"); return result


def response(a,b,role):
    var = "waterlevel" if role=="history" else "mesh2d_s1" if role=="map" else "s1"
    with nc.Dataset(a) as x,nc.Dataset(b) as y:
        need(dimensions(x)==dimensions(y) and list(x.variables)==list(y.variables),"Response schema/topology changed")
        need(clock(x,expected_clock(role))==clock(y,expected_clock(role)),"Response clocks differ")
        # Native static geometry/topology and every variable's metadata must stay
        # consistent even though the physical state is expected to change.
        for name,v in x.variables.items():
            w = y[name]
            need(v.dimensions==w.dimensions and v.shape==w.shape and v.dtype==w.dtype and attributes(v)==attributes(w),
                 "Response field metadata/units changed: "+name)
            if "time" not in v.dimensions: exact_variable(v,w)
        need(var in x.variables and getattr(x[var],"units",None)=="m", "Response physical water-level units missing")
        _, av, am = variable_data(x[var]); _, bv, bm = variable_data(y[var])
        need(av.shape==bv.shape and av.ndim==2,"Response variable dimensions")
        if role=="history":
            ids = station_names(x["station_name"]); need(ids==station_names(y["station_name"]),"Response station identities")
            need(set(ids)=={"near_east","near_west"},"Expected two named native stations")
            i = ids.index("near_east"); av,bv,am,bm = [a[:,i:i+1] for a in (av,bv,am,bm)]
        elif role=="map": need(x[var].dimensions==("time","mesh2d_nFaces") and av.shape[1]==48,"Expected all48 native map faces")
        else: need(x[var].dimensions==("time","nFlowElem") and av.shape[1]>=48,"Native restart element schema")
        valid = ~am & ~bm & np.isfinite(av) & np.isfinite(bv)
        delta = np.abs(bv.astype("f8")-av.astype("f8")); threshold = PLAN["response"]["minimum_abs_delta_m"]
        times = expected_clock(role); metrics = []; qualifying = 0
        for i,t in enumerate(times):
            active = valid[i]; detected = active & (delta[i]>=threshold)
            count = int(detected.sum()); required = 1 if role=="history" else 2
            if t>0 and count>=required: qualifying += 1
            examples = [{"native_index":int(j),"baseline_m":float(av[i,j]),"changed_m":float(bv[i,j]),
                         "abs_delta_m":float(delta[i,j])} for j in np.flatnonzero(detected)[:4]]
            metrics.append({"time_seconds":t,"finite_common_samples":int(active.sum()),"detected_samples":count,
                            "maximum_abs_delta_m":float(delta[i,active].max(initial=0)),"examples":examples})
        need(qualifying >= (1 if role=="restart_final" else 2),"No sufficiently repeated measurable native response: "+role)
        return {"variable":var,"unit":"m","minimum_abs_delta_m":threshold,"qualifying_postinitial_times":qualifying,
                "per_time":metrics,"west_output_invariance_required":False}
