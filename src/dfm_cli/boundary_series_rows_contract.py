"""Versioned B03-ROWS integration metadata; no live CLI edits in this stage."""

CONTRACT = "preserved-waterlevel-series-rows-v1"
LIMITS = [
    "Existing new EXT waterlevelbnd/O, single-polyline 2D geometry, exact existing support; explicit linear timeseries only",
    "Existing exact UTC Unit strings retained; seconds/minutes/hours/days since YYYY-MM-DD HH:MM:SS +00:00; MDU TUnit S/TZone 0 and absolute start/stop",
    "Insert explicit time/value strings and delete whole existing numeric lines; no interpolation, retiming, value replacement or changed units",
    "Time matching/duplicates/overlap use exact Decimal equality; binary64/MJD collisions additionally refused",
    "Deletion of any row carrying an inline # comment is refused; original standalone comments and all untargeted bytes remain in place",
    "Inserted rows are ordered by exact time and anchored after the preceding original row, or before the first row; local newline style is used",
    "A retained numeric EOF without newline requires an explicit inserted separator, reported separately; original EOF row bytes are unchanged",
    "At least 2 and at most 100000 resulting knots; strict time order and full absolute model coverage required",
    "Request at most 1 MiB/10000 total insert+delete actions; BC at most 16 MiB; numeric strings at most 256 ASCII bytes",
    "Supported full MDU/new-EXT/PLI/BC/Meteo input graph and request path/bytes bound; large inputs stream-hashed; unknown input containers and aliases refused",
    "One BC atomic replacement with final actual-content graph/request recheck; no cross-file lock against uncooperative writers",
    "BOM preserved; known destination-marker compatibility observation only; no engine/GUI/scientific acceptance",
]


def contract():
    return {
        "schema_version": 1, "contract": CONTRACT,
        "command": "boundary series-rows",
        "usage": "dfm boundary series-rows MDU --point ID --rows FILE [--apply --expect-sha256 HASH]",
        "request": {"exact_keys": ["time_unit", "value_unit", "insert", "delete"],
                    "time_unit": "Existing BC Unit string exactly, including UTC origin",
                    "value_unit": "Existing BC Unit string exactly (m in this profile)",
                    "insert": [{"time": "ASCII decimal string", "value": "ASCII decimal string"}],
                    "delete": ["Existing time as ASCII decimal string"],
                    "rules": "Both arrays required; at least one action. Order arbitrary; exact Decimal duplicates, overlap, nonexistent deletion and existing insertion refused"},
        "example": {"time_unit": "seconds since 2026-01-01 00:00:00 +00:00", "value_unit": "m",
                    "insert": [{"time": "30", "value": "0.125"}, {"time": "90", "value": "0.175"}], "delete": ["60.0"]},
        "apply": "Preview writes nothing; exact contract/graph/request/point/action, original and resulting target hashes and operation receipt bind input_sha256; plan is recomputed before apply",
        "receipt": "Affected actual inserted/deleted rows, exact removed line bytes/base64/hash, before-edit offsets, actual resulting count/range/coverage, explicit EOF framing, intended after_sha256",
        "source_basis": {"format": "Existing B03 linear water-level series validator and B09 full graph binder reused by imports",
                         "clock": "Absolute model start/stop override relative times; RefDate need not equal start; BC origin remains explicit",
                         "native_status": "not_performed; syntax and preservation checks only"},
        "limitations": LIMITS,
    }


def schema_metadata():
    return contract()
