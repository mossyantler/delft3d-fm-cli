"""Lightweight E014 MDU blockers, shared by inspection and bounded editing.

This module never reads references/meshes or imports the run extra. A text-only
pass is requires_preview, not eligibility for an unspecified candidate value.
Duplicate inventory is built once, with bounded per-field summaries.
"""
from decimal import Decimal
from pathlib import PureWindowsPath

from .common import DfmError
from .model import INPUTS, OUTPUT_FILES, clock

FORBIDDEN = ("geometry/crossdeffile", "geometry/crosslocfile", "geometry/structurefile", "geometry/frictfile",
             "geometry/inifieldfile", "geometry/waterlevinifile", "restart/restartfile")


def reason(code, message, setting=None, *, exit_code=3, **details):
    result = {"code": code, "message": message, "exit_code": exit_code}
    if setting is not None:
        result["setting"] = setting
    if details:
        result["details"] = details
    return result


def raise_reason(item):
    raise DfmError(item["code"], item["message"], item["exit_code"], item.get("setting", item.get("details")))


class TextEligibility:
    def __init__(self, mdu, editors, scalar):
        self.mdu, self.editors, self.scalar = mdu, editors, scalar
        self.duplicates = [{"setting": address, "lines": [e.line for e in entries]}
                           for address, entries in mdu.index.items() if len(entries) > 1]
        self.global_reasons, self.cache = [], {}
        if self.duplicates:
            self.global_reasons.append(reason("ambiguous_setting", "Bounded editing refuses every repeated MDU address",
                duplicate_address_count=len(self.duplicates), inventory="mdu_edit_context.duplicate_addresses"))
        for setting in FORBIDDEN:
            if any(e.value for e in mdu.index.get(setting, ())):
                self.global_reasons.append(reason("unsupported_field_profile", "Bounded 2D fields exclude 1D, structures, spatial initial/roughness overrides and restart", setting))
        if self.one("geometry/kmx") != "0":
            self.global_reasons.append(reason("unsupported_field_profile", "Only explicit Kmx=0 is covered", "geometry/kmx"))
        if self.one("geometry/bedlevtype") != "3":
            self.global_reasons.append(reason("unsupported_field_bed_mode", "Bounded E014 edits require explicit BedlevType=3; node elevations do not prove the active bed mode", "geometry/bedlevtype"))
        if self.one("geometry/conveyance2d", "") not in ("", "1"):
            self.global_reasons.append(reason("unsupported_field_bed_mode", "Only explicit Conveyance2D=1 or the undeclared observed M3 setting is covered", "geometry/conveyance2d"))
        if self.one("general/pathsrelativetoparent", "0") not in ("0", "1"):
            self.global_reasons.append(reason("field_references", "Unsupported declared reference path mode", "general/pathsrelativetoparent", exit_code=4))
        if not self.one("geometry/netfile", ""):
            self.global_reasons.append(reason("field_references", "Explicit mesh reference missing; no mesh is opened during inspection", "geometry/netfile", exit_code=4))
        # The existing reference inspector rejects unknown nonempty file keys.
        # Group them once instead of repeating an unbounded list on every row.
        unsupported, unsupported_paths = [], []
        for entry in mdu.records:
            key = entry.address.rsplit("/", 1)[1]
            if entry.value and entry.address in INPUTS:
                path = PureWindowsPath(entry.value)
                if path.drive or path.root:
                    unsupported_paths.append({"setting": entry.address, "line": entry.line})
            if entry.value and entry.address not in INPUTS and (("file" in key and entry.address not in OUTPUT_FILES and
                entry.address not in ("general/fileversion", "general/filetype")) or entry.address in ("trachytopes/trtdef", "trachytopes/trtl")):
                unsupported.append({"setting": entry.address, "line": entry.line})
        self.unsupported_references = unsupported
        self.unsupported_paths = unsupported_paths
        if unsupported_paths:
            self.global_reasons.append(reason("field_references", "Absolute/drive-relative input paths are refused by the existing portable reference inspector", exit_code=4,
                reference_count=len(unsupported_paths), inventory="mdu_edit_context.unsupported_paths"))
        if unsupported:
            self.global_reasons.append(reason("field_references", "Nonempty unsupported MDU references block the existing bounded graph inspector", exit_code=4,
                reference_count=len(unsupported), inventory="mdu_edit_context.unsupported_references"))
        if not self.duplicates:
            try:
                clock(mdu)  # Pure MDU text; identical clock rules to inspect_mdu.
            except DfmError as exc:
                self.global_reasons.append(reason("field_references", "MDU clock is unsupported by the reference inspector", exit_code=4,
                                                  underlying_code=exc.code, underlying_message=str(exc)))

    def one(self, address, default=None):
        entries = self.mdu.index.get(address, ())
        return entries[0].value if len(entries) == 1 else default

    def friction(self):
        entries = self.mdu.index.get("physics/uniffricttype", ())
        value = self.one("physics/uniffricttype")
        names = {"0": "Chezy", "1": "Manning", "2": "White-Colebrook", "3": "White-Colebrook WAQUA style"}
        return {"setting": "physics/uniffricttype", "state": "explicit" if len(entries) == 1 else "missing" if not entries else "ambiguous",
                "value": value, "law": names.get(value, "unknown"),
                "occurrence_count": len(entries),
                "source_occurrences": [{"line": e.line, "value": e.value} for e in entries[:8]],
                "source_occurrences_truncated": len(entries) > 8,
                "full_duplicate_inventory": "mdu_edit_context.duplicate_addresses",
                "basis": "Static HYDROLIB Physics.Comments.uniffricttype and engine prop_set labels; not engine execution"}

    def blockers(self, setting):
        if setting in self.cache:
            return self.cache[setting]
        problems = list(self.global_reasons)
        entries = self.mdu.index.get(setting, ())
        if not entries:
            problems.append(reason("missing_setting", "Bounded editor never inserts a missing key", setting))
        elif len(entries) == 1:
            try:
                self.scalar(entries[0].value, setting)
            except DfmError as exc:
                problems.append(reason(exc.code, str(exc), setting, exit_code=exc.exit_code))
        if setting == "physics/uniffrictcoef" and self.one("physics/uniffricttype") != "1":
            problems.append(reason("field_friction_law", "The bounded coefficient editor requires exactly one explicit UnifFrictType=1 (Manning)",
                                   "physics/uniffricttype", exit_code=4))
        if setting == "time/dtmax":
            numbers = {}
            for address in ("time/dtinit", "time/dtuser"):
                value = self.one(address)
                if value is None:
                    problems.append(reason("missing_setting" if not self.mdu.index.get(address) else "ambiguous_setting", "Require one explicit timestep dependency", address))
                else:
                    try:
                        numbers[address] = self.scalar(value, address)
                    except DfmError as exc:
                        problems.append(reason(exc.code, str(exc), address, exit_code=exc.exit_code))
            if len(numbers) == 2:
                initial, user = numbers["time/dtinit"], numbers["time/dtuser"]
                rule = self.editors[setting]
                if not (0 < initial <= user <= 30 and max(initial, Decimal(rule["minimum"])) <= min(user, Decimal(rule["maximum"]))):
                    problems.append(reason("field_timestep", "No candidate can satisfy explicit 0 < DtInit <= new DtMax <= DtUser <=30 seconds within the editor range", setting, exit_code=4))
        self.cache[setting] = problems
        return problems

    def report(self, setting):
        available = setting in self.editors
        blockers = self.blockers(setting) if available else [reason("unsupported_field_edit", "model field-set does not edit this setting", setting)]
        state = "blocked" if available and blockers else "requires_preview" if available else "unsupported"
        reasons = blockers or [{"code": "preview_required", "message": "MDU text cannot validate connected inputs or an unspecified candidate; request a field-set preview"}]
        pending = ["connected_input_graph_and_reference_safety", "projected_2d_mesh_units_bed_and_datum", "candidate_value_and_unit_constraints", "preview_graph_hash"] if available else []
        # Preserve the Boolean type; text-only inspection never claims that an
        # unspecified candidate has passed the connected-model preview.
        return {"editor_available": available, "editable": False, "edit_support": state,
                "edit_eligibility": {"state": state, "checked_scope": "MDU_text_only", "reasons": reasons,
                    "mdu_blockers": blockers if available else [],
                    "graph_validation": "not_performed", "candidate_validation": "not_performed",
                    "requires_preview_checks": pending,
                    "editable_semantics": "True only after connected graph and supplied candidate pass field-set preview; static editor availability is separate"}}

    def summary(self):
        return {"checked_scope": "MDU_text_only", "graph_validation": "not_performed", "candidate_validation": "not_performed",
                "global_blockers": self.global_reasons, "duplicate_addresses": self.duplicates,
                "unsupported_references": self.unsupported_references,
                "unsupported_paths": self.unsupported_paths,
                "friction_law": self.friction(), "ordering_and_offsets": "original occurrences retained"}

    def require_global(self):
        if self.global_reasons:
            raise_reason(self.global_reasons[0])

    def require_setting(self, setting):
        problems = self.blockers(setting)
        if problems:
            raise_reason(problems[0])

    def require_timestep_candidate(self, number):
        initial = self.scalar(self.mdu.get("time/dtinit"), "time/dtinit")
        user = self.scalar(self.mdu.get("time/dtuser"), "time/dtuser")
        if not 0 < initial <= number <= user <= 30:
            raise DfmError("field_timestep", "Require explicit 0 < DtInit <= DtMax <= DtUser <=30 seconds", 4)
