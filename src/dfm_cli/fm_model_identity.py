"""Narrow FM identity observation/launch gate; not complete native validation.

No defaults or rewriting. Section/key matching follows the existing MDU parser;
Program values remain case-sensitive. No engine, installation or source checkout
is accessed. Explicitly call only for known FM models/components.
"""
import re

from .common import DfmError

CONTRACT = "fm-model-identity-v1"
ACCEPTED = ("Unstruc", "UNSTRUC", "D-Flow FM", "D-Flow Flexible Mesh")
SOURCE = {
    "repository": "Deltares/Delft3D", "commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
    "identity": "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90:818-826",
    "section_selection": "unstruc_model.f90:783-802; parseable General/FileVersion selects General, otherwise model",
    "version_diagnostic_continues": "unstruc_model.f90:807-814 resets istat to DFM_NOERR; numeric major mismatch is not an identity hard gate",
    "case_insensitive_lookup": "src/utils_lgpl/deltares_common/packages/deltares_common/src/properties.f90:1682-1705,1744-1745",
    "version_lookup": "properties.f90:3240-3293 and string_module.f90:1014-1053",
    "installed_engine_source_revision": "unknown; collected source is not asserted to be the installed binary's commit",
}
NATIVE_GATE = "research/experiments/MDU-ID-V-stage-01/installed-alias-observations-slot153.json"
NATIVE_GATE_SHA256 = "5e5f2c592a618e2e489946b79e6ed724d556b0ce582137a4b2f68183147212df"
EVIDENCE = {
    value: {"state": "installed_observed_on_retained_fixture", "source_acknowledged": True,
            "case": case, "reference": NATIVE_GATE, "reference_sha256": NATIVE_GATE_SHA256,
            "scope": "Direct FM, General/FileVersion=1.09, one 48-cell 120-second case; not every namespace/version/route or model",
            "native_execution_by_identity_helper": "not_performed"}
    for value, case in (("D-Flow FM", "canonical"), ("Unstruc", "alias-mixed-Unstruc"),
                        ("UNSTRUC", "alias-uppercase-UNSTRUC"), ("D-Flow Flexible Mesh", "alias-D-Flow-Flexible-Mesh"))
}


def _entries(mdu, address):
    return [{"setting": entry.address, "value": entry.value, "line": entry.line,
             "value_byte_start": entry.start, "value_byte_end": entry.end}
            for entry in mdu.index.get(address, ())]


def contract():
    return {"contract": CONTRACT, "commands": ["model validate", "run start"],
            "accepted_program_values": list(ACCEPTED), "case_sensitive_values": True,
            "section_rule": "Parseable General/FileVersion selects General/Program; an absent or empty version selects model/Program",
            "unresolved_or_duplicate": "Refuse native launch rather than choose a value",
            "inspection": "model inspect and byte-preserving editors do not require a launchable model",
            "scope": "Static FM identity only; format version, native initialization and completion are separate checks",
            "source_basis": SOURCE}


def _version_route(entries):
    if len(entries) > 1:
        return None, {"state": "ambiguous", "comparison_enforced": False}
    if not entries or not entries[0]["value"]:
        return "model", {"state": "absent_or_empty; source_selects_legacy_model", "comparison_enforced": False}
    text = entries[0]["value"]
    # The source reads an integer before '.', then the immediately following
    # decimal digits, ignoring later text. Cover ordinary documented spelling;
    # do not pretend to implement arbitrary Fortran list-directed input syntax.
    match = re.match(r"([+-]?[0-9]+)\.([0-9]+)", text, re.ASCII)
    if match and len(match[1]) <= 11 and len(match[2]) <= 10:
        major, minor = int(match[1]), int(match[2])
        if -(2**31) <= major < 2**31 and minor < 2**31:
            return "general", {"state": "parseable_standard_numeric_prefix", "major": major, "minor": minor,
                               "comparison_enforced": False,
                               "source_major_mismatch_diagnostic": major != 1,
                               "installed_exact_value_observation": ({"value": "9.99", "native_returncode": 1,
                                   "public_exit_code": 5, "completion": "not_established", "reference": NATIVE_GATE,
                                   "scope": "One exact observed version failure; no inferred supported range or identity hard gate"}
                                   if text == "9.99" else None),
                               "scope": "Routing only; no current/maximum version acceptance inferred"}
    return None, {"state": "unresolved_nonstandard_version_routing", "comparison_enforced": False,
                  "scope": "No guessed fallback or proven native rejection for unsupported syntax; review identity lookup explicitly"}


