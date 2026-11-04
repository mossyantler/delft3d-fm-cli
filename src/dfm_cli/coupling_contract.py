"""E015 authoring / owned-run contract; native evidence is explicitly scoped.

Public proposed commands (coordinator owns shared CLI registration):
 coupling inspect CONFIG
 coupling validate CONFIG
 coupling profiles
 coupling prepare SPEC --out NEW [--apply --expect-sha256 HASH]
 coupling run CASE --out NEW_RUN --install SUITE --timeout SECONDS [--progress]
 coupling plan CASE --out NEW_PLAN --install SUITE --timeout SECONDS
 plan stages/fingerprints/checks the same graph and selected binaries and writes
 plan.json. It creates no native Job/process, loads no engine DLL and writes no
 active run manifest. A real run requires a separate NEW output and native lease.
Python: coupling.inspect(path), validate(path), prepare(spec,out,apply=False,
expected=None); coupling_run.start(case,out,installation,timeout=45,progress=False).

prepare JSON v1 required keys:
 schema_version:1, name:ASCII ID, profile:one profiles() key,
 source:{root:path relative to SPEC, files:[portable relative files]},
 clock:{reference:ISO UTC Z,start:ISO UTC Z,stop:ISO UTC Z},
 components:[{name,library,working_dir,input_file,process:[0],
              settings:[{key,value}],parameters:[{key,value}]}],
 control:[NODE,...], couplers:[COUPLER,...], patches:[PATCH,...],
 observables:[OBS,...]. Unknown keys are refused.
 NODE={kind:'start',name} or {kind:'coupler',name} or
 {kind:'parallel',children:[NODE,...]} or
 {kind:'start_group',time:{start:number,step:number,stop:number,unit:'s'},
  children:[NODE,...]}. Parallel requires exactly one direct master start; order
 is preserved. This is serial rank0 DIMR time scheduling, not OS/MPI parallelism.
 COUPLER={name,source_component,target_component,
          items:[{source,target,quantity,unit}],logger:{working_dir,output_file}}.
 Scalar item quantity/unit are declared review metadata, not invented XML fields.
 Each source/target address is explicit; XML does not prove kernel availability.
 PATCH={file,section,key,occurrence:positive int,value:ASCII single-line string}.
 Only documented clock/output/wave-mode fields can be patched in MDU/MDW; unknown
 data/comments/repeated fields are preserved by byte splices. Other file changes
 require new explicit source files. Source is never edited. No export/rewrite of
 an existing user project. Explicit inventories avoid copying old outputs/native
 executables; all actual file SHA256s bind preview/apply and later staging.
 Only FM geometry/frictfile is split as a documented semicolon file list. Every
 element is nonempty, individually contained, nonlinked, existing and SHA-bound;
 other native file keys retain their original single-path meaning.
 OBS={component,path,format:'netcdf'|'pi_xml',variable,unit,time_variable,
      interval:{value:positive number,unit:'s'},nonzero:bool,
      sample_semantics?:'inclusive'|'interval_start_hold'}.
 Omitted sample_semantics remains inclusive: every requested sample including
 the terminal instant is mandatory. Old specs/receipts are not normalized or
 rewritten to add this field. interval_start_hold is an explicit opt-in ONLY for
 stationary coupled Waves native wavm NetCDF snapshots (not standalone/Flow/RTC
 or coupler logs). Require start=reference, a single before-master group with
 only that Waves start, group start0/step=observable cadence/stop>=model stop,
 exact divisibility, and MapWriteNetCDF=true/MapWriteInterval=-1. Other phases,
 schedules and outputs are unsupported. Each solve on [start,stop) must appear;
 missing/extra/shifted/terminal samples fail. No terminal sample is fabricated.
 Reports separate observed_time_range from requested_model_interval and explicit
 declared_hold_coverage (stop_exclusive=true, instantaneous snapshots, declared
 scheduled reuse only). This does NOT prove constant physical holding, a CF
 interval mean, convergence, exchange effects or scientific validity. Online FM
 uses method7 time interpolation/extrapolation; neither scheduler nor timestamps
 alone establish the resulting field between solves. Slot21 proves two solves
 at0/3600 for FM0..7200, not a7200 Waves value. No clock/physics changes are made.
 At least one independent numeric/time observable per component is mandatory.
 Coupler logs must additionally appear as observables using component='@coupler'.
 Coupled output agreement/physical influence is separate from time completion.
 FEWS PI XML (RTC): variable is exact locationId/parameterId or id:SERIES_ID;
 time_variable='event_date_time'; root timeZone must explicitly be0, header units
 must match, and all events must cover the declared case clock/cadence. Missing
 or nonfinite PI values fail. Native export paths are outputs, not copied inputs.

Outputs: dimr_config.xml, coupling-spec.json (normalized portable replay spec),
coupling-provenance.json and selected copied inputs with only previewed patches.
Preview writes NOTHING; apply exclusively claims a new folder (including refusing
dangling symlinks), rechecks all fingerprints, and publishes a guarded receipt.
Plans/cases are movable. All source clocks are inspected: FM absolute/relative
clock and TZone/TUnit; Waves reference date and TimePoint values in MINUTES
(wave_bmi get_end_time multiplies by60); RTC settings/runtime period/step. Group
times are seconds of the master's reference clock, not Waves MDW minutes.

Profile distinctions (never infer from an upstream folder name):
 fm: ONE uncoupled FM hydrodynamic control, separate from processes/Waves.
 fm_processes: ONE FM component, SubstanceFile + DtProcesses. Pinned example03
 is in-kernel WAQ processes, NOT a second DIMR WAQ or offline postprocessing run.
 Component settings/parameters serialize as key/value XML attributes. FM
 processlibrary must be a pre-initialize setting naming an explicit staged .dat
 with its matching .def. Both files are required, fingerprinted input resources;
 ambient PROC_DEF_DIR/${...}/percent substitution is never performed.
 waves: ONE wave library, pinned07 standalone stationary Waves.
 fm_waves: FM + wave, pinned08 startGroup; no DIMR scalar couplers required.
 fm_rtc_waves: FM + FBCTools_BMI + wave, pinned10 flow2rtc/rtc2flow scalar items.
 fm_rtc: separate bounded FM+FBCTools_BMI derivative WITHOUT Waves. Reference=start,
 <=600s, serialrank0, cold2D with Waves/processes disabled, matched FM/RTC clocks,
 explicit finite RTC input state and numeric modern locationFile weir initial
 crest. Group is FM_to_RTC -> RTC -> RTC_to_FM before FM, with native RTC step.
 Both scalar directions need format='dimr_logger', time_variable='time_offset',
 variable='item1_values', sample_semantics='exchange_before_master' and explicit
 source-backed unit. The pinned DIMR logger has a known hardcoded1980 CF label
 and no scalar units. This SPECIAL reader verifies raw metadata/source->target,
 uses the explicitly declared FM reference offsets and [start,stop) group times,
 and reports the raw metadata separately. It never changes generic CF parsing,
 fabricates a terminal sample, rewrites outputs or claims physical influence.
 Live RTC requires limitedMemory=true: false reruns the complete horizon on every
 BMI update and cannot rewind its rolling state. The unstarred before-FM input
 writes slot n; lookup ref=EXPLICIT reads that received slot and computes n+1.
 Native PI export is unavailable in this incremental mode. format='rtc_csv',
 variable=the actual output scalar, time_variable='date time' checks native CSV
 output inclusive through the unchanged stop. Every native scalar and active
 flag is checked; received input covers [start,stop), terminal input is retained
 as raw null/value without claiming a terminal transfer. Native final CSV omits
 the active flag. Units and UTC come explicitly from the validated case, since
 CSV encodes neither. No PI output is synthesized. FM CF remains inclusive.
 The bounded official10 pair passed live exchange/causal hydraulics and natural
 owned completion in RTC-G-exchange-01 (#68), independently repeated in #67.
 Each case has10 transfers0:60:540 -> actual next-step crest60:60:600. The native
 CSV records receipt and output; the scalar logger alone does not prove receipt.
 Final signed q1 on50 topology-matched links, oriented Upstream to Downstream,
 is63011.093017578125m3/s control and58631.78076171875m3/s changed. The changed
 final crest is+0.31801366806030273m and Downstream level-0.10158085823059082m.
 Both final hydraulic checkpoints match2500s1/4950q1 by physical/topology join
 and exact projection to actual map float32 storage;150 map-only closed edges
 remain actual zeros. Raw weir-history discharge masks4/11 and5/11 stay missing.
 Live gate=passed; saved_actuator_restorability_gate=not_established; overall
 evidence=partial. Legacy34-variable restart has no saved crest/actuator field.
 Live history crest and hydraulic checkpoint success do not qualify actuator
 persistence, restart restore, calibration, general models or RTC cancellation.
 New helpers coupling_rtc.inspect(work), lookup_value(review,x),
 coupling_rr.inspect(config) perform read-only source-backed reviews. RR review
 keeps component-clock mismatches, populated actual graph and unresolved optional
 FNM slots explicit; it NEVER declares native readiness or invents missing inputs.
 fm_rr: FM + rr_dll with explicit scalar couplers; HYDROLIB c11 reference is1D.
 fm_waq_offline: FM hydrodynamic EXPORT then independent WAQ. Kept a distinct
 unsupported native profile until a concrete WAQ consumer/file contract is given.

RR-local sobek_3b.log scanning applies only to staged rr_dll components. Native RR
 ERROR/FATAL cause carries component/path/line/context/SHA256 and takes primary
 attribution; controller_primary_error retains the propagated DIMR cause.
 Warnings stay separate; the FM initialization marker is preserved. The scanner
 is bounded to32MiB/32entries/1024characters and fails completion closed if a
 present log cannot be completely read. Historical manifests/logs are never
 rewritten by collection. Component diagnostic errors do not alone identify
 which RR simulation phase failed.
Owned-run integration: coupling_run builds a runs.Run subclass and calls the
EXISTING runs.execute_native, runs.fail, Run.save/terminate and Windows Job Object
launch/monitor/cancel implementation. It does not implement a second process
runner or PID killing. Its stage and component verification callbacks are exposed
for coordinator use. Existing runs.py/run_control.py/cli.py are untouched here.
All component DLLs plus DIMR executable are discovered/fingerprinted from the
selected installation; no CWD DLLs or arbitrary library paths are accepted.
Raw native logs, partial artifacts and per-component checks are retained on all
terminal paths. Zero exit, a new output file, XML validity, DLL presence, and
scheduled calls are each insufficient for physical/coupling validation.
Native execution happens ONLY when the coordinator allocates a slot. Every
profile reports separate launchable eligibility and evidence; native_gate is
attained evidence, never the condition for permitting launch. The pinned07 fresh
forcing pair E015-G-waves-final-01 is fixture_verified; cancellation, coupled
exchange and broader Waves models remain pending. Other experimental profiles
remain pending until their standalone/coupled independent observable
tests, real final-time checks, failure/timeout/cancel and isolation cases pass.
The separately published fm_rtc official10 fixture has the live/causal/hydraulic
checkpoint scope above; saved actuator restore and forced-stop scopes stay pending.

Evidence: pinned Delft3D commit5a4649830b1e5072caf019fb4850bbdefd9ad431;
examples/dflowfm/{03_dflowfm_dwaq_sequential,07_dwaves,
08_dflowfm_sequential_dwaves,10_dflowfm_sequential_drtc_dwaves}/dimr_config.xml,
materialized source receipt E015-coordinator-source-01 (149files). DIMR UM §2.2.5,
§2.2.6, §2.3.3 and §2.4; wave/packages/wave/src/wave_bmi.f90:182-225.
Installed suite version and exact binary/source commits remain separate evidence.
"""
