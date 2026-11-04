"""Fixed pinned06 offline consumer authoring; no suite execution or research import."""
from datetime import datetime, timedelta
import copy
import hashlib
from pathlib import Path
import re

from .common import DfmError, sha, utc_now
from .coupling_common import digest, encoded, ident, load_json, obj, relative
from .water_quality import plain
from .water_quality_offline import review_offline, uncomment
from .water_quality_offline_binary import inspect_hydro
from .water_quality_offline_contract import (PIN, SOURCE_DIGEST, STEM, REFERENCE, START, UNITS, EFFECT,
                                            PROFILE_GATE, PROFILE_EVIDENCE, effect_policy_matches)
from .water_quality_offline_lifecycle import (CHEMISTRY_PROFILE, LIFECYCLE_PROFILE, PURPOSE,
    SOURCE_INP_SHA256, LIFECYCLE_POLICY, LIFECYCLE_EVIDENCE, receipt_profile, audit_input)

CASE_RECEIPT = "waq-offline-case.json"
CONSUMED = {STEM+"."+suffix for suffix in ("atr", "vol", "poi", "len", "flo", "are", "par", "vdf", "stt")}


def fail(suffix, message, details=None, exit_code=4):
    raise DfmError("waq_offline_"+suffix, message, exit_code, details)


def contained(root, name, *, strict=True):
    root = plain(root).resolve(strict=True)
    path = plain(root / relative(name)).resolve()
    if not path.is_relative_to(root):
        fail("path", "Input/evidence path escapes private root", name)
    if strict and not path.is_file():
        fail("missing_input", "Required contained file is missing", name)
    return path


def file_bytes(path, maximum=32*1024**2):
    path = plain(path).resolve()
    if not path.is_file() or path.stat().st_size > maximum:
        fail("bound", "Expected bounded ordinary input file", str(path))
    return path.read_bytes()


def inventory(root):
    root = plain(root).resolve(strict=True)
    result, total = {}, 0
    for path in sorted(root.rglob("*")):
        plain(path)
        if path.is_file():
            total += path.stat().st_size
            if len(result) >= 128 or total > 64*1024**2:
                fail("bound", "Input graph exceeds128files/64MiB")
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def clock_for(duration, *, profile=CHEMISTRY_PROFILE):
    if profile not in (CHEMISTRY_PROFILE, LIFECYCLE_PROFILE):
        fail("profile", "Unknown offline consumer profile")
    if type(duration) is not int or not 600 <= duration <= 3600 or duration % 300:
        fail("clock", "Duration must be600..3600s divisible by300")
    if profile == LIFECYCLE_PROFILE and duration != 3600:
        fail("clock", "Lifecycle dt1 requires exactly3600s with300s outputs")
    stop = datetime.fromisoformat(START)+timedelta(seconds=duration)
    return {"reference": REFERENCE, "start": START, "stop": stop.isoformat(),
            "start_tick": 45000, "stop_tick": 45000+duration, "duration_seconds": duration,
            "time_step_seconds": 1 if profile == LIFECYCLE_PROFILE else 60,
            "output_interval_seconds": 300, "timezone": "not_encoded_in_source"}