def observe(mdu):
    """Return every identity occurrence without choosing a duplicate winner."""
    occurrences = {key: _entries(mdu, key) for key in (
        "general/program", "model/program", "general/fileversion", "model/mduformatversion", "general/filetype")}
    selected_section, version = _version_route(occurrences["general/fileversion"])
    address = selected_section + "/program" if selected_section else None
    entries = occurrences[address] if address else []
    duplicate = [key for key in ("general/program", "model/program", "general/fileversion", "model/mduformatversion")
                 if len(occurrences[key]) > 1]
    if duplicate:
        state, reason = "ambiguous", "Repeated identity/routing fields are refused; native duplicate winner is not assumed"
    elif selected_section is None:
        state, reason = "unresolved", "Cannot establish the source-informed identity lookup section from this version spelling"
    elif not entries:
        state, reason = "missing", "Required Program is missing in the selected native identity section"
    elif not entries[0]["value"]:
        state, reason = "empty", "Program must be explicitly nonempty"
    elif entries[0]["value"] not in ACCEPTED:
        state, reason = "unaccepted_value", "Program value is case-sensitive and does not match a source-admitted spelling"
    else:
        state, reason = "source_admitted", "Exact source-admitted Program value; no engine initialization performed"
    value = entries[0]["value"] if len(entries) == 1 else None
    admissible = state == "source_admitted"
    remediation = ("Review the copied FM MDU's declared format and Program. For a modern MDU use its explicit parseable "
                   "[General] FileVersion and one Program with an exact accepted spelling. Unversioned legacy lookup uses "
                   "[model] Program. Never add a guessed Program or format version to an existing model automatically.")
    issue = {"code": "fm_model_identity_invalid", "setting": address,
             "message": reason, "state": state, "duplicate_fields": duplicate, "remediation": remediation}
    return {"contract": CONTRACT, "path": str(mdu.path),
            "state": state, "static_launch_eligible": admissible, "lookup_section": selected_section,
            "eligibility_scope": "Program identity gate only; separate version/configuration diagnostics or native refusal remain possible",
            "selected_setting": address, "value": value, "occurrences": occurrences,
            "section_key_case": "insensitive", "program_value_case": "sensitive",
            "version": version, "filetype_is_native_identity_guard": False,
            "accepted_program_values": list(ACCEPTED),
            "alias_evidence": [{"program": spelling, **EVIDENCE[spelling]} for spelling in ACCEPTED],
            "selected_value_evidence": EVIDENCE.get(value), "duplicate_resolution": "refuse_even_identical; no guessed native winner",
            "selected_lookup_evidence": {"general": "source_and_installed_General_case",
                                         "model": "source_and_installed_legacy_model_case"}.get(selected_section, "unresolved"),
            "section_routing_reference": "research/experiments/MDU-ID-V-stage-01/native-slot-155-01/verification.json",
            "issues": [] if admissible else [issue], "remediation": None if admissible else remediation,
            "source_basis": SOURCE, "engine_initialization": "not_performed",
            "simulation": "not_performed", "scientific_validation": "not_performed",
            "scope": "FM file identity only, not full format/version/configuration or solver acceptance"}


def require(mdu, *, observation=None):
    result = observe(mdu) if observation is None else observation
    if not result["static_launch_eligible"]:
        raise DfmError("fm_model_identity_invalid", "FM Program identity must be resolved before native launch; no Program/version was guessed", 4, result)
    return result
