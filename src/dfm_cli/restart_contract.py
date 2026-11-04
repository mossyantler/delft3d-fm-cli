"""E013 exact serial 2D restart preparation; native acceptance is PENDING.

Public integration contract
---------------------------
``prepare(previous_run: Path, mdu: Path, out: Path, stop: str,
           apply: bool=False, expected: str|None=None) -> dict``
CLI proposal: ``restart prepare PREVIOUS_RUN MDU --out NEW --stop YYYYMMDDhhmmss
[--apply --expect-sha256 HASH]``. Preview is read-only (including no mkdir).
Apply requires preview's content fingerprint; existing/dangling-link destinations
are conflicts. Sources/run manifests are never rewritten. Relative paths plus
embedded evidence permit moving BOTH previous runs and prepared segments.

Only a completed manifest v3 with rc0, passed CF verification and confirmed empty
owned Windows job can supply a state. Hashes/actual times are rechecked, not just
trusted flags. Exactly one recorded final one-snapshot *native legacy* restart
must match the previous stop. UGRID map files, MPI/merged/3D/transport/morphology,
changed grid/forcing/physics, smoothing and implicit time origins are refused.
NetFile must be 2D UGRID; its exact SHA and net dimensions must agree with the
staged prior input and native state dimensions. No remeshing/interpolation.
Input BC harmonic or linear timeseries waterlevelbnd only; every timeseries must
already cover the complete new interval. Prepare cannot extend/crop forcing.
RefDate and TUnit remain fixed, UTC only; absolute and relative start/stop are
written consistently. This first scope requires the existing absolute/relative
parent and source endpoints to agree (conflicting representations are refused).
History/map/restart intervals and DtUser remain unchanged
and must align both to the cut and to the new stop. First parent must be cold;
restart chains require a later independent case. Segment duration <=600s until
the coordinator explicitly integrates the independently verified M5 profile.
Essential hydraulic state must be finite and unmasked. Native diagnostic czs can
be entirely masked in the observed writer; its mask is recorded/preserved rather
than fabricated. E013 must establish that this writer's state is actually usable.

Copied files retain their original relative names and bytes except requested MDU
time/restart tokens. New reserved files: restart-state_rst.nc, restart-parent.json,
restart-parent.mdu, restart-source.mdu, restart-preparation.json. Existing names
colliding case-insensitively with these are refused. The parent/source MDU copies
are evidence snapshots, not extra engine models. Provenance is not a run manifest.

Coordinator-owned hooks (this node MUST NOT edit shared modules):
1. CLI delegates to prepare(...); --apply requires --expect-sha256, returns JSON.
2. In model validation, when RestartFile is nonempty, call
   ``restart.augment_report(report, mdu)``. This removes ONLY the exact unsupported
   RestartFile issue after guard succeeds, and adds the state and ALL receipt/
   metadata files to the staged/hash-checked input graph. It preserves all other
   issues and all cold-model behavior.
3. In the existing runs.profile, call ``restart.guard(mdu)`` for that explicit
   experimental restart profile; retain every cold constraint except the single
   nonempty RestartFile exception. Do not broadly relax the cold path. Store the
   guard result in the run profile/manifest. Re-run it on staged inputs before
   launch. No second native runner, process adoption or new cancellation path.
4. After installation selection call ``restart.check_engine(info, install,route)``
   to enforce exact previous native executable/kernel hashes and direct route.
5. Output verification still requires full CF first/final/cadence and restart
   completion for the NEW segment. Input snapshot/state files are excluded via
   manifest.inputs; selected input state must never masquerade as new output.
6. Independent E013 harness must actually use the existing owned run start on
   continuous, first, and prepared resumed inputs (exclusive coordinator slots).
   ``restart_compare.compare(continuous, first, resumed, rtol=..., atol=...)``
   consumes completed native evidence, checks initialization from the selected
   state, all concatenated history/map fields/masks and final native state arrays.
   Caller MUST choose/report tolerances; no universal scientific threshold. A
   prepared folder or completed process is never the scientific gate. Preserve
   failures and warnings. E013 is not complete until independent native replay.

Static/manual evidence: D-Flow FM UM 2026.02 §8.8 pp142-143, §11.1.1.5 pp170-172,
Appendix F.3.4 p542 (PDF pages +26). Collected source commit
5a4649830b1e5072caf019fb4850bbdefd9ad431:
* m_flowtimes.f90:39/69 (all times relative to RefDate), :296-345 (reset schedules).
* flow_flowinit.f90:815-873 load_restart_file -> read_restart_from_map.
* unstruc_netcdf.f90:13394 unc_read_map_or_rst (actual entry in this revision,
  rather than inferring a read_restart_nc symbol), :13539 UGRID rejection,
  :13669-13730 snapshot/time selection, :13733 timestep, :13751+ s1/s0/czs/unorm.
* unstruc_model.f90:1881-1882 RestartFile/RestartDateTime; :2499 smoothing warning.
Native code can select an earlier map time with a warning. This product refuses
that fallback and uses one native snapshot with a blank RestartDateTime.

Public comparison v2 (read-only, including all original run manifests):
``restart_compare.compare(full, first, resumed, rtol=0, atol=0)`` OR
``restart_compare.compare(full, first, resumed, policy=Path(POLICY),
                         continuity="raw"|"join")``.
Coordinator CLI hook: retain FULL FIRST RESUMED; add --tolerances POLICY (mutually
exclusive with the uniform --rtol/--atol pair), --continuity {raw,join} default raw;
pass policy=args.tolerances and continuity=args.continuity. Existing caller exit6
on report.state != passed remains correct: TOP-LEVEL STATE ALWAYS MEANS RAW
NATIVE EQUIVALENCE, including when a derived join passes. Do not change manifests
to completed/failed based on the joined view; native run completion and numerical
comparison are distinct. Schema v2 has manifest_status, raw_native_equivalence,
source_diagnosis and optional joined_continuity, plus every existing per-field
report. Original numerical arrays, masks, fields and tolerances are retained.

Policy shape: tolerances:{category:{rtol,atol,unit?:annotation}},
per_variable_rules:{exact_variable_name:category}, exact category={rtol:0,atol:0},
unlisted_fields="exact; never omitted", static_fields="exact", masks="exact".
The original E013 predeclared policy JSON is accepted unchanged and fingerprinted.
No name-pattern tolerance inference, unit conversion, exclusion or runtime relax.

Per dynamic field: concatenated_values, first_control, resumed_after_cut,
cut_overlap, final_full_field, field_kind, distinction, tolerance, storage_dtype.
Initialization includes an ADDITIONAL exact native_output_encoding_match (casting
saved state to the writer dtype), while retaining original raw tolerance verdict.
Actual coordinate time is rank1 with its own dimension; rank2 time_bds is checked
as a data field. Native effective RestartFile parsing strips trailing # comments.

Join is a separately labeled data reconstruction: keep first's last sample at
the cut; source-confirmed cumulative fields only use resumed(t)+first(cut)-
resumed(cut), computed in float64. Instantaneous total_volume is never offset.
Neither control data nor best-fit offsets enter construction. Duplicate native
diagnostics remain in raw cut_overlap. Float32 rounding-cell diagnostics are
reported without changing acceptance, proving native accumulators, or hiding
remaining errors. Lost precision and omitted counters cannot be recovered by an
XML/MDU restore flag found in the inspected source. True native continuity needs
engine accumulator serialization/restoration plus consistent initial diagnostic
state, then a separate native replay; a persistent BMI worker is separate scope.

Observed E013-restart-native-20261104-01 (read-only reanalysis, no new launch):
57 history, 34 map and 34 final state fields checked. Final state is exact. Under
the predeclared policy, raw cumulative offsets include inflow1146.9891357421875m3,
outflow1008.1171875m3, storage/net138.87191772460938m3. Cut tausx discrepancy is
0.14413121342658997N/m2, viu0.000674806535243988m2/s, and time_bds10s. A join still
fails the unchanged exact balance tolerances: inflow residual0.0003662109375m3,
outflow0.0001220703125m3, storage/net4.76837158203125e-6m3. Residuals are compatible
with independent float32 rounding cells; that is not strict equivalence. Volume
error's offset can be joined exactly. All native files/manifests remain intact.
"""
