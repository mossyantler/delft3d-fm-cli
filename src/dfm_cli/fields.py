"""E014: inspect actual MDU occurrences and preview bounded known 2D scalar edits.

Additive integration, owned by the coordinator::

    fields.register(models)  # the existing model action subparser collection
    # Before ordinary model dispatch:
    if args.group == 'model' and args.action in fields.ACTIONS:
        return fields.execute(args)

Public commands: model fields MDU [--section NAME] [--key NAME];
model field-set MDU SECTION/KEY VALUE --unit UNIT
[--apply --expect-sha256 INPUT_SHA256]. The new hash is the complete inspected
input graph fingerprint, not the MDU-only before_sha256. The original model.set
contract is unchanged. Inspection has no netCDF dependency. Bounded editing
requires the run extra and a supplied projected 2D UGRID mesh with explicit bed
and vertical datum, explicit BedlevType=3, and no incompatible declared
Conveyance2D (only 1, or undeclared as in the observed M3 input). Only existing
value tokens change; no default insertion.
Editing inherits the reference inspector's refusal of any repeated MDU address;
inspection still reports every occurrence without choosing a value.
editor_available describes a static bounded editor; edit_eligibility reports
definite MDU blockers or requires_preview without opening referenced files.
Inspection keeps editable=False until a supplied candidate passes the complete
field-set graph/mesh/unit checks; known_verified_case stays historical evidence.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import difflib
import hashlib
import json
from pathlib import Path
import re

from .common import DfmError, atomic_bytes, inside, sha
from .model import Mdu, SETTINGS, inspect_mdu
from .fields_evidence import EDITABLE, evidence, registry
from .fields_eligibility import TextEligibility

ACTIONS = ("fields", "field-set")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def register(models):
    commands = {}
    view = models.add_parser("fields", help="List each actual MDU key/line/occurrence with static and observed evidence")
    view.add_argument("mdu", type=Path)
    view.add_argument("--section", help="Exact section name, case-insensitive")
    view.add_argument("--key", help="Exact key name, case-insensitive; unknown keys remain visible")
    commands["fields"] = view
    edit = models.add_parser("field-set", help="Preview/apply one existing bounded 2D scalar; explicit unit and graph hash required")
    edit.add_argument("mdu", type=Path)
    edit.add_argument("setting", help="geometry/waterlevini, physics/uniffrictcoef or time/dtmax")
    edit.add_argument("value")
    edit.add_argument("--unit", required=True, help="m; 's m-1/3' for Manning n; or s for DtMax")
    edit.add_argument("--apply", action="store_true")
    edit.add_argument("--expect-sha256", help="input_sha256 from this field preview, covering the entire reference graph")
    commands["field-set"] = edit
    return commands


def inspect(path, section=None, key=None):
    mdu, counts, records = Mdu(Path(path)), defaultdict(int), []
    assessment = TextEligibility(mdu, EDITABLE, scalar)
    for entry in mdu.records:
        sec, name = entry.address.split("/", 1)
        counts[entry.address] += 1
        if section is not None and sec != section.casefold(): continue
        if key is not None and name != key.casefold(): continue
        item = {"section": sec, "key": name, "setting": entry.address, "line": entry.line,
                "occurrence": counts[entry.address], "value": entry.value,
                "byte_start": entry.start, "byte_end": entry.end, **evidence(entry.address), **assessment.report(entry.address)}
        if entry.address in SETTINGS:
            item["model_set_preview"] = {"command": "model set", "setting": entry.address,
                                         "apply_hash": "before_sha256", "hash_scope": "MDU bytes"}
        if entry.address == "physics/uniffrictcoef":
            laws = mdu.index.get("physics/uniffricttype", [])
            item["unit_evidence"] = {"unit": "s m-1/3" if len(laws) == 1 and laws[0].value == "1" else None,
                                     "basis": "Manning only when exactly one explicit UnifFrictType=1; otherwise conditional/unknown",
                                     "friction_law": assessment.friction(), "bounded_editor_unit": "s m-1/3"}
        records.append(item)
    return {"mdu": str(mdu.path), "before_sha256": hashlib.sha256(mdu.raw).hexdigest(), "fields": records,
            "field_count": len(records), "actual_mdu_occurrences": len(mdu.records),
            "editable_settings": EDITABLE, "apply_requires": "input_sha256 of a field-set preview",
            "editable_settings_scope": "static_editor_catalog_only; not permission to edit this model",
            "mdu_edit_context": assessment.summary(),
            "registry": {k: v for k, v in registry().items() if k != "records"},
            "limitations": ["Static source and HYDROLIB evidence do not establish installed behavior or GUI ownership",
                            "Unknown keys and duplicate occurrences are preserved and reported; bounded editing refuses any repeated MDU address",
                            "Inspection checks MDU text only; editable stays false until a connected-model field-set preview validates the supplied candidate",
                            "E014-G verifies the recorded bounded 2D fixture; this inspection does not run engine initialization or establish scientific validity"]}


def scalar(value, setting):
    if not isinstance(value, str) or not NUMBER.fullmatch(value) or len(value) > 80:
        raise DfmError("field_scalar", "Expected one bounded finite ASCII decimal token", 4, setting)
    try:
        result = Decimal(value)
        if not result.is_finite() or result.copy_abs() > Decimal("1e6") or result != 0 and result.copy_abs() < Decimal("1e-12"):
            raise InvalidOperation
        return result
    except InvalidOperation as exc:
        raise DfmError("field_scalar", "Scalar is outside supported finite precision/range", 4, setting) from exc


def context(mdu, assessment=None):
    (assessment or TextEligibility(mdu, EDITABLE, scalar)).require_global()
    from .outputs import reader
    nc, np = reader()
    conveyance = mdu.get("geometry/conveyance2d", "")
    report = inspect_mdu(mdu)
    if report["issues"]:
        raise DfmError("field_references", "Resolve unsupported/missing model input references first", 4, report["issues"])
    mesh = inside(mdu.path.parent, mdu.get("geometry/netfile"), root=mdu.path.parent)
    try:
        with nc.Dataset(mesh) as ds:
            topologies = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
            if len(topologies) != 1 or getattr(topologies[0], "topology_dimension", None) != 2:
                raise DfmError("unsupported_field_profile", "Expected one provided 2D UGRID topology", 3)
            topo = topologies[0]
            xy = str(getattr(topo, "node_coordinates", "")).split()
            if len(xy) not in (2, 3) or any(name not in ds.variables or getattr(ds[name], "units", None) != "m" for name in xy[:2]):
                raise DfmError("unsupported_field_profile", "Only explicitly metric projected coordinates are covered", 3)
            if any(getattr(ds[name], "standard_name", "") != "projection_" + axis + "_coordinate" for name, axis in zip(xy, "xy")):
                raise DfmError("unsupported_field_profile", "Projected X/Y coordinate metadata is required", 3)
            zname = xy[2] if len(xy) == 3 else topo.name + "_node_z"
            if zname not in ds.variables:
                raise DfmError("field_bed", "Explicit node elevations are required", 4)
            z = ds[zname]
            if ds[xy[0]].ndim != 1 or len(ds[xy[0]]) < 3 or ds[xy[1]].dimensions != ds[xy[0]].dimensions or z.dimensions != ds[xy[0]].dimensions or getattr(z, "location", "node") != "node":
                raise DfmError("field_bed", "X/Y and bed must share the same explicit node dimension", 4)
            datum = [str(owner.getncattr("vertical_datum")) for owner in (ds, z) if "vertical_datum" in owner.ncattrs()]
            if not datum or any(not d.strip() or d != datum[0] for d in datum):
                raise DfmError("field_datum", "Mesh must declare one consistent vertical datum; it is never guessed", 4)
            values = np.ma.asarray(z[:])
            if getattr(z, "units", None) != "m" or getattr(z, "positive", "up") != "up" or not (getattr(z, "positive", "") == "up" or getattr(z, "standard_name", "") == "altitude") or np.ma.getmaskarray(values).any() or not np.isfinite(values).all() or not values.size:
                raise DfmError("field_bed", "Complete finite node bed elevations in metres positive up are required", 4)
            maximum_bed = Decimal(str(float(values.max())))
    except (OSError, RuntimeError, ValueError, AttributeError) as exc:
        raise DfmError("field_mesh", "Cannot establish the bounded 2D mesh/units/datum context", 3, str(exc)) from exc
    entries = [{"relative_path": Path(f["path"]).relative_to(mdu.path.parent).as_posix(), "sha256": f["sha256"], "bytes": f["bytes"]}
               for f in report["files"]]
    entries.sort(key=lambda f: f["relative_path"])
    for item in entries:
        if sha(mdu.path.parent / item["relative_path"]) != item["sha256"]:
            raise DfmError("stale_preview", "Inputs changed while establishing field context", 4)
    fingerprint = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"input_sha256": fingerprint, "files": entries, "mesh": str(mesh), "vertical_datum": datum[0], "maximum_node_bed_m": str(maximum_bed),
            "bed_mode": {"bedlevtype": 3, "conveyance2d": 1 if conveyance else "undeclared_as_in_M3_fixture",
                         "evidence": "M3 supplied node bed with BedlevType=3; M4 BedlevType=3/Conveyance2D=1; other modes unsupported",
                         "engine_initialization": "not_performed"}}


def edit(path, setting, value, unit, apply=False, expected=None):
    setting = setting.casefold() if isinstance(setting, str) else ""
    if setting not in EDITABLE:
        raise DfmError("unsupported_field_edit", "This field is inspection-only or outside the bounded edit surface", 3, EDITABLE)
    rule = EDITABLE[setting]
    if unit != rule["unit"]:
        raise DfmError("field_unit", "Explicit unit does not match the bounded setting", 4, {"required": rule["unit"], "received": unit})
    mdu = Mdu(Path(path))
    old = mdu.get(setting)  # Reject missing or duplicate keys, never insert.
    scalar(old, setting)
    number = scalar(value, setting)
    if not Decimal(rule["minimum"]) <= number <= Decimal(rule["maximum"]):
        raise DfmError("field_range", "Value is outside the documented bounded interval", 4, rule)
    assessment = TextEligibility(mdu, EDITABLE, scalar)
    assessment.require_setting(setting)
    before = context(mdu, assessment)
    if expected is not None and expected.lower() != before["input_sha256"]:
        raise DfmError("stale_preview", "Input graph differs from the field preview", 4)
    if setting == "geometry/waterlevini" and number <= Decimal(before["maximum_node_bed_m"]):
        raise DfmError("field_initial_wet", "This initial-level edit profile requires a level above every provided bed node", 4)
    if setting == "time/dtmax":
        assessment.require_timestep_candidate(number)
    entry = mdu.index[setting][0]
    changed = mdu.raw[:entry.start] + value.encode("ascii") + mdu.raw[entry.end:]
    if apply:
        if not expected:
            raise DfmError("expected_hash_required", "--apply requires input_sha256 from this field preview", 2)
        after_context = context(Mdu(mdu.path))
        if after_context["input_sha256"] != before["input_sha256"] or mdu.path.read_bytes() != mdu.raw:
            raise DfmError("stale_preview", "Inputs changed during edit validation", 4)
        atomic_bytes(mdu.path, changed)
    current_evidence = evidence(setting)
    current_evidence.update(editor_available=True, editable=True, edit_support="preview_validated",
                            edit_eligibility={"state": "preview_validated", "graph_validation": "passed", "candidate_validation": "passed",
                                              "native_validation": "not_performed_for_this_invocation"})
    return {"path": str(mdu.path), "setting": setting, "before": old, "after": value, "unit": unit, "applied": apply,
            **before, "before_sha256": hashlib.sha256(mdu.raw).hexdigest(), "after_sha256": hashlib.sha256(changed).hexdigest(),
            "line": entry.line, "occurrence": 1, "evidence": current_evidence,
            "diff": "".join(difflib.unified_diff(mdu.raw.decode("utf-8-sig").splitlines(keepends=True), changed.decode("utf-8-sig").splitlines(keepends=True), fromfile="before", tofile="after")),
            "preservation": "Only the selected existing numeric value token changes; all other bytes/files retained",
            "checks": {"bounded_input_profile": "passed", "native_field_isolation": "not_performed", "scientific_validation": "not_performed"}}


def execute(args):
    if args.action == "fields":
        return inspect(args.mdu, getattr(args, "section", None), getattr(args, "key", None))
    if args.action == "field-set":
        return edit(args.mdu, args.setting, args.value, args.unit, args.apply, args.expect_sha256)
    raise DfmError("usage", "Unknown model field action", 2)
