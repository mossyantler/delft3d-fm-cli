"""WAQ-offline v1, fixed pinned06 consumer with scoped native profile evidence.

Additive command group waq-offline via register(groups)/execute(args) in workflow:
 review HYD INP [--install SUITE]          (legacy textual review + binary graph)
 prepare SPEC --out NEW --process-library DAT [--apply --expect-sha256 HASH]
 inspect CASE                            (strict prepared input graph guard)
 run CASE --out NEW --install SUITE [--timeout 60] [--apply --expect-sha256 HASH]
 preprocess CASE ...                     (same owned backend, validation_mode)
 compare POSITIVE_RUN CONTROL_RUN         (re-read manifests, raw map/his fields)
 status RUN / cancel RUN                  (existing live-owner control protocol)

Use dfm waq-offline ... (or python -B -m dfm_cli.water_quality_offline_workflow).
Existing water-quality 03 commands/inputs stay frozen.
Public prepare/guard/review_graph are in inputs; read_output/read_series in binary;
plan/start in run and compare in compare. Preview writes nothing. Apply needs matching fingerprint,
fresh path and contained fixed inputs. Public API has no coordinator token: native
serialization is an external research lease, not a product authorization mechanism.
Review, preparation and plan never execute the selected invocation. Native
profile evidence below is separate from that invocation's completion verdict.

Scope: exact28-file examples/delft3d4/06_delwaq Git blobs at PIN, regular private
copies only. .inp directly consumes9 references incl .are and .stt; .hyd is metadata
and its absent origin.dat is never synthesized. Stage original full source graph,
NEFIS process data pair, immutable original INP and provenance. Prepared INP has
explicit common dt60s, monitor/map/history300s, duration600..3600s divisible300,
start1990-08-05T12:30:00, within unchanged hydro45000..90000s relative to
1990-08-05T00:00:00. Source timezone/CRS/datum remain unencoded/unverified.
Actual hydro51records/900s, quality1130segments, exchanges1130+1020+904=3054.
Input graph checks record sizes, finite data, strict time order and coverage,
pointer bounds, .len count3054, .par static time0 and fixed two parameters.
No interpolation, hydro cropping/rewriting, periodic extension or binary repair.

A/B only physical difference: INP RcMrtEColi=.8/day vs0/day. BOTH append explicit
common TcMrtEColi=1.07 and CTMrtEColi=2. INP Temp18, outfall/transport and UV/salt
mortality retained. coli_03.sub is retained unit/source documentation, not the
consumed parameter file. EColi concentration MPN/m3, MrtToEColi1/day. bacmrt.f90
MORT=(RcMrtEColi+SPMRTZ*CL)*Tc**(Temp-20)+MRTRAD above critical temperature;
expected A-B mortality delta .8*1.07**(-2), not zero total control mortality.

Output supported reader: Windows little-endian int32/float32 STREAM .map/.his,
4x40title bytes, int32nvar/nloc, nvarx20names; HIS adds(nlocx(int32id+20name)).
Then int32time + float32(nvar*nloc) per record, variable-fastest/Fortran order.
Require native T0/reference+1s scale, exact inclusive300s output times, EColi,
Salinity, IM1, MrtToEColi names, valid finite data, matching masks (-999 source
sentinel), map1130segments/history20stations. Units come from retained original
substance/process definitions; binary format has no units field. Never invent CF
units/time or rewrite raw outputs. Raw output hash plus source units is retained.

Observed native49:26 MAP/HIS columns, including daily_EColi at ordinals13/14/15.
Pinned STT STADAY suffix daily and setday.f90 generate equal names for periodic
average/minimum/maximum. Reader preserves every fixed20-byte name, order and
occurrence: variables is the unchanged name list; columns includes zero-based
ordinal, one-based occurrence, raw_name_20 and raw_name_hex. column_summary is
ordinal-aligned. With keep_values=True, column_records[time][ordinal][location]
contains EVERY original column; records[time][name] and summary[name] are explicit
unique-name views only. No renamed, merged or silently selected statistic columns.
Duplicate physical target names (including case variants) always fail. Native49
failed manifests remain untouched; successful re-read is not a new native run or
acceptance of its failed producer record.

Runner: existing runs.Run/execute_native/fail + private Windows Job assigned
before resume; closed stdin/unrelated handles; private cwd/TEMP/TMP; bounded
timeout; normal run_control status/cancel; no native kill by name/recorded PID.
Exact source-backed argv is delwaq.exe INPUT.inp -p process_library/proc_def.dat
-threads1 (two argv tokens); preprocessing adds -validation_mode. Installed bat
selects lib/bin PATH and input cwd. Independent slot51 and coordinator G verified
preprocessing and the paired 3600s consumer on 2026.02 OpenHMWQ with this argv;
missing executable/DLL/database yields diagnostic, never a success substitute.
No batch wrapper, service, global observer or GUI. Validation-only native call
writes compiled files. Success requires zero native exit, diagnostics, unchanged
inputs, complete binary output time axes and empty private Job; initialization,
preprocess completion, simulation and scientific influence remain distinct.

Comparison requires completed retained runs, input/executable/data/argv provenance,
same paired recipe except RcMrtEColi, rehashed raw outputs, same axes/names/locations
and masks, equal initial EColi, matched Salinity/IM1, lower final positive EColi,
and native MrtToEColi difference within predeclared float32 tolerances at every
active sample after the initial output. Initial rate is reported separately from
scheduled reaction. MAP concentration and volume-weighted EColi inventory must be
lower in the positive case; history stations may miss the plume, so their EColi
response is diagnostic. Raw volumes are linearly interpolated under source -2
semantics for inventory analysis only; no input/output data is rewritten. MON/BAL
files remain raw retained artifacts; their ledger/rounding/mass closure is a
separate gate. This establishes neither calibration nor general model support.

Accepted profile evidence: WAQ-offline-V-slot51-20261104-195742-ebd15791 and
WAQ-G-offline-consumer-01 independently completed preprocessing/control/positive,
read all 26 ordinal columns (including repeated non-target statistics), checked
13 native map/history samples and source rate/units, matched transport and
initial fields, and detected lower positive EColi concentration and V*C inventory.
MON inventory agrees with independently integrated raw volumes/concentrations;
this is not a complete reaction/boundary/source flux ledger closure. Evidence
does not validate a newly selected installation, process library or invocation,
other durations/timesteps, general cancellation/timeout, or all input grammars.

Separate opt-in lifecycle spec schema2: profile=pinned06-lifecycle-dt1-v1 and
purpose=lifecycle_stress_only. Exactly3600s, same local45000..48600 clock,
300s outputs/13samples, same pinned source/chemistry recipe; solver step1s
(ddhhmmss00000001). Lifecycle receipt schema2/kind and timer/counter audit bind
every native token and input hash. Expected3600 regular intervals versus60 at
dt60; native initialization/final evaluations and wall-clock duration are not
inferred from this intent. Prepare/inspect/plan never execute a selected case.
Natural completion (#65), independent active cancel/timeout (#66) and coordinator
G (#70) verified this lifecycle fixture. Each forced stop had an owned live
same-executable peer that survived and completed the full13-sample clock.
Completed controls reported3601 process evaluations and3600 advances. Neither
graceful finalization nor retained chemistry/continuation state is established by
a forced stop; a new invocation still needs its own verification. Chemistry
compare explicitly refuses these cases. Lifecycle evidence and its retained
artifact hashes are in water_quality_offline_lifecycle.LIFECYCLE_EVIDENCE.
No existing schema1 spec gains a new timestep or different semantics.

Primary basis: PIN/waq_kernel/results/write_binary_output.f90, waq_precision.f90,
waq_process/bacmrt.f90, example06 comments and delwaq_exe source CLI/program.
Online D-Water Quality UM A.2/B and Input File Description A.2 corroborate stream
layouts/INCLUDE/-2 binary interpolation. Online manuals currently report2027.01,
not the installed2026.02 source revision; they are not binary compatibility proof.
"""
PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
SOURCE_DIGEST = "a62741ee093a0c4295be0ca431c550ba6706d7d78b2e4742ca76e3ab8fd147ef"
STEM = "com-tut_fti_waq"
NSEG, NEXCH = 1130, 3054
REFERENCE = "1990-08-05T00:00:00"
START = "1990-08-05T12:30:00"
UNITS = {"EColi": "MPN/m3", "Salinity": "g/kg", "IM1": "gDM/m3", "MrtToEColi": "1/d"}
PROFILE_GATE = "verified_pinned06_consumer_profile"
PROFILE_EVIDENCE = {
    "state": PROFILE_GATE,
    "basis": "independent native replay and coordinator G; not execution of this invocation",
    "experiments": ["WAQ-offline-V-slot51-20261104-195742-ebd15791", "WAQ-G-offline-consumer-01"],
    "source_commit": PIN, "source_sha256": SOURCE_DIGEST,
    "suite_observed": "2026.02 OpenHMWQ; installed source commit not inferred",
    "recorded_native_sha256": {
        "bin/delwaq.exe": "416d74a8185a55e56afbe7b53b1fbcb6806bbb05412d885b9d7cfde83cd2329e",
        "lib/delwaq.dll": "894183103e5f28b99c2f38a9a38c9f1dcd3bbfec24bc35c16dd24198296c79c4",
        "bin/run_delwaq.bat": "aeaef1595c1e5e6ab95aed51cd9333905a71d93bf21968a3c7ecb5f5c57e84da",
    },
    "recorded_process_library_sha256": {
        "proc_def.dat": "3771d49f388b9f7c71f1b481989bb562b061ae0c2e35181bf6b09a085e323a8c",
        "proc_def.def": "254f65225908b01e0b90623bff4a0429a8b9ce092554265a1c6f8367f5f68e5c",
    },
    "clock": {"start_tick": 45000, "stop_tick": 48600, "time_step_seconds": 60,
              "output_interval_seconds": 300, "timezone": "not_encoded_in_source"},
    "verified_scope": ["preprocessing and positive/control consumer completion",
                       "native map1130/history20: 26 ordinal columns and 13 samples",
                       "source-bound units and mortality rate; matched initial and transport fields",
                       "EColi concentration and volume-weighted inventory response; MON inventory crosscheck"],
    "limits": ["Selected invocation, backend and library are not verified by this evidence annotation",
               "Other supported preparation durations have not received this native physics gate",
               "No general lifecycle, complete flux-ledger closure or scientific calibration claim"],
}
EFFECT = {"mortality_delta_per_day": .8 * 1.07 ** -2, "mortality_atol_per_day": 2e-5,
          "mortality_rtol": 2e-5, "transport_atol": 2e-5, "transport_rtol": 2e-6,
          "initial_EColi_atol": 1e-6, "minimum_final_EColi_delta": 1e-3,
          "mask_policy": "equal; sentinel -999 only; reject NaN/Inf and mismatches",
          "native_gate": PROFILE_GATE}


def effect_policy_matches(value):
    """Accept the exact v1 policy, including its historical evidence annotation.

    Historical receipts are hashed as written, never migrated or rewritten. Only
    this former status string is compatible; all other fields remain exact.
    """
    if value == EFFECT:
        return True
    historical = dict(EFFECT, native_gate="pending_independent_native_replay")
    return value == historical
