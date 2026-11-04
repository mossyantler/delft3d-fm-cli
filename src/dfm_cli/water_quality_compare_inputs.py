"""Retained example03 pair provenance. Never follows historical external paths."""
import copy
import hashlib
from pathlib import Path
import re

from .common import DfmError, sha
from .coupling_common import digest, load_json, relative
from . import coupling, water_quality
from .model import parse
from .run_control import read_record
from .water_quality_contract import PIN, INPUT_SET_SHA256, EFFECT_GATE


def reject(suffix, message, details=None):
    raise DfmError("water_quality_compare_"+suffix, message, 6, details)


class Evidence:
    def __init__(self):
        self.files = {}

    def path(self, root, name):
        root = water_quality.plain(root).resolve(strict=True)
        path = water_quality.plain(root / relative(name)).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            reject("path", "Evidence path is not a contained regular file", name)
        return path

    def bind(self, path, expected=None, size=None):
        path = water_quality.plain(path).resolve(strict=True)
        actual_size = path.stat().st_size
        if actual_size > 256*1024**2 or len(self.files) >= 4096 and path not in self.files:
            reject("bound", "Evidence exceeds comparison size/file bound")
        value = sha(path)
        if expected is not None and value != expected or size is not None and actual_size != size:
            reject("stale", "Retained artifact differs from its recorded hash/size", str(path))
        if path in self.files and self.files[path] != value:
            reject("stale", "Evidence changed during comparison", str(path))
        self.files[path] = value
        return value

    def json(self, path):
        if Path(path).stat().st_size > 8*1024**2:
            reject("bound", "JSON evidence exceeds8MiB")
        self.bind(path)
        return load_json(path)[0]

    def finish(self):
        for path, expected in self.files.items():
            self.bind(path, expected)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _inventory(entries, name):
    if not isinstance(entries, list) or not entries or len(entries) > 4096:
        reject("manifest", "Missing/bounded inventory required", name)
    result = {}
    for entry in entries:
        key = relative(entry.get("relative_path", ""))
        if key.casefold() in {item.casefold() for item in result} or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            reject("manifest", "Duplicate/invalid inventory item", name)
        result[key] = entry["sha256"]
    return result


def bundle_info(root, evidence):
    root = water_quality.plain(root).resolve(strict=True)
    checked = water_quality.guard(root)
    receipt = evidence.json(root / "water-quality-provenance.json")
    for item in receipt["files"]:
        evidence.bind(evidence.path(root, item["relative_path"]), item["sha256"])
    plan = checked["physical_plan"]
    if plan["source_commit"] != PIN or plan["source_input_set_sha256"] != INPUT_SET_SHA256 or plan["effect_gate"] != EFFECT_GATE:
        reject("pair", "Only the pinned example03 physical plan is supported")
    rates = plan["changed_parameter"]
    if rates.get("name") != "RcNit" or rates.get("unit") != "1/d" or rates.get("control") != 0 or not 0.1 <= rates.get("positive", -1) <= 2:
        reject("role", "Positive/control RcNit plan is not supported")
    specs, sources = {}, {}
    for role in ("positive", "control"):
        specs[role] = evidence.json(root / ("spec-"+role+".json"))
        if specs[role]["source"]["root"] != "source-"+role or not specs[role]["name"].endswith("_"+role):
            reject("role", "Bundle roles require explicit source/spec bindings")
        source = root / ("source-"+role)
        sources[role] = {}
        for name, original_hash in receipt["source"]["files"].items():
            key = "dflowfm/"+name
            content = evidence.path(source, key).read_bytes()
            sources[role][key] = content
            if name == "dynamo.sub":
                marker = b"\nparameter 'SWVnNit'"
                if content.count(marker) != 1:
                    reject("pair", "Common explicit process branch is missing/ambiguous")
                base = content.split(marker)[0]
                pattern = rb"(?m)^(parameter\s+'RcNit'\s+[^\r\n]*?\bvalue\s+)([+0-9.eEdD-]+)(\s+end-parameter[^\r\n]*)$"
                matches = list(re.finditer(pattern, base))
                if len(matches) != 1:
                    reject("role", "Require exactly one native RcNit parameter")
                match = matches[0]
                original = base[:match.start(2)]+b"1.000e-01"+base[match.end(2):]
                if _hash(original) != original_hash or water_quality.reaction_file(original, rates[role]) != content:
                    reject("role", "Native reaction/branch/parameter differs from the pinned role", role)
            elif _hash(content) != original_hash:
                reject("pair", "Common native source differs from the pinned original", key)
        for name in ("proc_def.dat", "proc_def.def"):
            key = "dflowfm/process_library/"+name
            content = evidence.path(source, key).read_bytes()
            if _hash(content) != receipt["process_library"][name]["sha256"]:
                reject("pair", "Process database differs from bundle provenance", key)
            sources[role][key] = content
        if set(sources[role]) != set(specs[role]["source"]["files"]):
            reject("pair", "Spec input list differs from complete pinned graph")
    left, right = copy.deepcopy(specs["positive"]), copy.deepcopy(specs["control"])
    for value in (left, right):
        value.pop("name"); value["source"].pop("root")
    if left != right or [key for key in sources["positive"] if sources["positive"][key] != sources["control"][key]] != ["dflowfm/dynamo.sub"]:
        reject("pair", "Only RcNit may differ between matched native cases")
    return {"root": root, "receipt": receipt, "plan": plan, "specs": specs, "sources": sources}