def patch_input(raw, duration, rate, *, profile=CHEMISTRY_PROFILE):
    """Byte-preserving fixed recipe; only timer/rate tokens and common constants."""
    clock = clock_for(duration, profile=profile)
    if profile == LIFECYCLE_PROFILE and hashlib.sha256(raw).hexdigest() != SOURCE_INP_SHA256:
        fail("source", "Lifecycle patch requires the exact pinned original INP bytes")
    if rate not in (0, .8):
        fail("chemistry", "Only declared RcMrtEColi .8/day versus0/day is supported")
    if b"'TcMrtEColi'" in raw or b"'CTMrtEColi'" in raw:
        fail("chemistry", "Common constants must be added once to original pinned input")
    stop = datetime.fromisoformat(clock["stop"]).strftime("%Y/%m/%d-%H:%M:%S").encode("ascii")
    def replace(pattern, replacement):
        nonlocal raw
        raw, count = re.subn(pattern, replacement, raw, flags=re.M)
        if count != 1:
            fail("recipe", "Fixed input token is missing/ambiguous", pattern.decode("ascii"))
    replace(rb"^(\s*)1990/08/15-12:30:00(\s*; stop time[^\r\n]*)$", lambda m: m[1]+stop+m[2])
    step = b"00000001" if profile == LIFECYCLE_PROFILE else b"00000100"
    replace(rb"^(\s*)0001500(\s*; time step[^\r\n]*)$", lambda m: m[1]+step+m[2])
    for label in (b"monitoring", b"map, dump", b"history"):
        pattern = rb"^(\s*1990/08/05-12:30:00\s+)1990/08/15-12:30:00(\s+)\d+(\s*; "+label+rb"\s*)$"
        replace(pattern, lambda m: m[1]+stop+m[2]+b"00000500"+m[3])
    replace(rb"^(\s*)8\.00000e-001(\s*; RcMrtEColi\s*)$", lambda m: m[1]+format(rate, ".8e").encode()+m[2])
    # These constants occur only in block7 of this exact input. All original
    # constants/forcing/initial data and their order remain byte-identical.
    # Rate may have changed, so locate the DATA introducing the named constant.
    replace(rb"^(DATA\r?\n)(\s*[0-9.eE+\-]+\s*; RcMrtEColi\s*)$",
            lambda m: b" 'TcMrtEColi'\n 'CTMrtEColi'\n"+m[1]+m[2])
    replace(rb"^PARAMETERS\s*$", b" 1.07000000e+00 ; explicit common TcMrtEColi\n 2.00000000e+00 ; explicit common CTMrtEColi\nPARAMETERS")
    if profile == LIFECYCLE_PROFILE:
        audit_input(raw)
    return raw


def _closure(root, inp):
    files, visiting = {}, set()
    def visit(name, depth=0):
        if depth > 8 or name in visiting:
            fail("include", "Input INCLUDE cycle/depth exceeded", name)
        visiting.add(name)
        text = file_bytes(contained(root, name), 2*1024**2).decode("utf-8-sig")
        for line_no, line in enumerate(text.splitlines(), 1):
            code = uncomment(line)
            for value in re.findall(r"'([A-Za-z0-9_./\\:\-]+\.[A-Za-z0-9_]+)'", code):
                target = contained(root, value)
                if not target.is_file():
                    fail("missing_input", "Consumed file missing", value)
                files[value] = {"relative_path": value, "sha256": sha(target), "bytes": target.stat().st_size,
                                "from": name, "line": line_no}
            for value in re.findall(r"\bINCLUDE\s+'([^']+)'", code, flags=re.I):
                visit(relative(value), depth+1)
        visiting.remove(name)
    visit(inp)
    if set(files) != CONSUMED:
        fail("graph", "Consumer graph differs from the fixed nine-file input chain", sorted(files))
    return files


def review_graph(hyd, inp, install=None, *, requested_clock=None):
    report = review_offline(hyd, inp, install)
    root = plain(inp).resolve(strict=True).parent
    files = _closure(root, Path(inp).name)
    hydro_start = int((datetime.fromisoformat(report["hyd_clock"]["hydrodynamic-start-time"])-datetime.fromisoformat(REFERENCE)).total_seconds())
    hydro_stop = int((datetime.fromisoformat(report["hyd_clock"]["hydrodynamic-stop-time"])-datetime.fromisoformat(REFERENCE)).total_seconds())
    if report["hyd_clock"]["reference-time"] != REFERENCE or (hydro_start, hydro_stop) != (45000, 90000):
        fail("clock", "HYD reference/range differs from fixed source")
    lo, hi = (requested_clock["start_tick"], requested_clock["stop_tick"]) if requested_clock else (hydro_start, hydro_stop)
    report.update(consumed_graph=files, binary_graph=inspect_hydro(root, lo, hi),
                  preparation_checks="passed_bounded_graph", native_ready=False,
                  units_provenance={"substance_file": "coli_03.sub", "EColi_literal": "(MPN/m3)",
                                    "MrtToEColi": "pinned process items.csv: (1/d); binary has no units field"})
    return report


