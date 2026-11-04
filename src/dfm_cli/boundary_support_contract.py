"""B10 file editor contract; GUI and engine behavior remain separate gates."""

CONTRACT = "boundary-support-function-v1"
SOURCE = {
    "manual": "D-Flow FM User Manual 2026.02, revision 81168, section 7.4.8.2, printed p.93 / PDF p.119",
    "documented": "Deactivating a support loses its data; changing a polyline function loses its data",
    "implementation": "Explicit new-EXT/BC file editing; selected blocks removed entirely, exact original slices exposed in receipt only",
    "native_counterexample": "B10-G-native-02/run-candidate-disable/stdout.log (#128): historical retirement comments in an active numeric stream rejected; repaired representation awaits native replay",
    "pinned_reader_analysis": "Deltares/Delft3D 5a4649830b1e5072caf019fb4850bbdefd9ad431, ec_bcreader.f90:778-819 / ec_filereader_read.F90:1244-1282: block headers/EOF terminate harmonic reading; semantic comment stripping alone is not a native-format test",
    "gui_runtime_parity": "not_established",
}
LIMITS = [
    "Existing new EXT, 2D UTC-seconds MDU, exact unique PLI label/support IDs; waterlevelbnd only",
    "One target BC, shared with other water-level boundaries allowed; PLI and EXT are never modified",
    "Harmonic minutes/m/deg or linear UTC time-series/m only; no corrections, astronomy, QH or layered functions",
    "Enable requires a complete one-point BC source and the same function as existing active points; disabling the last active point is refused",
    "Function change requires the other function and exactly every currently active point; inactive points are preserved",
    "Source BC at most 64 blocks, aggregate 100000 rows; target/source at most 16 MiB; source General header is not copied",
    "Selected Forcing spans run from their section header through just before the next section or EOF, including trailing comments; only those complete spans are removed",
    "Removed exact slices are base64/hash in the receipt ONLY; save preview/apply output to retain them; no separate archive file or in-BC tombstone is written",
    "Historical boundary-support retired-marker input is refused; use an unchanged fresh baseline, never implicitly normalize or reinsert its old comment tails",
    "Incoming comment-only records after numeric data are refused rather than copied or silently stripped; header comments and inline row comments are preserved",
    "Appending new blocks requires newline-terminated nonselected final blocks; otherwise exact nonselected-span preservation refuses the edit",
    "Full supported input graph content bound with streamed large inputs; unknown input containers and aliases refused",
    "Single-file atomic replacement, not a model-wide lock or compare-and-swap against uncooperative concurrent writers",
    "BC BOM is preserved and its known installed-suite incompatibility reported; no automatic normalization",
    "No engine initialization, simulation, scientific validation or GUI execution",
]


def contract():
    return {
        "schema_version": 1,
        "representation_revision": 2,
        "contract": CONTRACT,
        "commands": {
            "boundary support": {
                "required": ["mdu", "--boundary", "--point", "--state"],
                "state": ["enable", "disable"],
                "source": "--signal FILE.bc required only for enable; exact one complete matching support",
            },
            "boundary function-set": {
                "required": ["mdu", "--boundary", "--function", "--signals"],
                "function": ["harmonic", "timeseries"],
                "source": "BC exactly covers active points; all blocks have the requested new function",
            },
        },
        "apply": "--apply --expect-sha256 INPUT_SHA256 from the exact preview; preview writes nothing",
        "examples": [
            "dfm boundary support COPY/model.mdu --boundary east --point east_0003 --state enable --signal examples/boundary_support/enable-east-0003.bc",
            "dfm boundary support COPY/model.mdu --boundary east --point east_0002 --state disable",
            "dfm boundary function-set COPY/model.mdu --boundary east --function timeseries --signals examples/boundary_support/east-linear.bc",
            "dfm boundary function-set COPY/model.mdu --boundary east --function harmonic --signals examples/boundary_support/east-harmonic.bc",
        ],
        "example_scope": "Explicit source signals only, not complete native models. Adjust exact IDs, populated-point coverage, dates and units to the copied destination. selfcheck.py is a static hook test with a mesh hash sentinel, not an engine case or second CLI.",
        "signal_format": {
            "header": "[General], fileVersion=1.01, fileType=boundConds",
            "harmonic": "[Forcing] Name, Function=harmonic; ordered Quantity/Unit harmonic component/minutes, waterlevelbnd amplitude/m, waterlevelbnd phase/deg; complete numeric rows",
            "timeseries": "[Forcing] Name, Function=timeseries, Time-interpolation=linear; time/UNIT, waterlevelbnd/m; >=2 strictly increasing knots covering model interval",
            "clock": "UNIT: seconds|minutes|hours|days since YYYY-MM-DD HH:MM:SS +00:00; explicit UTC, relative to its own epoch, checked against MDU RefDate/StartDateTime/StopDateTime; no host timezone inference",
        },
        "receipt": "before_edit offsets; complete per-support before/after state, exact retired base64 bytes/hash, full replacement block bytes/hash, target after_sha256",
        "errors": "usage/expected_hash_required (2); unsupported/ambiguous/invalid input (3); stale_preview/preservation/publication (4); no native launch",
        "source_basis": SOURCE,
        "limitations": LIMITS,
    }
