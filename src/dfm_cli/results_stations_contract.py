"""G11-ASSIGN public contract and JSON examples; root registration is G-owned.

  results stations RUN
  register(existing_results_subparsers) -> same SubParsersAction
  execute(args) -> dict; stations(run:Path) -> dict; contract() -> dict

No --out: JSON stdout only. Never mutate the run, inputs, manifests or sidecars.
Use only current optional run extra (netCDF4/numpy), stdlib struct for narrow
point SHP/DBF/SHX. No GIS dependency or installed engine/source requirement.

Proof policy: complete matching SHP/SHX/DBF set, ID-exact joins (NFC/casefold
aliases refused, never normalized into a match), DBF ORIG_X/Y exactly match actual history and
recorded input XY; FLOWNODENR positive; SHP point exactly matches a UNIQUE map
face coordinate and FLOWNODENR-1 equals that index. Require matching explicit
units/CRS declarations and complete identical CF time axes, uncompressed scalar
waterlevel/mesh2d_s1 units/dtype, masks and all finite unmasked values exactly.
At least one finite paired sample is required (all-masked equality is vacuous).
Declared history CF point geometry must agree with reported station XY, and
waterlevel coordinate references must agree with their station/mesh topology.
Only THEN publish assigned map face, and assigned input face only via an exact
unique polygon ring join (rotation/reversal allowed, no coordinate tolerance).
Input face numbering and runtime map numbering are independent.

Missing GIS, missing station row, absent history ID, mismatched axes/coordinates,
masked/nonfinite data or missing map produce explicit unknown/reason states.
Raw GIS FLOWNODENR is reported as measured evidence even when assignment is not
proven. Never infer assignment from nearest coordinates, equal time alone or
series coincidence alone. Never label masked as necessarily dry or infer the
cause from dry-polygon settings. No pre-run GUI estimated feature is reported.
All SHP/SHX/DBF absent is unknown; a partial recorded or available set is a
structured data refusal (exit3). Initial selected data differing from recorded
manifest length/hash is malformed recorded data (exit3); in-flight replacement
or mutation during snapshot/final recheck is a conflict (exit4).

Integrity: read a strict bounded run manifest (duplicate JSON keys refused),
rebase recorded relative routes beneath selected RUN (move allowed), require
every selected artifact match its recorded SHA256/length, reject links/aliases,
and rehash selected files after reading. Scope is selected manifest-backed
MDU/XYN/NetFile/history/map/GIS, not cryptographic/native-process attestation.
Streaming summaries/comparison use bounded time blocks; arrays/time/geometry and
join work have hard budgets. No dense station*time*face search.

Evidence separation: parent native #163 wet/dry retained at
G11-DRY-I-native-163-01; prior G06-OBS-G-raw-01 is a separate history/map gate.
Pinned source5a4649830b1e5072caf019fb4850bbdefd9ad431:
unstruc_shapefile.F90:141-249 writes ObjectID, ORIG_X/Y, FLOWNODENR=kobs and
SHP xz(k),yz(k), skipping k<=0. This source is not asserted installed binary SHA.
Manual §7.4.2.1 PDF96-98 estimated features ignore dry areas; this command reads
recorded execution outputs, not that GUI layer. No GUI/native/science claim.
"""

CONTRACT="results-stations-v1"
MAX_STATIONS=4096
MAX_TIMES=100000
MAX_SAMPLES=20000000
MAX_FACES=40000
MAX_NODES=100000
TIME_BLOCK=512
LIMITS=["Manifest-backed serial standalone named XYN observations and scalar 2D hydrodynamic waterlevel only; no MPI/1D/3D/moving stations",
        "Complete CF axes must match for all-times proof; no interpolation, intersection or tolerance expansion",
        "Complete point SHP/DBF/SHX parser is intentionally narrow; non-ASCII DBF IDs without explicit supported encoding are refused",
        "Assigned input face requires exact unique polygon geometry, not reuse of a runtime map index",
        "Missing GIS evidence is unknown; an absent history ID differs from a present masked station",
        "All GIS components absent is unknown; partial GIS is malformed data (exit3). Initial recorded hash mismatches exit3; in-flight replacement/recheck races exit4",
        "Masks and nonfinite counts are observations, not a diagnosis of dryness",
        "Selected files must match recorded manifest hashes; no complete-run revalidation or process ownership/native science attestation",
        "Bounded streaming/read-only; no GUI estimate, nearest face, snapping, transformation or installed-suite access"]
EXAMPLES={"masked_without_GIS":{"station_id":"centre","history_presence":"present","waterlevel":{"samples":13,"masked":13,"finite_unmasked":0,"nonfinite_unmasked":0},
                                "assignment":{"state":"unknown","reason":"no_matching_snapped_station_record","input_face":None,"map_face":None}},
          "absent_history_ID":{"station_id":"centre","history_presence":"absent","waterlevel":None,
                               "assignment":{"state":"unknown","reason":"absent_history_id","input_face":None,"map_face":None}}}


def contract():
    return {"contract":CONTRACT,"command":"results stations RUN","dependencies":"optional run extra only; no heavy GIS dependency",
            "identity":"actual station_id, exact joins only; duplicate/NFC/casefold aliases refused within and across datasets; names/coordinates never substitute for a missing ID",
            "assignment_proof":"complete manifest-backed SHP/SHX/DBF, exact coordinates/index, input polygon identity, same full CF axes, exact all-times finite waterlevel/masks",
            "mask_meaning":"missing/invalid samples only; not necessarily dry","output":"JSON stdout only; no artifact/manifest writes",
            "errors":{"3":"Malformed/unsupported recorded data, partial GIS, ambiguous IDs, or initial selected-file hash mismatch","4":"In-flight replacement/mutation or active writer"},
            "bounds":{"stations":MAX_STATIONS,"times":MAX_TIMES,"history_samples":MAX_SAMPLES,"faces":MAX_FACES,"nodes":MAX_NODES,"time_block":TIME_BLOCK},
            "examples":EXAMPLES,"gui_parity":"not_verified","native_execution":"not_performed","limits":LIMITS}
