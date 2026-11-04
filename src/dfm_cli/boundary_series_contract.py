"""B03 public integration contract and portable examples.

Parent hooks: register(existing_boundary_subparsers); execute(args). Commands::

    boundary series-inspect model.mdu --point east_0001
    boundary series-set model.mdu --point east_0001 --values changes.json
    boundary series-set model.mdu --point east_0001 --values changes.json \
        --apply --expect-sha256 PREVIEW_INPUT_SHA256

changes.json for the reviewed authored 1200-second M5 channel::

    {"time_unit":"seconds since 2001-01-01 00:00:00 +00:00",
     "value_unit":"m",
     "changes":[{"time":"0","value":"0.01"},
                {"time":"1200","value":"-0.02"}]}

The edit fingerprint binds graph paths/bytes, point, request path and EXACT JSON
bytes. An inspect fingerprint is not a series-set preview fingerprint. Edit
reports label series_snapshot='before_edit': the series and all source byte
offsets describe the pre-edit BC. Each change.after is a replacement token;
after_sha256 identifies the intended resulting bytes. Inspection and editing do
not establish GUI execution, engine initialization, simulation or scientific
validity for the inspected model.
"""

CONTRACT = "preserved-waterlevel-series-v1"
LIMITS = [
    "New EXT waterlevelbnd O operand, single 2D PLI per boundary; exact existing support ID",
    "Selected BC: explicit linear timeseries, ordered time/Unit then waterlevelbnd/m",
    "Explicit UTC seconds/minutes/hours/days since YYYY-MM-DD HH:MM:SS +00:00 only",
    "Explicit 2D UTC MDU with absolute start/stop and TUnit S; knots cover its full interval",
    "Change existing value tokens only; no knot insertion, deletion, retiming or interpolation change",
    "Unknown selected metadata, duplicate/colliding times and ambiguous identities are refused",
    "UTF-8/ASCII; existing # inline comments and whole-line semicolon comments preserved",
    "Request: at most 1 MiB and 1000 changes; BC: at most 16 MiB and 100000 selected rows; numeric tokens: at most 256 bytes",
    "Shared disjoint support names allowed; shared opaque consumers, BC/request hard links and symlink/junction paths refused",
    "Other connected files are preserved; unrelated Meteo inputs retain the existing graph's identity-only fingerprint scope",
    "Atomic single-BC replacement with final graph/request recheck; no cross-file lock against uncooperative writers",
    "No CRS/datum transformation, model calibration, GUI or native execution",
]
SOURCE = {
    "kind": "documented format and static pinned source; no new native evidence",
    "manual": "D-Flow FM User Manual 2026.02 revision 81168 C.5/C.6; B03 inventory",
    "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
    "source_prefix": "src/utils_lgpl/ec_module/packages/ec_module/src/",
    "header_normalization": "ec_bcreader.f90:405-416,536-554",
    "time_conversion": "ec_support.f90:1331-1340",
    "reviewed_authored_input": "M5-G-coordinator-final-01/prepared; east_0001, 0..1200 seconds",
    "scope": "Source-informed format and rounding checks do not establish native acceptance of a changed signal",
}
