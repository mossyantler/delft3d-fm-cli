"""G18 standalone transfer contract, separate from G12 orientation editing."""
from .common import DfmError
from .pump_edit_contract import POLICY_VERSION as IMPORT_PUBLICATION_POLICY

CONTRACT = "observation-section-transfer-v1"
EDIT_POLICY = "section-transfer-ascii-core-v1"
EXPORT_POLICY = "section-transfer-exclusive-export-v1"
MAX_TEXT = 8 * 1024**2
MAX_BLOCKS = 512
MAX_VERTICES = 100000
SOURCE = {"revision": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
          "manual": "FM2026.02 PDF99,524; M0 G18",
          "reader": "reapol_nampli.f90:MATR64/REC256,header comments,missingX; m_monitoring_crosssections.f90:259-312,401-444",
          "GUI": "Context menu documented; standalone format/collision/save behaviour unobserved"}


def fail(code, message, details=None, exit_code=3):
    raise DfmError("section_transfer_" + code, message, exit_code, details)


def context(exc):
    """Contextualize shared service diagnostics, never rewrite raw receipts."""
    if exc.code.startswith("section_transfer_"): return exc
    prose = {"Pump input publication did not complete with verified cleanup": "Section input publication did not complete with verified cleanup",
             "Pump input publication currently supports local NTFS with persistent ACLs only": "Section publication currently supports local NTFS with persistent ACLs only"}
    return DfmError("section_transfer_service", prose.get(str(exc), str(exc)), exc.exit_code,
                    {"service_code": exc.code, "service_details": exc.details})


def policies():
    return {"edit": EDIT_POLICY, "import_publication": IMPORT_PUBLICATION_POLICY, "export_publication": EXPORT_POLICY,
            "identity": "full source/graph bytes, roles, file+ancestor identities and security; no implementation source-file reads",
            "no_op": "identical complete import target bytes: full recheck, no stage or metadata churn"}


def contract():
    return {"contract": CONTRACT, "policy": policies(), "commands": {
        "export": "section export MDU (--id FULL_ID repeat | --all) --out NEW.pli [--apply --expect-sha256 HASH]",
        "import": "section import MDU --source EXTERNAL.pli (--id FULL_ID repeat | --all) --mode append|replace-matching --coordinates model-xy-as-is [--apply --expect-sha256 HASH]"},
        "admission": {"whole_file": "all and selected require strict entire-file admission; no archival bypass",
                      "encoding": "ASCII/no BOM; LF/CRLF; no bareCR/control except TAB in count/XY whitespace",
                      "IDs": "1..64 printable ASCII body bytes, canonical edges, no quotes or initial*#;; exact selection, global casefold collision refusal is CLI policy",
                      "records": "body<=256bytes excluding EOL; contiguous header/count/exactlyN two-column XY rows",
                      "numeric": "finite normal binary64 or exact0; E/D allowed; reject X=-999/999.999 including binary64 rounding",
                      "geometry": ">=2distinct Decimal/binary64 points, no binary64 zero adjacent segments; conservative CLI scope, not native validation"},
        "ordering": {"selection": "source file order, not argument order; duplicate selectors refuse",
                     "append": "disjoint incoming IDs, insert cores before destination footer in source order",
                     "replace-matching": "every selected ID exact-matches existing destination; replace destination slots, no append mixture"},
        "trivia": "Core includes header through last XY physical record including EOL; prologue/gaps/footer file-owned. Selected transfer excludes source file-trivia; destination file-trivia exact.",
        "bridge": "First destination EOL after copied no-EOL core whenever anything follows, even newline-leading suffix; also bridge original no-EOL append prefix; no guessed fallback",
        "model_role": "sole existing lowercase.pli output/CrsFile, whitespace-free unquoted relative value, PathsRelativeToParent explicit0|1; MDU unchanged; no INI/list/ref creation",
        "external_paths": "ordinary lowercase.pli outside model, no alias/reparse/hardlink/UNC/device/ADS; export absent path and existing parent, never overwrite/create parents",
        "coordinates": "model-xy-as-is is caller assertion only; no CRS/unit/datum compatibility, conversion, snapping or NetCDF decoding",
        "limits": {"text_bytes": MAX_TEXT, "blocks": MAX_BLOCKS, "total_vertices": MAX_VERTICES, "graph_files": 512, "graph_bytes": 2 * 1024**3, "opaque_file_bytes": 256 * 1024**2},
        "errors": {"usage": 2, "unsupported_data_path_alias": 3, "collision_missing_match_stale_publication": 4},
        "publication": "one existing import target via reviewed ACL writer; export exclusive new name via pinned-parent owned temporary. Raw commit/rollback/cleanup retained; no global writer lock/CAS.",
        "security_scope": "All read-only input file ACL/attribute fingerprints are consent-bound, never copied or claimed migrated. Import target has unchanged reviewed inherited-ACL admission/recheck/preservation; export binds output-parent security and checks created-stage/output security, not source ACL equivalence. Directory identities are bound; general directory ACL migration is not qualified.",
        "evidence": {"GUI_parity": "not_verified", "GUI_collision_policy": "unknown", "native": "not_performed", "scientific": "not_performed", "G12_XYN_approval": "not_inherited"}, "source": SOURCE}
