"""B09 file-level merge contract; GUI/console import parity is untested.

Parent hooks: register(existing_boundary_subparsers), execute(args).
Public command: dfm boundary import MDU --boundary EXACT_PLI_LABEL --source FILE
--format {bc,csv} --mode {replace,extend,overwrite-all} [--mapping FILE]
[--apply --expect-sha256 PREVIEW_INPUT_SHA256].

replace: import matching supports, including empty ones.
extend: import matching empty supports; preserve populated ones.
overwrite-all: import matches and clear unmatched selected-boundary supports.
At least one source support must match. Other boundaries are never targets.

Mapping v1 declares UTC explicitly. Its zone-free epoch spelling means UTC by
this schema, NEVER host/local time. +00:00 is written into canonical BC units.
Numeric CSV times are offsets in the declared unit from that epoch, independent
of MDU RefDate; full coverage is checked against explicit UTC Start/StopDateTime.
No timezone/unit conversion, time guessing, snapping or engine/GUI execution.

A leading UTF-8 BOM in the destination is preserved, even though the observed
FM suite rejects that marker. This is a file preservation operation, not an
encoding repair. External source/mapping BOMs are decoding markers and are not
transplanted into the destination header. Native compatibility observations
report only this resulting leading marker, never successful initialization of
the edited model. Separately author or explicitly normalize a COPY if desired;
no normalization command or automatic marker removal is provided here.
"""
CONTRACT = "preserved-waterlevel-import-v1"
LIMITS = [
    "One existing target BC, new EXT waterlevelbnd O operand and exact 2D PLI label",
    "Explicit 2D UTC-seconds MDU and absolute start/stop; linear two-column water-level series in m",
    "Source BC: every block must be a valid nonempty linear series with a unique support name",
    "Validated unmatched source supports and unused CSV columns are explicitly reported",
    "Destination selected supports: absent, empty linear block or valid linear series; function switching refused",
    "Other-boundary harmonic/linear blocks preserved; unknown destination blocks/functions refused",
    "Existing target metadata/units must agree exactly; no silent origin or unit conversion",
    "Replacement keeps destination metadata, whitespace and comments; row surplus loses numeric tokens only",
    "Clearing deactivates active block lines with a comment prefix; original text/comments retained",
    "CSV: UTF-8 RFC4180 comma delimiter, unique explicit header, exact mapping v1, no blank/unequal rows",
    "At most 64 source supports, 100000 source rows, 16 MiB BC/CSV, 1 MiB mapping; finite decimal tokens <=256 bytes",
    "Request, source, mapping, paths and connected model inputs bind the preview; one atomic BC write",
    "Patch receipt keeps up to 256 ordered spans plus total/omitted counts and a digest of ALL span records; after_sha256 binds exact output bytes",
    "Shared target BC allowed only for disjoint support identities; links, aliases and ambiguous writes refused",
    "All supported MDU inputs and Meteo bytes are bound, including mesh/network/obs/thin/dry/land/restart inputs; large files use streamed SHA256",
    "Actual content hashes are revalidated before every apply, including no-op; output destinations are not inputs",
    "Undeclared input-file references, unsupported direct formats and unknown dependency containers are refused",
    "Destination UTF-8 BOM is preserved and reported as known incompatible on the observed FM suite; source/mapping BOMs are not propagated into its header",
    "No-BOM means only that this leading marker was checked; native initialization of the edited model remains untested",
    "No GUI runtime parity, engine initialization, simulation or scientific validity inferred",
]
SOURCE = {
    "manual": "D-Flow FM User Manual 2026.02 revision 81168 section7.4.8.2 PDF121-125 (mode definitions on124)",
    "inventory": "B09 GUI/console import/diff untested; file-level contract implemented separately",
    "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
    "time_conversion": "src/utils_lgpl/ec_module/packages/ec_module/src/ec_support.f90:1331-1340",
    "native_evidence": "not established by this operation",
    "destination_bom_observation": "B09-G-BC-BOM-01/verification.json; observed installed FM rejects leading U+FEFF[General]; no silent normalization",
}

DESTINATION_BOM_EVIDENCE = {
    "gate": "B09-G-BC-BOM-01/verification.json",
    "gate_sha256": "f170d18f33b3dbd3760dd1be0c6bb5b0b78ab783a9f858f23ac21a9e6ff8c4b4",
    "suite_observed": "2026.02 OpenHMWQ",
    "engine_version_observed": "1.2.184.Unknown",
    "recorded_binary_sha256": {
        "bin/dflowfm-cli.exe": "78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2",
        "lib/dflowfm.dll": "ca6de0b6d900a51ece33140b4666ca97d6875d8e60cac31e91ad072800f1df99",
    },
    "controlled_change": "Only the leading EF BB BF bytes were removed; remaining model bytes identical",
    "bom_result": {"engine_returncode": 1, "diagnostic": "Unknown block type U+FEFF[General]"},
    "no_bom_control_result": {"engine_returncode": 0, "final_seconds": 120},
    "scope": "Retained native A/B observation for this suite; not execution or initialization of the selected import model",
    "installed_source_commit": "not inferred from suite or version",
}
