"""Read-only comparison of completed, pinned example03 positive/control runs.

PUBLIC: dfm water-quality compare POSITIVE_RUN CONTROL_RUN --bundle BUNDLE
                                [--samples-per-time 3] (integer0..5)
API: water_quality_compare.compare(positive_run, control_run, *, bundle,
                                  samples_per_time=3) -> JSON-compatible dict.
Only run folders, not arbitrary NetCDF paths. No execution or output mutation.
Requires optional existing run extra (netCDF4/numpy), never research/verifier code.

Role proof is retained bundle spec-positive/spec-control plus each staged original
coupling-source.json fingerprint, normalized spec, physical RcNit and all copied
input hashes. Both share pinned70 original hashes; reconstruct original SUB and
replay declared MDU patches, bind dat/def and all common physical inputs. Recorded
executable/module hashes must match between runs and argv/installation metadata;
no installed suite/original source folders need remain present. All current staged
inputs, output inventory, raw MAP/HIS, timers and bundle files must rehash. Require
completed manifest3, verified simulation, exit0, exact private-Job ownership and
recorded empty final Job; never adopt/re-run old processes. Historical manifests
are evidence, not cryptographic attestation. Relocating the enclosing evidence
folder is allowed; all current reads stay within supplied roots, no recorded
absolute model/log/output paths are followed.

Native timing proof: CF time coordinate/reference/calendar/units and exact inclusive
declared cadence in map AND history; detailed timer initialization snapshot and
final snapshot must agree by timer ID/context. One initial call for each of the
3 process/copy routines, plus one distinct scheduled context for each with
duration/DtProcesses calls. Same names in different contexts are not added or
misclassified. This checks counts, not individual unavailable event timestamps.

Native topology/coordinates/vertical dimensions/metadata and masks must match
without remapping. Pinned native map has222faces/12layers,258nodes/479edges;
counts of valid cells/faces are measured per time, not assumed from dimensions.
Require initial NH4/NO3/OXY equality; map s1/waterdepth/ucx/ucy/ucz and history
waterlevel equality. Same raw history chemistry units/masks/initial conditions.
Missing, truncated, reversed, nonfinite, masked-time, stale, unbound or mismatched
evidence fails. No filling, cropping, interpolation or scientific recalibration.

RESULT schema1: comparison='passed'; provenance{bundle/manifest/output hashes,
roles, common native input and recorded binary hashes}; timing{state,clock,
positive/control:{map/history axes,process_schedule}}; topology; initial_equality;
hydrodynamic_equality; history; paired_metrics by exact map variable (NH4/NO3/OXY)
with unit, spatial dimensions and by_time rows{time,valid_cells,masked_cells,
valid_faces,positive/control/delta:{minimum,mean,maximum},detected,samples}.
Statistics and subtraction accumulate in float64 from native values. Samples
(0..5 per variable/time) are actual finite native face/layer indices,
face x/y with native units, positive/control values and delta; largest absolute
changes, deterministic flat-index tie break. No raw field arrays in public JSON.
Effect thresholds reuse the accepted preparation plan for final NH4 decrease and
NO3 increase. OXY response is reported as a diagnostic; no new calibration claim.
Separate effect_detection and timing from scientific_validation='not_performed'.
Input/data errors use DfmError exit6 and water_quality_compare_* codes; missing
optional reader uses existing missing_dependency error. Independent verification
and native preparation acceptance are separate gates from this product command.
"""

CHEMISTRY = (("mesh2d_NH4", "NH4", "g/m3"), ("mesh2d_NO3", "NO3", "gN/m3"),
             ("mesh2d_OXY", "OXY", "gO2/m3"))
HYDRO = (("mesh2d_s1", "m"), ("mesh2d_waterdepth", "m"), ("mesh2d_ucx", "m s-1"),
         ("mesh2d_ucy", "m s-1"), ("mesh2d_ucz", "m s-1"))
ROUTINES = ("fm_wq_processes_step", "copy_data_from_fm_to_wq_processes", "copy_data_from_wq_processes_to_fm")
DETECTION = {"mesh2d_NH4": 1e-4, "mesh2d_NO3": 1e-4, "mesh2d_OXY": 1e-4}
