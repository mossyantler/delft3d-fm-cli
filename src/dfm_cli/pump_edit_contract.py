"""Versioned single-token pump input-edit contract; no runtime evidence lookup."""
import hashlib
import json

CONTRACT = "pump-set-v1"
POLICY_VERSION = "pump-set-publication-v2"
SELECTED_FIELDS = frozenset({"id", "name", "type", "locationfile", "orientation", "numstages", "capacity", "numreductionlevels"})
EVIDENCE = {
    "reference": "research/catalog/pump-drive-gates.json",
    "sha256": "2c2452983126685bfe3e5ae73e93f9472c7fed8d0b2661a7dad116dd2be86b62",
    "scope": "Native #177: one fixed four-link 2D fixture; orientation negative OR capacity -1 alone changed fixed east +4 to -4 m3/s",
    "nominal_total_capacity": "mismatched in that fixture; no rescaling or efficacy promise",
    "geometry_reversal_gate": "Native #175 failed; retained separately, no pump reverse command",
    "handling": "Static portable reference only; never read research evidence at runtime",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def policy():
    # Any behavioral change to edit eligibility, consent or publication MUST bump
    # POLICY_VERSION. Consent binds this explicit policy, not Python file hashes.
    value = {"contract": CONTRACT, "version": POLICY_VERSION,
             "selected_fields": sorted(SELECTED_FIELDS),
             "replacement": "one existing scalar value byte span; literal requested spelling",
             "ownership": "one StructureFile declaration role; no shared input/output/hardlink",
             "consent": "full graph content/identity, directories, request, references, destinations and old/new target bytes",
             "publication": "fsync; recheck full graph and aliases; guarded same-directory atomic replacement; owned readback",
             "access_control": "ACL-bound consent; protected effective stage before payload; Windows ReplaceFileW flags=0; unsupported ACL/metadata refuses before staging",
             "rollback": "only exact publisher-owned inode and proposed bytes; foreign/unreadable target preserved",
             "no_op": "exact raw token equality; recheck only, never replace inode"}
    return {**value, "sha256": digest(value)}


def contract():
    return {"contract": CONTRACT, "commands": {"set": "pump set MDU --id ID (--orientation {positive,negative} | --capacity-m3-s NUMBER) [--apply --expect-sha256 HASH]"},
            "scope": "Existing modern scalar pump input only; explicit Kmx=0; 2–10,000 XY rows; no stages or reduction",
            "exactly_one": ["orientation", "capacity_m3_s"],
            "capacity_m3_s": {"type": "literal signed decimal string", "unit": "m3/s", "maximum_characters": 256,
                              "exponents": "e/E/d/D", "range": "finite normal binary64 or exact zero; no overflow, underflow or subnormal"},
            "unknown_fields": "Unknown selected pump properties block set; inspection may still report them. No stripping or rewrite fallback.",
            "selected_property_allowlist": sorted(SELECTED_FIELDS),
            "preview": "No writes; sha256 binds request, whole supported graph and versioned edit/publication policy",
            "apply": "Requires exact preview sha256; same-input in-place single-file atomic edit; no model copy or geometry edit",
            "policy": policy(),
            "access_control": {"windows": "Windows 10+ local NTFS; ordinary fully inherited allow/deny DACL only; protected/custom DACL and observable access-label/resource metadata refused before staging",
                               "posix": "Current uid/gid, ordinary mode bits, no target extended attributes or parent default ACL",
                               "stage": "Explicit protected effective clone before any model payload; never rely on inherited directory ACL",
                               "publication": "Windows ReplaceFileW without ACL/merge ignore flags; original owner/group/DACL binding verified after commit and rollback",
                               "unsupported": "No arbitrary ACL, auditing SACL, extended-attribute or provider metadata migration qualification"},
            "result_fields": ["sha256", "applied", "changed", "no_op", "edit", "input_files", "references", "publication", "files_written"],
            "exit_codes": {"2": "invalid arguments", "3": "absent, ambiguous or unsupported input", "4": "stale consent, race or publication failure"},
            "limits": ["Input edit only; no hydraulic direction, nominal total discharge or scientific efficacy prediction",
                       "All supported connected input bytes are hashed and rechecked; no native/GUI execution",
                       "Preserve all bytes outside the selected existing scalar token, including capacity/orientation not requested",
                       "Exact raw token no-op does not replace the inode; equal numeric values with different spelling are byte edits",
                       "No filesystem compare-and-swap or global lock against uncooperative writers; race limits remain",
                       "Unsupported access control refuses before staging; protected/custom Windows DACLs require a separate gate",
                       "Rollback restores original bytes only when safe; inode, timestamps and other metadata are not restored"],
            "gui_parity": "not_verified", "native_execution": "not_performed", "hydraulic_effect": "not_predicted", "evidence": EVIDENCE}
