"""E015-WQ v1: offline authoring contract, all native/scientific gates pending.

Public hooks, additive to coupling (no shared CLI edit):
  register(groups) -> argparse subparsers; execute(args) -> JSON-compatible dict
  build_process_specs(spec: Path, out: Path, process_library: Path,
                      apply=False, expected=None) -> preview/apply receipt
  guard(bundle: Path) -> re-read all authored input/spec fingerprints
  review_offline(hyd: Path, inp: Path, install: Path | None) -> static review

Proposed commands:
  water-quality prepare SPEC --out NEW --process-library PROC_DEF_DAT
                        [--apply --expect-sha256 PREVIEW_HASH]
  water-quality inspect BUNDLE
  water-quality review-offline HYD INP [--install SUITE]
Until coordinator registration use `python -B -m dfm_cli.water_quality ...`.
This module does not start an engine, WAQ preprocessor, launcher or GUI. Generated
spec-positive.json/spec-control.json are ordinary coupling.prepare schema1 inputs:
  dfm coupling prepare BUNDLE/spec-positive.json --out FRESH_CASE
  dfm coupling prepare ... --apply --expect-sha256 HASH
After those cases pass independent review, the coordinator's existing owned
coupling run route may execute them in separately allocated native run folders.

Fixed authentic basis: DIMRset_2026.02 commit PIN below, example03 f34_dynamo,
70 exact dflowfm files; one dflowfm component, processlibrary setting, no second
WAQ component and no scalar coupler. All native definitions/processes, mesh,
initial/boundary fields and unrelated bytes are preserved. A native process
database pair (proc_def.dat AND proc_def.def) is explicitly copied per case.
Its installed hashes are not inferred to equal the collected source revision.

Each pair: start/reference1990-08-05T00:00:00Z; stop after600..3600s; seconds,
UTC; process step60s; regular history/map300s; WaqInterval0 to keep offline
hydrodynamic-export semantics distinct. Sole positive/control physical input
difference is dynamo.sub parameter RcNit: explicit positive0.1..2 /day vs0 /day.
Both append explicit common SWVnNit=0 (original first-order branch) and ZNit=0
(background nitrification flux); installed database defaults are not assumed.
All original processes including Nitrif_NH4 stay active in BOTH cases.
Expected NH4 decreases and NO3 increases relative to the matched control;
OXY is retained as a reaction-related diagnostic. Other processes remain active,
so no one-box exponential, isolated stoichiometry or conservation claim is made.

Native fields declared from pinned source (installed schema still must be read):
 dflowfm/output/f34_dynamo_map.nc, time CF coordinate;
 mesh2d_NH4 g/m3; mesh2d_NO3 gN/m3; mesh2d_OXY gO2/m3; mesh2d_s1 m.
NH4 source concentration-unit is literally g/m3; do not relabel it silently as
gN/m3. Source init polygon NH4=.4, OXY=8; source boundary NH4=.4 with legacy
BC unit '-'. Inherited f34 CRS/datum are explicit unknown/unverified provenance,
not EPSG guesses. Source process nitrification flux documentation uses gN/m3/day.

Predeclared independent numerical gate: identical CF axes/calendars, topology,
units and masks; valid common wet faces; equal initial NH4/NO3/OXY to1e-10 in each
declared unit; max hydrodynamic s1 difference<=1e-10m; final mean NH4 positive-minus-
control <=-1e-4g/m3 and NO3 >=1e-4gN/m3 on final common valid faces, at least10
faces. Report full spatial deltas, OXY sign and extrema, actual process-update
schedule from native diagnostics/source, and positive/control run-manifest hashes.
Thresholds are predeclared experimental discriminators, not accuracy/convergence
claims. Unknown output schema/units, inactive processes, different masks/grids,
nonfinite data, stale artifacts or missing provenance fail/remain unverified.
No production comparator is claimed yet; independent Einstein verifier owns it.

Offline WAQ is a separate gate. Pinned examples/delft3d4/06_delwaq has EColi,
Salinity and IM1, an explicit .inp binary/reference chain and .hyd metadata.
Its hydro range ends1990-08-06T01:00 while input runs to1990-08-15T12:30;
clock reuse/periodicity must be established, never assumed. The .inp directly
names .vol/.flo/.poi/.len/.par/.vdf plus includes; .hyd is not itself a substitute
for quality input. .hyd hydrodynamic-file .dat is absent in that pinned folder;
classify as metadata separately from actually consumed binary files. Source
delwaq_program.F90 performs preprocessor then solver, with source-specific CLI
`delwaq.exe INPUT.inp -p proc_def.dat [-validation_mode] [-threads N] [-output DIR]`.
Installed delwaq.exe help/version/format compatibility has NOT been executed.
Its existence/hash and delwaq.dll existence/hash prove discovery only.
"""

PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
INPUT_SET_SHA256 = "a74cefdc861fbcd5423998e62fe9e9a9fbdce790ba4cc885225af64239c9e329"
VARIABLES = (("mesh2d_NH4", "g/m3"), ("mesh2d_NO3", "gN/m3"),
             ("mesh2d_OXY", "gO2/m3"), ("mesh2d_s1", "m"))
EFFECT_GATE = {"minimum_common_faces": 10, "initial_absolute_tolerance": 1e-10,
               "water_level_absolute_tolerance_m": 1e-10,
               "final_mean_NH4_positive_minus_control_max_g_m3": -1e-4,
               "final_mean_NO3_positive_minus_control_min_gN_m3": 1e-4,
               "mask_policy": "equal; reject mismatch; no fill/interpolation",
               "time_policy": "exact decoded CF schedule and calendars; no synthetic times",
               "topology_policy": "same grid and spatial indices; no index guessing/remap",
               "native_gate": "pending_independent_native_verification"}