def _binding(receipt):
    return {key: value for key, value in receipt.items() if key not in ("prepared_sha256", "created_at_utc")}


def prepare(spec, out, process_library, apply=False, expected=None):
    if type(apply) is not bool:
        fail("argument", "apply must be boolean")
    if apply and expected is None:
        fail("expected_hash_required", "Apply requires preview --expect-sha256", exit_code=2)
    spec = plain(spec).resolve(strict=True)
    data, spec_raw = load_json(spec)
    lifecycle = type(data.get("schema_version")) is int and data["schema_version"] == 2
    obj(data, "schema_version name source_root duration_seconds time_step_seconds output_interval_seconds mortality common_parameters timezone" +
        (" profile purpose" if lifecycle else ""), "offline spec")
    if type(data["schema_version"]) is not int or data["schema_version"] not in (1, 2):
        fail("spec", "Use schema_version1 chemistry or explicit schema_version2 lifecycle")
    profile = LIFECYCLE_PROFILE if lifecycle else CHEMISTRY_PROFILE
    if lifecycle and (data["profile"] != LIFECYCLE_PROFILE or data["purpose"] != PURPOSE):
        fail("profile", "Require the explicit lifecycle profile and purpose")
    ident(data["name"])
    clock = clock_for(data["duration_seconds"], profile=profile)
    obj(data["mortality"], "positive control unit", "mortality")
    obj(data["common_parameters"], "TcMrtEColi CTMrtEColi", "common_parameters")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in
           (data["mortality"]["positive"], data["mortality"]["control"], *data["common_parameters"].values())):
        fail("spec", "Physical parameter values must be finite numbers, not boolean flags")
    if (type(data["time_step_seconds"]) is not int or data["time_step_seconds"] != clock["time_step_seconds"] or
        type(data["output_interval_seconds"]) is not int or data["output_interval_seconds"] != 300 or
        data["timezone"] != "not_encoded_in_source" or
        data["mortality"] != {"positive": .8, "control": 0, "unit": "1/d"} or
        data["common_parameters"] != {"TcMrtEColi": 1.07, "CTMrtEColi": 2}):
        fail("spec", "Require the explicit fixed clock, common constants, units and matched rates")
    if not isinstance(data["source_root"], str) or not data["source_root"]:
        fail("source", "Explicit source root required")
    source = plain(spec.parent / data["source_root"]).resolve(strict=True)
    out = plain(out).resolve()
    if out.exists() or out.is_relative_to(source) or source.is_relative_to(out):
        fail("output", "Use a fresh destination separate from source")
    graph = review_graph(source / (STEM+".hyd"), source / (STEM+".inp"), requested_clock=clock)
    originals = inventory(source)
    if len(originals) != 28 or digest(originals) != SOURCE_DIGEST:
        fail("source", "Only the exact28 pinned06 Git blobs are supported; no user model")
    original_bytes = {name: file_bytes(contained(source, name)) for name in originals}
    library = plain(process_library).resolve(strict=True)
    if library.name.casefold() != "proc_def.dat":
        fail("library", "Select proc_def.dat explicitly")
    companion = plain(library.with_suffix(".def")).resolve(strict=True)
    resources = {"proc_def.dat": file_bytes(library), "proc_def.def": file_bytes(companion)}
    if any(len(raw) < 1024 for raw in resources.values()):
        fail("library", "Process definition data/definition pair is incomplete")
    native, file_sets = {}, {}
    for role in ("positive", "control"):
        files = dict(original_bytes)
        files[STEM+".inp"] = patch_input(original_bytes[STEM+".inp"], clock["duration_seconds"], data["mortality"][role], profile=profile)
        files.update({"process_library/"+name: raw for name, raw in resources.items()})
        files["provenance/original.inp"] = original_bytes[STEM+".inp"]
        native[role] = files
        file_sets[role] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
    implementation = {path.name: sha(path) for path in sorted(Path(__file__).parent.glob("water_quality_offline*.py"))}
    pair_sha = digest({"spec_sha256": hashlib.sha256(spec_raw).hexdigest(), "files": file_sets, "implementation": implementation})
    if expected is not None and expected != pair_sha:
        fail("stale_preview", "Preparation fingerprint differs; no destination written")
    policy, evidence = (LIFECYCLE_POLICY, LIFECYCLE_EVIDENCE) if lifecycle else (EFFECT, PROFILE_EVIDENCE)
    effect = {"clock": clock, "parameter": "RcMrtEColi", "rates": data["mortality"],
              "common_parameters": data["common_parameters"], "units": UNITS, "effect": policy,
              "profile": profile, "native_gate": evidence["state"], "profile_evidence": evidence,
              "native_execution": "not_performed", "scientific_validation": "not_performed"}
    result = {"applied": apply, "input_sha256": pair_sha, "directory": str(out),
              "profile": profile,
              "cases": {role: str(out / role) for role in native}, "effect_plan": effect,
              "source_commit": PIN, "source_sha256": SOURCE_DIGEST,
              "checks": {"pinned_source": "passed", "consumed_graph": "passed_nine_files", "binary_hydro": "passed",
                         "staged_recipe": "source_backed; this stage has not been executed",
                         "native_execution": "not_performed"}}
    if lifecycle:
        result["lifecycle_study"] = {"purpose": PURPOSE, "chemistry_comparison": "unsupported_for_dt1",
                                     "timer_audits": {role: audit_input(files[STEM+".inp"]) for role, files in native.items()}}
    if not apply:
        return result
    if inventory(source) != originals or spec.read_bytes() != spec_raw or library.read_bytes() != resources["proc_def.dat"] or companion.read_bytes() != resources["proc_def.def"]:
        fail("stale_preview", "Input changed while authoring")
    payload = {}
    for role, files in native.items():
        receipt = {"schema_version": 2 if lifecycle else 1,
                   "kind": "dfm_waq_offline_lifecycle_case" if lifecycle else "dfm_waq_offline_case",
                   "name": data["name"], "role": role,
                   "pair_sha256": pair_sha, "created_at_utc": utc_now(), "clock": clock,
                   "source_commit": PIN, "source_files": originals, "parameters": {"RcMrtEColi": data["mortality"][role], **data["common_parameters"]},
                   "units": UNITS, "effect": policy, "implementation": implementation,
                   "files": [{"relative_path": name, "sha256": file_sets[role][name], "bytes": len(raw)} for name, raw in sorted(files.items())]}
        if lifecycle:
            receipt.update(profile=profile, purpose=PURPOSE, timer_audit=audit_input(files[STEM+".inp"]))
        receipt["prepared_sha256"] = digest(_binding(receipt))
        payload.update({role+"/"+name: raw for name, raw in files.items()})
        payload[role+"/"+CASE_RECEIPT] = encoded(receipt)
    payload["effect-plan.json"] = encoded(effect)
    payload["waq-offline-bundle.json"] = encoded({"schema_version": 1, "pair_sha256": pair_sha,
        "source_spec_sha256": hashlib.sha256(spec_raw).hexdigest(), "source_commit": PIN,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in payload.items()}})
    out.parent.mkdir(parents=True, exist_ok=True); out.mkdir(exist_ok=False)
    for name, raw in payload.items():
        path = out / name; path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return result