def _patch(raw, patches):
    changes = []
    entries = parse(raw)
    for patch in patches:
        if patch["file"] != "dflowfm/f34_dynamo.mdu" or patch["occurrence"] != 1:
            reject("pair", "Unexpected native patch target")
        matches = [entry for entry in entries if entry.address == (patch["section"]+"/"+patch["key"]).casefold()]
        if len(matches) != 1:
            reject("pair", "Ambiguous native MDU patch")
        entry = matches[0]
        changes.append((entry.start, entry.end, patch["value"].encode("ascii")))
    for start, stop, value in sorted(changes, reverse=True):
        raw = raw[:start]+value+raw[stop:]
    return raw


def run_info(root, role, bundle, evidence):
    root = water_quality.plain(root).resolve(strict=True)
    evidence.bind(evidence.path(root, "manifest.json"))
    record = read_record(root)
    if (record["schema_version"] != 3 or record["state"] != "completed" or record.get("returncode") != 0 or
        record.get("route") != "dimr" or record.get("profile_name") != "coupling" or
        record.get("validation", {}).get("engine_initialization") != "passed_native_marker" or
        record.get("diagnostics", {}).get("primary_error") is not None):
        reject("manifest", "Require a completed and verified native example03 run", role)
    ownership = record.get("ownership", {})
    if (ownership.get("method") != "windows_job_object" or ownership.get("assigned_before_resume") is not True or
        ownership.get("kill_on_owner_handle_close") is not True or ownership.get("stdin") != "DEVNULL" or
        ownership.get("final_job_pids") != [] or not ownership.get("native_identity")):
        reject("ownership", "Completed run lacks retained private-Job/exit proof", role)
    model = root / "model"
    guarded = coupling.guard(model)
    spec = bundle["specs"][role]
    clock = record.get("profile", {}).get("clock", {})
    if any(clock.get(key) != value for key, value in spec["clock"].items()):
        reject("manifest", "Manifest profile clock differs from declared input pair", role)
    if record["validation"].get("simulation") != "completed_and_declared_component_observables_verified":
        reject("manifest", "Manifest has no verified component simulation state", role)
    normalized = copy.deepcopy(spec); normalized["source"]["root"] = "."
    original = evidence.path(model, "coupling-source.json")
    if sha(original) != sha(bundle["root"] / ("spec-"+role+".json")) or guarded["spec"] != normalized:
        reject("role", "Run does not bind to the requested positive/control bundle role", role)
    recorded = record.get("coupling", {})
    if recorded.get("prepared_sha256") != guarded["prepared_sha256"] or recorded.get("spec") != guarded["spec"]:
        reject("manifest", "Manifest normalized case/receipt differs from staged inputs", role)
    actual = _inventory(guarded["files"], "staged")
    if _inventory(record["inputs"], "manifest.inputs") != actual or _inventory(recorded["files"], "coupling.files") != actual:
        reject("manifest", "Manifest and retained input inventories differ", role)
    for item in record["inputs"]:
        evidence.bind(evidence.path(model, item["relative_path"]), item["sha256"], item["bytes"])
    native_hashes = {}
    for name, content in bundle["sources"][role].items():
        if name == "dflowfm/f34_dynamo.mdu":
            content = _patch(content, spec["patches"])
        native_hashes[name] = _hash(content)
        if native_hashes[name] != actual[name]:
            reject("pair", "Native input differs from declared source/patch replay", {"role": role, "path": name})
    evidence.bind(evidence.path(model, "dimr_config.xml"), actual["dimr_config.xml"])
    outputs = {}
    for entry in record.get("outputs", []):
        name = relative(entry["path"])
        if name in outputs or name in {"model/"+key for key in actual}:
            reject("manifest", "Duplicate/input-colliding output inventory", name)
        outputs[name] = entry["sha256"]
        evidence.bind(evidence.path(root, name), entry["sha256"], entry["bytes"])
    required = {kind: "model/dflowfm/output/f34_dynamo"+suffix for kind, suffix in
                (("map", "_map.nc"), ("history", "_his.nc"), ("timer_init", "_detailed_timers_init.txt"), ("timer_final", "_detailed_timers.txt"))}
    if any(path not in outputs for path in required.values()):
        reject("missing", "Required raw dataset/timer is absent from native output inventory", role)
    binaries = record["installation"].get("binaries", {})
    selected = {}
    for key in ("bin/dimr.exe", "lib/dimr.dll", "lib/dflowfm.dll"):
        value = binaries.get(key, {}).get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            reject("manifest", "Selected native binary has no recorded fingerprint", key)
        selected[key] = value
    if record.get("executable_sha256") != selected["bin/dimr.exe"] or record.get("argv") != [binaries["bin/dimr.exe"]["path"], "dimr_config.xml"]:
        reject("manifest", "Executable/argv metadata differs from selected native backend")
    components = record["verification"].get("components", [])
    for variable, unit in (("mesh2d_NH4", "g/m3"), ("mesh2d_NO3", "gN/m3"), ("mesh2d_OXY", "gO2/m3"), ("mesh2d_s1", "m")):
        matches = [item for item in components if item.get("variable") == variable]
        if len(matches) != 1 or matches[0].get("state") != "passed" or matches[0].get("unit") != unit or matches[0].get("sha256") != outputs[required["map"]]:
            reject("manifest", "Native verification record is inconsistent with the current raw map", variable)
    return {"root": root, "record": record, "guard": guarded, "native_hashes": native_hashes,
            "binary_hashes": selected, "paths": {key: evidence.path(root, name) for key, name in required.items()},
            "manifest_sha256": sha(root / "manifest.json"), "output_hashes": {key: outputs[name] for key, name in required.items()}}
