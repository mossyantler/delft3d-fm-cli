# Contract: open run route for integrated user models (`RUN-OPEN`)

Beads: `RUN-OPEN-Contract` (`dfm-7tv`, this Contract), then `RUN-OPEN-A-*` and `RUN-OPEN-B-*` (to be created after the user
approves the scope). Status: **draft by the coordinator, 2026-11-10; not approved.** Product direction decided by the
user on 2026-11-10: besides the narrow verified profiles, `dfm` runs integrated models and reports per layer what
was checked, instead of refusing every feature combination that no profile has verified.

## Why

Every run profile today admits one verified feature island. `short` requires `Kmx = 0`, `Tzone = 0`,
`Wavemodelnr = 0`, at most 600 s (`runs.py:51-75`); `extended` admits a 2D water-level model of at most 7 days and
excludes meteo, transport, layers, morphology, Waves and coupling (`serial_profile.py:1-15`); authored profiles admit
one feature each (`runs.py:30`). A real model combines many features, and verifying every combination as its own
profile does not scale.

**Target model (user, 2026-11-10):** `~/project/garolim/garolim-3d.dsproj_data` (Garolim Bay). It is the user's
project: read and copied only, never written. Survey `GARO-SURVEY-20261110-01` (observed, current main `0d015aa`,
copy in `research/experiments/GARO-SURVEY-20261110-01/model/`):

| Feature | Input | Current CLI |
| --- | --- | --- |
| 3D sigma, 14 layers | `Kmx = 14`, `Layertype = 1` | refused by `short`/`extended` |
| Local time | `Tzone = 9` | refused by `short` |
| Salinity, temperature (transport only) | MDU and two 57.8 MB `.bc` (317 points × 14 layers) | refused by `extended` |
| Mud sediment and morphology | `SedFile`, `MorFile`, `Sedimentmodelnr = 4`, INI `initialsedfrac…` polygon | `model validate`: `unsupported_reference` (`model.py:193-194`) |
| Spatial Chézy roughness | INI `[Parameter] frictioncoefficient` from `.xyz` samples | `IniFieldFile`: `unsupported_reference` |
| Tide | `waterlevelbnd`, astronomic `.bc`, 317 support points | supported reference |
| Wind, rain/evaporation | EXT `[Meteo]` `windxy.wnd` (`uniMagDir`), `rainfall_rate` `.bc` | references accepted; refused by `extended` |
| SWAN waves via DIMR | `Wavemodelnr = 3`, `Waves/input/Waves.mdw` (outer and inner grids) | no DIMR configuration in the project (`Integrated_Model/` is empty) |
| Duration | 2023-07-01 to 2023-11-01 (123 days), `DtUser = 300` | `run start --timeout` ≤ 3600 s (`runs.py:124`) |

`model validate` reports exactly three issues: `geometry/inifieldfile`, `sediment/morfile`, `sediment/sedfile`
(`GARO-SURVEY-20261110-01/model_validate.json`).

## Question

Can `dfm` run such a model as given, through a public command, with the same guarantees as today (closed and
staged input graph, untouched source, owned processes, honest completion), and report which layers were
established, without claiming verification that does not exist?

## R1. Admission (`--profile open`)

1. **Closure is the only hard gate.** Every file the engine will read must be found and staged; a model is refused
   (exit 4, input unchanged) on a missing file, a path outside the model folder, an unknown key that names a file or
   directory (the G15 R6 rule), or a format whose references `dfm` cannot enumerate.
2. **Reference catalog extended** (I): `IniFieldFile` and every `dataFile` of its `[Initial]`/`[Parameter]` blocks;
   `SedFile` and `MorFile` and the files they name; EXT `[Meteo]` forcing files of the observed `forcingFileType`s;
   for Phase B, the DIMR configuration, `Waves.mdw` and its grid, depth, enclosure, boundary and output paths. Each
   added reader cites the engine source line that consumes the key (DIMRset_2026.02, `research/upstream/Delft3D`).
3. **No feature gate.** Layers, time zone, transport, sediment, morphology, meteo, structures and duration are not
   refused for being unverified. Only the existing hard limits stay: input size budget, output collision, no write
   into the source folder.
4. **Wave coupling is never dropped silently.** A model with `Wavemodelnr ≠ 0` runs only on the Phase B coupled
   route, or on the direct route if the user passes an explicit, recorded override that names the physics left out.

## R2. Execution

1. **Phase A (direct FM):** the staged copy runs with `dflowfm` under the existing owned Job (`runs.py`), with
   `run status` and `run cancel` unchanged.
2. **Long runs:** `--profile open` accepts a wall-clock limit beyond 3600 s and a detached mode in which `run start`
   returns after a verified launch and `run status` reports progress (engine time from the `.dia` or history file,
   with its source named). The process tree stays owned and cancellable; a lost monitor never claims an exit.
3. **Disk preflight:** before launch, an estimate of output size (map and history schedule × grid × layers ×
   variables) is compared with free space; the run is refused below the estimate unless the user sets a limit.
4. **Phase B (DIMR FM + Waves):** a DIMR configuration is generated from or checked against the existing
   `coupling` module (`coupling_profiles.py`, profile `fm_waves`) and its evidence `E015`/`08`. Whether `dfm`
   generates the configuration for a user model or requires one supplied is a scope question for the user.

## R3. Report (layered, never "verified")

The manifest and `run status` report each layer separately: input closure; engine initialization; simulation
reached the stop time; output files complete for the schedule; diagnostics (error and warning counts with the first
lines from the `.dia`). They add `verification: open` and a **feature table**: every feature the model uses, each
with its `dfm` evidence status (`verified <ID>` with the gate that verified it alone, or `not verified by dfm`), and
`combination: not verified`. `scientific_validation: not_performed` stays.

## R4. Acceptance (V-Plan predeclares before any run)

- **Public vs manual (Phase A):** a copy of the Garolim model with a bounded window set through public `model set`
  (V-Plan fixes the window, for example the first 6 h, and the wave handling of R1.4) runs through
  `run start --profile open` and through a coordinator-reviewed manual `dflowfm` launch on byte-equal staged inputs.
  History, map and restart outputs are exactly equal (rtol = atol = 0) except listed creation provenance.
- **Refusals:** missing INI `dataFile`, sediment file outside the folder, an unknown file-naming key, a disk estimate
  above the set limit: each refused before launch with the input unchanged.
- **Detached lifecycle:** launch, status with progress, cancel of a running case with every owned process exited
  and partial outputs retained and labelled.
- **Report:** the feature table for the Garolim copy lists every feature in the survey table above, each with the
  correct status.
- **Not required:** agreement with the user's Classic results or with field data; the full 123-day run (separate
  approval if the user wants it).

## R5. Process and limits

- Contract → I ∥ V-Plan → V-Run → G for Phase A; Phase B gets its own Contract revision after Phase A's G.
- Every native run needs the user's explicit approval as a HUMAN node, coordinator review and an exclusive lease.
- The user's project folder is read and copied only, never written; the DeltaShell GUI is never touched.
- The narrow profiles stay unchanged and keep their meaning as verified runs.

## Open questions for the user (before approval)

1. Phase A without waves: run the Garolim copy with `Wavemodelnr = 0` on the copy (recorded physics change), or
   wait for Phase B?
2. Phase B: should `dfm` generate the FM + Waves DIMR configuration itself, or require one exported from the GUI?
3. Detached long runs: is a multi-day wall clock on this machine acceptable in principle (each run still approved)?

## Out of scope

GUI parity, scientific calibration, MPI for user models (`parallel` stays separate), RTC, RR, water quality,
changing the narrow profiles.