def guard(case):
    case = plain(case).resolve()
    if not case.is_dir():
        fail("missing_case", "Prepared case directory is missing", str(case))
    receipt, _ = load_json(contained(case, CASE_RECEIPT))
    profile = receipt_profile(receipt)
    lifecycle = profile == LIFECYCLE_PROFILE
    obj(receipt, "schema_version kind name role pair_sha256 created_at_utc clock source_commit source_files parameters units effect implementation files prepared_sha256" +
        (" profile purpose timer_audit" if lifecycle else ""), "offline case receipt")
    if digest(_binding(receipt)) != receipt["prepared_sha256"]:
        fail("receipt", "Invalid prepared case binding")
    if receipt["source_commit"] != PIN or not isinstance(receipt["source_files"], dict) or len(receipt["source_files"]) != 28 or digest(receipt["source_files"]) != SOURCE_DIGEST:
        fail("source", "Prepared source is not the complete pinned example06")
    role = receipt["role"]
    if (role not in ("positive", "control") or not isinstance(receipt["parameters"], dict) or
        any(isinstance(value, bool) for value in receipt["parameters"].values()) or
        receipt["parameters"] != {"RcMrtEColi": .8 if role == "positive" else 0, "TcMrtEColi": 1.07, "CTMrtEColi": 2}):
        fail("role", "Physical parameters do not match explicit case role")
    effect_valid = receipt["effect"] == LIFECYCLE_POLICY if lifecycle else effect_policy_matches(receipt["effect"])
    expected_clock = clock_for(receipt["clock"]["duration_seconds"], profile=profile)
    if digest(receipt["clock"]) != digest(expected_clock) or receipt["units"] != UNITS or not effect_valid:
        fail("receipt", "Clock/unit/effect policy differs from supported profile")
    expected = set(receipt["source_files"]) | {"provenance/original.inp", "process_library/proc_def.dat", "process_library/proc_def.def"}
    files, seen = [], set()
    if not isinstance(receipt["files"], list) or len(receipt["files"]) != len(expected):
        fail("receipt", "Incomplete staged graph inventory")
    for item in receipt["files"]:
        obj(item, "relative_path sha256 bytes", "offline files[]")
        name = relative(item["relative_path"])
        if lifecycle and item["relative_path"] != name:
            fail("path", "Lifecycle receipt paths must be canonical portable relative paths", item["relative_path"])
        if lifecycle and (type(item["bytes"]) is not int or item["bytes"] < 0):
            fail("receipt", "Lifecycle file byte counters must be nonnegative JSON integers", name)
        if name.casefold() in seen or name not in expected:
            fail("receipt", "Duplicate/unknown prepared path", name)
        seen.add(name.casefold())
        path = contained(case, name)
        if sha(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            fail("input_changed", "Prepared input hash/size changed", name)
        files.append(dict(item, path=str(path)))
    original = file_bytes(contained(case, "provenance/original.inp"))
    if hashlib.sha256(original).hexdigest() != receipt["source_files"][STEM+".inp"]:
        fail("source", "Retained original input differs from source pin")
    for name, value in receipt["source_files"].items():
        path = contained(case, name)
        if name == STEM+".inp":
            raw = path.read_bytes()
            if raw != patch_input(original, receipt["clock"]["duration_seconds"], receipt["parameters"]["RcMrtEColi"], profile=profile):
                fail("recipe", "Native input differs from the declared bounded recipe")
            if lifecycle and digest(receipt["timer_audit"]) != digest(audit_input(raw)):
                fail("recipe", "Lifecycle timer/counter audit differs from the actual input bytes")
        elif sha(path) != value:
            fail("source", "Common input differs from pinned source", name)
    graph = review_graph(case / (STEM+".hyd"), case / (STEM+".inp"), requested_clock=receipt["clock"])
    if graph["clock_coverage"] != "inside_declared_hydro_range":
        fail("clock", "Prepared consumer clock is not inside hydro coverage")
    files.append({"relative_path": CASE_RECEIPT, "path": str(case / CASE_RECEIPT), "sha256": sha(case / CASE_RECEIPT), "bytes": (case / CASE_RECEIPT).stat().st_size})
    return {"state": "passed_portable_input_guard", "prepared_sha256": receipt["prepared_sha256"],
            "profile": profile,
            "receipt": receipt, "files": files, "graph": graph, "native_validation": "not_performed",
            "native_validation_scope": "this inspection does not execute or promote the selected case",
            "profile_evidence": LIFECYCLE_EVIDENCE if lifecycle else PROFILE_EVIDENCE}
