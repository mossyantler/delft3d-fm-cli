# Delft3D FM CLI

An AI-friendly command-line interface for creating, inspecting, editing, validating,
and running Delft3D Flexible Mesh models.

See the [implementation roadmap (한국어)](ROADMAP.md) and [GUI/console workflow table](research/notes/collection/gui-workflows.md) for each operation’s files, engine entry point, CLI command and evidence.

The working version is **0.4.0.dev1**, with JSON protocol **2** and run manifest **3**. The [delivery graph](DELIVERY.md) distinguishes work under review from accepted workflows. See the [0.3.1 performance measurements](research/notes/verification/cli-scale-031.md) and the [0.3 protocol migration examples](research/notes/verification/cli-03.md).

The application is implemented in Python: installation discovery,
model/dependency inspection, preserved setting edits, partial validation, and
bounded serial direct-FM or single-component DIMR runs with output-time checks.
It was verified on the copied f34 fixture with **2026.02 OpenHMWQ**. Broader model
formats, versions and execution modes remain separate work.

## Install and discover commands

Python 3.12 or newer. From this folder in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[run]'
.venv/Scripts/dfm.exe schema inspect
.venv/Scripts/dfm.exe install discover
.venv/Scripts/dfm.exe install inspect --install '<suite installation root>'
```

The `run` extra installs the NetCDF reader needed to verify completed runs. For
inspection/editing alone, install with `pip install -e .`. Both the `dfm` entry
point and `python -m dfm_cli` work. Ordinary commands return one JSON object. Interactive `bmi session` emits JSONL replies before its final result; native logs
are separate files. `--help` and `--version` produce human-readable text.

## Inspect, preview and apply

For a source or intake–outfall pair, use `dfm source inspect MODEL.mdu`.
`source forcing-create` writes a fresh BC; `source set` links an existing source
to it, and `source add` adds an explicit source to new EXT. Each write has its
own preview and `result.sha256`. See the [worked input recipe](examples/source_sink/README.md)
and [six 120-second comparisons](research/notes/verification/source-sink.md#public-225).
Writing currently covers inline one/two-point XY, 2D UTC, zero momentum area,
and linear discharge/salinityDelta BCs. These commands edit inputs. Run such a model with
`dfm run start MODEL.mdu --profile source-sink --route direct|dimr --install '<suite root>' --out NEW --timeout 120`;
[four installed runs](research/notes/verification/source-sink.md#public-run) matched #225 exactly. GUI export
equivalence remains separate work.

To see what a 2D model prescribes at a boundary **before running it**, use
`dfm boundary preview f34.mdu --boundary L1 --signals all`. Add `--point`,
one or more `--time` arguments, and an explicit UTC `--time-unit` to sample
an authored signal. The response distinguishes original data, interpolation
and missing supports. In the native comparison, two changing inputs differed from
the solver’s boundary array immediately after initialization. See the [f34 command and measured examples](research/notes/verification/boundary-preview.md). In [eight short follow-up cases](research/notes/verification/boundary-preview.md#native-221), all 704 boundary-element reads matched the authored signal evaluated at the later of the actual clock and `DtInit`. The CLI still samples the user's requested time.

For a layered salinity boundary, [this three-layer example](examples/layers/vertical-cell.json)
reproduces the [20-second cell-edit comparison](research/notes/verification/layers.md#b13).
Create it in a new folder. The edit below changes only the final sample at the
first west support, 40% of the distance from bed to surface:

```powershell
dfm layers create examples/layers/vertical-cell.json --out layers-case
$point = @('layers-case/model.mdu', '--boundary', 'west', '--point', 'west_0001', '--quantity', 'salinitybnd')
dfm boundary vertical-inspect @point
$cell = @('--time', '20', '--time-unit', 'seconds since 2001-01-01 00:00:00 +00:00', '--position', '0.4', '--position-type', 'percBed', '--value', '22', '--unit', 'ppt')
$preview = dfm boundary vertical-set @point @cell | ConvertFrom-Json
if ($preview.ok) { dfm boundary vertical-set @point @cell --apply --expect-sha256 $preview.result.input_sha256 }
dfm run start layers-case/model.mdu --route direct --profile layers --install '<suite root>' --out layers-run
```

Use the time and position tokens exactly as written in the BC. The position
identifies an input value column via its `VertPositionIndex`; it is not a
computational layer number. Inspection and editing do not start the solver.

To inspect or change an existing 2D weir crest time series, use `dfm weir series-inspect`, `series-export` or `series-import`. The [worked PowerShell example](examples/weir_series/README.md) maps CSV seconds to TIM minutes and restores the original 11 inputs. Import edits height tokens at existing times; it cannot insert knots or turn a constant crest into a TIM. Simulation-time crest values and the GUI CSV format have separate checks. Run the 48-cell example with `dfm run start model.mdu --out NEW --route direct --profile weir-series --timeout 120`. [Four installed runs](research/notes/verification/weir-crest-series.md#public-run) matched their respective 120 s references, including both restarts.

To change an existing two-breakpoint Smith & Banke wind drag table (`[wind] ICdtyp=2`), use `dfm wind drag-inspect` and `dfm wind drag-set` (preview, then `--apply --expect-sha256`). Only the selected coefficient or speed tokens change. See the [worked example](examples/wind_drag/README.md). [Seven installed runs](research/notes/verification/wind-drag.md) gave the predicted wind stress for each coefficient.

For an existing 2D pump, `dfm pump inspect MODEL.mdu --id transfer_pump`
reads the declared capacity, orientation, and ordered XY vertices from the
referenced structure and PLI files. Omit `--id` to list the supported pumps.
This read-only command covers modern scalar, non-staged pumps and requires an
explicit path mode. A reported orientation is an input value; the command does
not infer a geographic discharge direction or start the solver. See the
[pump measurements and input limits](research/notes/verification/pump-orientation.md).

To edit a pump and run the example, start with a fresh copy of the
[six input files](examples/pump/model.mdu). These commands change the declared
orientation in `structures.ini`; they preserve the pump line and the capacity.

```powershell
Copy-Item -LiteralPath examples/pump -Destination pump-case -Recurse  # new directory
$mdu = 'pump-case/model.mdu'
$p = dfm pump set $mdu --id transfer_pump --orientation negative | ConvertFrom-Json
if ($p.ok) { dfm pump set $mdu --id transfer_pump --orientation negative --apply --expect-sha256 $p.result.sha256 }
dfm run start $mdu --profile pump-scalar --route direct --install '<suite root>' --out pump-run
dfm run status pump-run
```

Use `--capacity-m3-s=-1` instead of `--orientation negative` to change capacity
alone. A preview binds one request to its input files. **Editing and running have
different limits:** the run profile accepts one scalar pump in a closed 120 × 40 m
basin on the verified 12 × 1 or 12 × 4 grid, for at most 120 seconds. In the
four-link example, a declared capacity of +1 moved 4 m³/s east; changing
orientation alone moved 4 m³/s west. See [the five installed runs and their
manual controls](research/notes/verification/pump-orientation.md#public-pump).

```powershell
$dfm = Join-Path (Get-Location) '.venv/Scripts/dfm.exe'
$modelPath = 'C:/models/copied-case/flow.mdu'
& $dfm model inspect $modelPath
& $dfm model validate $modelPath
$preview = & $dfm model set $modelPath output/hisinterval 60 | ConvertFrom-Json
$preview.result.diff
& $dfm model set $modelPath output/hisinterval 60 --apply --expect-sha256 $preview.result.before_sha256
```

The default is preview. Applying requires its input hash to detect a stale
preview. Only an existing value token is replaced; unrelated bytes, comments,
newlines, unknown fields and numeric precision remain intact. `model set` accepts
positive single-value history/map intervals, a scalar restart interval, and an
absolute stop time later than the explicit start. Use `dfm schema inspect` for
the exact addresses and constraints. Repeated target keys and interval windows
are refused.

Two existing output switches also accept a literal `0` or `1`. For example,
`dfm model set MODEL.mdu output/Wrishp_obs 1` previews a request for snapped
observation shapefiles; `dfm model set MODEL.mdu output/Wrihis_balance 0`
previews omitting the model-wide water-balance series from history. Applying
uses the same MDU hash as the example above. Neither command runs FM.
See [the f34 file and variable comparisons](research/notes/verification/output-toggles.md).

`model fields MDU` lists the actual occurrences, byte spans and field provenance; optional `--section` and `--key` filter them. `model field-set MDU SECTION/KEY VALUE --unit UNIT` previews a bounded initial water level, Manning coefficient or maximum timestep change. Unlike `model set`, apply requires the fingerprint of the entire input graph. See the [field commands and limits](research/notes/verification/fields.md).

For an AI caller, `editor_available` only means that the CLI has an editor for the address. Check `edit_eligibility.state`: `blocked` includes the MDU reasons; `requires_preview` means the references and candidate still need validation. Text inspection leaves `editable` false. Successful `field-set` preview returns `evidence.edit_support = "preview_validated"` and the input hash needed to apply.

For the accepted 2D workflow see [M1–M3 commands and evidence](research/notes/verification/roadmap-2d.md). `boundary inspect` follows new EXT, PLI and BC files; `boundary set` previews or applies one existing harmonic water-level amplitude. `model create SPEC --out NEW` authors a relocatable 2D model from explicit JSON and a supplied UGRID mesh. These are separate from the limited `model validate` checks below. Creation and results require the `run` extra.

Use [`boundary series-inspect` and `boundary series-set`](research/notes/verification/boundary-series.md) to read a linear water-level series or edit multiple existing values at one support point. The request names its exact time unit and origin; times, units, other support points and comments are preserved. Preview first, then apply using the request-bound `input_sha256`.

For all active supports on one line, `dfm boundary coefficients MODEL.mdu --boundary east --quantity waterlevelbnd` reads the existing scale and offset. Preview `--factor 2` or `--offset 0.125 --unit m`, then apply using the preview’s `input_sha256`. The raw time/value rows stay unchanged. See [B11 controls and limits](research/notes/verification/boundary-coefficients.md).

`dfm observation inspect MODEL.mdu` follows `ObsFile` and lists the names, raw coordinates and byte spans in the XYN file. To move one point, preview `dfm observation move MODEL.mdu --id centre --x 500025.0 --y 5700015.0 --crs EPSG:32631 --unit m`; use `observation add` for a new name. Apply the same request with `--apply --expect-sha256 HASH` using the preview's `input_sha256`. These edits require the `geo` extra and a point strictly inside one supported mesh face. The CLI writes the supplied coordinates in the mesh CRS. See the [file and engine checks](research/notes/verification/observation-points.md) for the difference between an input coordinate and the cell sampled in history.

To copy just the named stations, use `observation export MODEL.mdu --out NEW.xyn`. To bring a survey into an existing model, use `observation import MODEL.mdu --source INPUT.xyn --mode append --crs EPSG:32631 --unit m`; `replace-all` also removes stations absent from the source. For a discharge section use `section inspect MODEL.mdu` or `section reverse MODEL.mdu --id Entrance`. Preview first and apply the same request with its `input_sha256`. See [worked commands and matched engine outputs](research/notes/verification/spatial-transfer.md). A point inside the input mesh may be inactive in a run: in the dry-area control its name remained in history while all 13 water levels were missing.

After a run, `dfm results stations RUN` reads the actual station IDs, finite/missing sample counts and supporting mesh/shape records. `assignment.state = unknown` means the recorded evidence does not establish one cell. A station with 13 missing values still differs from an absent station. The [installed command checks](research/notes/verification/spatial-transfer.md) need the `run` extra; GUI prediction is outside this command.

`model validate` reports which FM `Program` declaration it found. `run start` rejects missing, ambiguous or unrecognized identities before creating a run folder. Modern and legacy MDUs use different sections; [the source and installed-engine checks](research/notes/verification/fm-model-identity.md) explain how they are selected.

To change which timestamps exist, use `dfm boundary series-rows MODEL.mdu --point east_0001 --rows rows.json`.
The JSON request supplies the existing time unit (including its origin), the value unit, and both arrays:
`"insert": [{"time":"30","value":"0.20"}]` and `"delete": []`, for example. Each new timestamp needs its own value.
Preview checks that the remaining rows still cover the model period. Apply the same request with
`--apply --expect-sha256` and the preview's `result.input_sha256`. Deleting a row that carries a comment is refused.

To import a whole set of linear water-level signals for one boundary, preview `dfm boundary import MODEL.mdu --boundary east --source new.bc --format bc --mode replace`. CSV uses `--format csv --mapping mapping.json`. Inspect the per-support actions before applying the preview hash: `extend` fills empty points, and `overwrite-all` clears existing signals absent from the source on that boundary. The [mode comparison and example mapping](research/notes/verification/boundary-import.md) show exactly which point changes. Check `native_compatibility`: this editor preserves an existing BC BOM, which the observed 2026.02 FM engine rejects.

For a standalone collection of the boundary positions and signals, preview `dfm boundary export MODEL.mdu --out NEW --group-by quantity`. Inspect the listed source blocks and files, then repeat with `--apply --expect-sha256 <input_sha256>`. The other groupings are `all`, `boundary` and `process` (requires a declared process map). This leaves the source model's EXT unchanged. See the [file and 3D run comparisons](research/notes/verification/boundary-export.md).

To import an XY polyline into a new copy, preview `dfm boundary location-import MODEL.mdu --source survey.pli --out NEW --coordinates as-is`. A new line is stored without an engine binding. Replacing a matching filename and internal line name **clears its attached forcing across quantities**. Inspect the removed blocks and disconnected EXT references before applying the preview hash. The [as-is checks and worked example](research/notes/verification/boundary-locations.md) show which files and results change.

For one existing water-level line, `boundary support` enables or disables a single point; `boundary function-set` replaces the function and signals at every active point on that line. Each operation previews the exact signal data it will retire. See the [commands and eight manual/CLI runs](research/notes/verification/boundary-support.md).

For horizontal conversion, install `pip install -e '.[geo]'` and select `--coordinates transform` with all four flags: for example `--source-crs EPSG:4326 --source-unit degree --target-crs EPSG:32631 --target-unit m`. The target must agree with the actual mesh metadata. The original PLI is archived; Z coordinates and vertical datum changes are unsupported.

Set the existing scalar restart cadence with `model set MODEL.mdu output/rstinterval SECONDS`. For [configured checkpoint verification](research/notes/verification/checkpoint-schedule.md) use `run start --restart-policy configured` on the short cold serial profile. It compares all actual checkpoint times with the MDU; a zero interval requests no checkpoint. The default still requires a final restart.

```powershell
dfm results inspect <run-folder>
dfm results series <run-folder> --variable waterlevel --station W1 --csv new-series.csv
dfm results compare <baseline-run> <changed-run> --variable waterlevel --station W1
dfm results map <f34-map.nc> --variable s1 --time-index 10 --csv new-map.csv
```

Compare computes changed minus baseline using matching station IDs, coordinates, units and decoded times. Missing values remain null. Map selection uses the variable’s actual face, link or node location; supported variable names depend on the output format.

To supply a grid for the [channel model spec](examples/channel/model.json), preview `dfm mesh build examples/channel/mesh.json --out NEW_GRID` and repeat with `--apply --expect-sha256 HASH` from the preview. Point a **copy** of the model spec’s `mesh.path` at the generated NetCDF and keep its reference system, vertical datum, initial water level and Manning coefficient consistent with the mesh spec. The [mesh and native field checks](research/notes/verification/roadmap-2d.md) cover a projected synthetic channel including local refinement.

Validation covers UTF-8/ASCII syntax, selected input references, and limited time
and interval checks. BC/PLI/mesh contents remain opaque. A passed check is not
complete native or scientific validation; the JSON states the performed levels.
Unknown nonempty file references and legacy EXT are reported as unsupported.

For standalone observation sections, preview `dfm section export MODEL.mdu --all --out NEW.pli`
to copy the whole existing CrsFile, or use repeated `--id 'Full name'` arguments
to copy selected sections in source-file order. Apply the identical request with
`--apply --expect-sha256 HASH` using the preview's `result.input_sha256`.
`section import` requires an external `--source FILE.pli`, selection, an explicit
`--mode append|replace-matching`, and `--coordinates model-xy-as-is`. Append
refuses name collisions; replacement keeps matching destination slots and other
sections. The coordinate assertion performs no CRS or unit conversion.
See the [file-only example](examples/section_transfer/README.md) for exact names,
comments, no-op imports and stale previews. These file operations do not establish
native results or GUI standalone import/export equivalence.

For structures, `dfm structure inspect MODEL.mdu` is read-only and lists every structure with its scope row. `dfm structure export MODEL.mdu --all --representation geometry|hydraulic-bundle --out NEW_DIR` (or repeated `--id`) copies raw route geometry or a hydraulic bundle into a fresh directory, and `dfm structure import MODEL.mdu --source DIR --representation ... --id ID --mode append|replace-matching --coordinates model-xy-as-is --xy-unit m` brings one structure back; hydraulic bundles also need `--height-unit`, `--vertical-datum`, `--target-structure-file` and an `--asset-map`. Each of export and import previews first and applies only with `--apply --expect-sha256 HASH` from the preview. Writes cover only the planar weir (scalar or TIM crest, W2D) and the scalar pump (P2D); the other scope rows are reported by `structure inspect` as deferred or unsupported and are never written. These are file operations; they establish no native-engine or GUI result.

## Run and read status

Prepare a copied model with an explicit UTC interval of **at most 600 seconds**.
For authored cold 2D water-level models, `run start --profile extended` explicitly opts into a different, resource-bounded profile. See [the verified 1,200-second case](research/notes/verification/roadmap-2d.md). The engine progress row, controller wall time, and NetCDF-verified final time are separate fields; absent progress is unknown. Use `schema inspect` for limits.
The first run profile requires `Kmx=0`, cold start, disabled Waves/trachytopes,
new EXT Boundary/Meteo, and scalar history/map intervals that divide the duration
and are multiples of positive `DtUser` (minimum interval one second). Critical
profile settings must be explicit. External/absolute input paths, custom output
schedules and split outputs are unsupported. The input files must resolve within
the MDU directory, respecting `PathsRelativeToParent`.

```powershell
& $dfm run start $modelPath --install '<suite installation root>' --route direct --out 'C:/runs/case-direct' --timeout 45 --progress
& $dfm run start $modelPath --install '<suite installation root>' --route dimr --out 'C:/runs/case-dimr' --timeout 45
& $dfm run status 'C:/runs/case-direct'
```

While `run start` is active, request cancellation from another terminal:

```powershell
& $dfm run cancel 'C:/runs/case-direct' --wait 10
```

Run folders must be new and outside the input model directory. The CLI copies
the supported input graph and starts an owned synchronous subprocess with an
explicit child environment. It retains `manifest.json`, stdout/stderr, generated
inputs and outputs. The manifest includes input fingerprints, selected binary/DLL
hashes, argument array, working directory, environment overrides, state, and output
verification. `--progress` emits JSONL state changes on stderr.

Completion requires serial completion diagnostics and CF time checks on history,
map and final restart datasets. Exit code zero alone is insufficient. Model time
is decoded using output units/calendar, independently of the computer's clock.
Warnings remain visible, including the baseline's unresolved projection
diagnostic. Physical validity and CRS correctness are not established by this check.

Each native process starts suspended, joins a private Windows Job Object, then
resumes with stdin closed. Timeout and cancellation terminate that job, including
its descendants. Exit confirmation uses retained member handles and an empty job
membership list. No process-name kill or arbitrary recorded-PID kill is used.

For the default `short` profile, completion also requires the original retained
members' exit evidence, original Job accounting, the actual Job close and collector
close before publishing the terminal manifest. Missing or contradictory closure
evidence yields `cleanup_failed`. A storage failure does not repeat the native
stop/close. [The twelve-case direct/DIMR replay and independent raw readback](research/notes/verification/serial-close.md#native231)
cover the copied f34 600-second fixture and route equality of 191 variables.

`run cancel` checks the controller PID and creation time, writes a request matching
the run ID, and optionally waits 0..30 seconds. The live controller performs the
forced stop. `cancellation_applied=false` means the command has not observed a
cancelled terminal state; a written request alone does not establish termination.
Native `run start` exits 5 for cancellation or timeout; the request command exits
0 when the request is written. Check `owner_acknowledged`, `tree_termination_confirmed` and `cancellation_applied` separately; a concurrent natural completion can win.

`failed`, `timed_out`, `cancelled` and `interrupted` retain diagnostics, primary
error context, native exit code and best-effort partial output inventories/time
axes. Unconfirmed tree cleanup is `cleanup_failed`, not a confirmed stop. Partial
NetCDF can be incomplete/unreadable and is never accepted as a completed run.

`run status` reads the saved manifest and makes point-in-time PID/creation-time
checks for active records. If the controller disappeared, it reports effective
state `owner_lost` and preserves the unfinished record. It does not repair that
manifest or reverify later output changes. Access denial gives `observations.owner=unavailable` and `effective_state=unknown`. Historical manifest v1/v2 is readable without rewriting; cancellation requires a matching v3 record. There is no daemon or resume command.
Native timeout, cancellation, owner loss and unrelated-run isolation are verified
for the serial fixture in [E009/E011](research/notes/verification/failure-cancellation-experiment.md).
[E012](research/notes/verification/parallel-trial.md) separately verified owned cancellation for one local two-rank MPI channel, with a live same-executable control. Graceful native finalization, terminal Ctrl+C delivery, larger/distributed MPI and coupled cancellation remain outside those tests.

| Exit code | Meaning |
| --- | --- |
| 0 | Command succeeded; warnings may remain; status queries can describe failed runs |
| 2 | Command/argument/edit usage error |
| 3 | Unsupported capability, missing dependency/resource or I/O/data error |
| 4 | Validation or stale-preview/existing-run-folder conflict |
| 5 | Native execution, timeout or interruption failure |
| 6 | Completion or output-time verification failure |
| 70 | Unexpected internal error |

The development build also exposes additional profiles with different levels of verification:

| Commands | Evidence and current limit |
| --- | --- |
| `restart prepare`, `run start --profile restart`, `restart compare` | [Actual split vs continuous case](research/notes/verification/restart-trial.md): same final state, different raw cumulative/diagnostic fields. The compare command returns exit 6 and per-variable differences on a mismatch. Opt-in `dfm restart forecast FULL FIRST RESUMED --cold-control COLD --tolerances POLICY --contract saved-forecast-v1` checks saved forecasts and reports the original raw failure alongside its verdict; the two native archives and 32 altered copies were checked. |
| `parallel plan/partition/run/merge/compare` | [Local two-rank trial](research/notes/verification/parallel-trial.md): both ranks reached 120 s. The native merge tool lost checkpoint arrays; the CLI reconstruction preserved all 39 rank variables. With forcing covering the full interval, `restart prepare --assembled` and direct FM consumed the 120 s checkpoint and reached 240 s. Final restart matched the declared tolerances; the complete raw series did not. |
| `network schema/create/inspect/validate` | Bounded [synthetic input specs](examples/network/plain-1d.json). Both the [fixed-weir/lateral case](research/notes/verification/network-structures.md) and the [seven 1D branch and 1D–2D exchange cases](research/notes/verification/network-exchange.md) passed their respective native volume and flow checks. |
| `layers create/inspect/verify`, `boundary vertical-inspect/vertical-set`, `run start --profile layers` | [Three sigma layers, two stations](research/notes/verification/layers.md): the [20-second example](examples/layers/vertical-cell.json) has a manual control for editing one existing T3D salinity cell. The [four-layer example](examples/layers/channel.json) is a different model. |
| `coupling inspect/prepare/validate/run` | The [standalone Waves and matched FM–Waves cases](research/notes/verification/waves.md) verified boundary forcing and two directions of exchange, respectively. For [the FM–RTC pair](research/notes/replay/coupling-cases.md), `coupling rtc-pair` authors two lookup rules. Ten transfers per arm and the resulting crest, downstream level and signed through-weir discharge were measured; resuming the RTC actuator is unverified. |
| `morph create/inspect/verify/compare`, `run start --profile morph` | [Two single-sand channels and their controls](research/notes/verification/morph-trial.md): native section counters measured 36.97337 kg and 31.34635 kg of mobile sand export, matching the stock loss. Frozen-bed, transport-disabled and rest controls, per-column budgets and final restart fields were verified for both designs. |

For water quality, `water-quality prepare/inspect` constructs a matched input pair for [FM in-kernel nitrification](research/notes/verification/water-quality.md). Use `dfm water-quality compare POSITIVE_RUN CONTROL_RUN --bundle BUNDLE` to verify completed paired runs and report concentration changes at matched cells and times. The separate `water-quality review-offline` reads a DELWAQ hydrodynamic descriptor and consumer input. `waq-offline prepare`, `preprocess`, `run` and `compare` were checked on a separate DELWAQ example 06 pair: at 3,600 s the measured EColi inventory fell by 2.95124×10¹⁰ MPN relative to its matched control. The source does not encode a time zone. A separate 1 s step fixture verified timeout and cancellation while a second DELWAQ process completed. For [live model control](research/notes/verification/live-worker.md), `bmi inspect` lists declared scalars; `bmi session` reads observations and can change one explicitly declared weir crest on the tested synthetic channel. The paired trial checked four native link fluxes and 14 isolated worker sessions. Other structures remain unverified. Consult `schema inspect` for the evidence for each workflow.

For the pinned f152 RR/FM inputs use `rr-f152 prepare` (preview, then apply with the returned hash) and `rr-f152 inspect`. [The three prepared scenarios](research/notes/replay/coupling-cases.md) distinguish rainfall and hydraulic controls. For these three cases, `coupling plan` and `coupling run` were verified to 600 s against the actual receiving outputs for all 34 linked laterals. The GUI export path and absolute vertical datum remain unverified.

## Development and evidence

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
python -m compileall -q src tests research/workflows research/scripts
```

The portable tests create their own temporary inputs/NetCDF datasets. The native
integration replay requires the locally collected baseline and installed suite;
see the [experiment index and native replay commands](research/notes/experiments.md).

Start with the [research index](research/README.md), the
[initial installation findings](research/notes/collection/initial-inspection.md), and the
[capability map](research/notes/collection/capability-map.md).

The intended foundation is explicit model files and engine interfaces. The Windows
GUI is a reference for model construction, export, validation, and execution.
For a single copied f34 model on the verified installation, the [optional console bridge](research/notes/verification/project-bridge.md) imports engine inputs into a new Shell project and exports a saved project back to engine inputs.

Downloaded source checkouts, manuals, portable tools, machine evidence, and
decompiled inspection output live under `research/` and are excluded from Git.
The source lock, investigation notes, and acquisition/inspection scripts are kept
as project documentation.

Agent contributors should read [AGENTS.md](AGENTS.md) before working on the project.
