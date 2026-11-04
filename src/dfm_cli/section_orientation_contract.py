"""Public metadata for preserved observation-section direction editing."""
CONTRACT = "observation-section-orientation-v1"
LIMITS = [
    "Only existing output/CrsFile observation sections; never geometry/CrossDefFile or boundary location geometry",
    "One ordinary relative CrsFile .pli; no lists, wildcard/quoted paths, role aliases, symlinks/reparse points or hardlinks",
    "UTF-8/ASCII multi-block PLI, exactly two finite numeric XY columns, 2..100000 vertices per block; at least two Decimal and binary64-distinct vertices",
    "Extra numeric columns/support IDs are refused until their observation-section semantics are supported; no truncation or silent dropping",
    "Section ID is the full trimmed noncomment header record; punctuation/spaces retained; exact selection; duplicate or casefold-aliased IDs refused",
    "Full row bodies including leading/trailing whitespace and inline coordinate comments move; line endings and inter-row trivia stay in their original slots",
    "No CRS/unit/datum inference, conversion, mesh snapping or native initialization; numeric output effects are not predicted",
    "Full supported direct-MDU input graph plus recursively referenced .ext/.ini containers bound using accepted observation graph primitives; opaque leaves are byte-bound, not arbitrary dependency grammars",
    "ObsFile is optional and independent; if declared its supported input bytes are bound without requiring or validating station coordinates",
    "Explicit PathsRelativeToParent=0 or 1 is required; no path-mode default is guessed for edits or inspection",
    "Text at most 8 MiB; 512 connected files/2 GiB; each opaque file at most 256 MiB; at most 512 section blocks/100000 total vertices",
    "Preview hashes a consistent snapshot and checks identities; apply rehashes actual content immediately before one-file atomic replacement; no lock against uncooperative writers",
]


def contract():
    return {"contract": CONTRACT, "commands": {
        "inspect": "section inspect MDU [--id NAME]",
        "reverse": "section reverse MDU --id NAME [--apply --expect-sha256 HASH]"},
        "target_role": "output/crsfile", "inspection": "Omit ID to inventory sections; exact ID selects coordinates and source offsets",
        "consent": "Versioned contract, action, exact ID, graph input paths/bytes/identities/roles/output destinations and target before/after/operation hashes; inspect hash cannot authorize reverse",
        "preservation": "Only selected complete coordinate row BODY spans are permuted; newline bytes, inter-row comments, headers, other blocks and all other files unchanged",
        "record_columns": {"supported": ["X", "Y"], "extra_columns": "refused; not silently interpreted or discarded"},
        "meaning_sources": {"manual":"D-Flow FM User Manual 2026.02 section 7.4.2.3, PDF pages 99-100",
            "engine_source_revision":"5a4649830b1e5072caf019fb4850bbdefd9ad431",
            "engine_source":"dflowfm_kernel/prepost/m_monitoring_crosssections.f90 (section reader and orientation); m_update_values_on_cross_sections.f90 (signed link sum)",
            "scope":"Source-defined direction convention; not proof of native initialization for this request, GUI parity or scientific validation"},
        "signed_quantity_meaning": {
            "direction": "The ordered observation-section polyline defines the signed normal convention for section-oriented discharge, cumulative transport and normal mean velocity",
            "reverse": "Reversing the row order changes that geometric direction convention; wet area is an unsigned quantity",
            "numeric_output": "No solver outputs or numeric effect predictions are produced by inspect/reverse; requires a separate native run and verification"},
        "offsets": "zero-based half-open byte spans; patches, sections and selected_rows describe before_edit even after apply; selected_after is explicitly intended_after",
        "receipt_bound": "First 256 patch records plus deterministic SHA256 of ALL ordered spans; exact target before/after hashes bind complete bytes",
        "errors": "usage2; unsupported/data/alias3; stale/conflict/publication4; no native execution",
        "limitations": LIMITS}
