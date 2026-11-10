# Contract: open run route for integrated user models (`RUN-OPEN`)

Beads: `RUN-OPEN-Contract` (`dfm-7tv`, this Contract), then `RUN-OPEN-A-*` (Phase A) and later `RUN-OPEN-B-*`
(Phase B). Status: proposal by the coordinator, 2026-11-10, with the user's scope decisions of the same day (section
"User decisions"). Product direction decided by the user on 2026-11-10: besides the narrow verified profiles, `dfm`
runs integrated models and reports per layer what was checked, instead of refusing every feature combination that no
profile has verified.

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
   `coupling` module (`coupling_profiles.py`, profile `fm_waves`) and its evidence `E015`/`08`; `dfm` generates the
   configuration for a user model (user decision 2).

## R3. Report (layered, never "verified")

The manifest and `run status` report each layer separately: input closure; engine initialization; simulation
reached the stop time; output files complete for the schedule; diagnostics (error and warning counts with the first
lines from the `.dia`). They add `verification: open` and a **feature table**: every feature the model uses, each
with its `dfm` evidence status (`verified <ID>` with the gate that verified it alone, or `not verified by dfm`), and
`combination: not verified`. `scientific_validation: not_performed` stays.

## R4. Acceptance (V-Plan predeclares before any run)

Phase A (direct FM, no waves):

- **Integrated test model:** V-Plan builds or selects one uncoupled model (`Wavemodelnr = 0`) that combines at least
  `Kmx > 0`, `Tzone ≠ 0`, salinity and temperature transport, an `IniFieldFile` with an `[Initial]` and a
  `[Parameter]` block (sample `.xyz` and polygon data), `SedFile`/`MorFile` with one sediment fraction, and an EXT
  `[Meteo]` forcing; from repository examples or a copied official example, with sources stated. It is not the
  Garolim model (user decision 1).
- **Public vs manual:** that model runs through `run start --profile open` and through a coordinator-reviewed manual
  `dflowfm` launch on byte-equal staged inputs. History, map and restart outputs are exactly equal (rtol = atol = 0)
  except listed creation provenance.
- **Garolim closure without launch:** on the Garolim copy, `model validate` reports the input graph closed (the three
  survey issues gone, every INI, sediment and morphology file enumerated), and `run start --profile open` refuses
  before launch under R1.4 (`Wavemodelnr = 3`, no coupled route yet) with the input unchanged. The feature table of
  its report lists every feature in the survey table, each with the correct status.
- **Refusals:** missing INI `dataFile`, sediment file outside the folder, an unknown file-naming key, a disk estimate
  above the set limit: each refused before launch with the input unchanged.
- **Detached lifecycle:** launch, status with progress, cancel of a running case with every owned process exited
  and partial outputs retained and labelled.

Phase B (DIMR FM + Waves) is where the Garolim model itself first runs, on a bounded window chosen by its V-Plan.

- **Not required:** agreement with the user's Classic results or with field data; the full 123-day run (separate
  approval when the user wants it).

## R5. Process and limits

- Contract → I ∥ V-Plan → V-Run → G for Phase A; Phase B gets its own Contract revision after Phase A's G.
- Every native run needs the user's explicit approval as a HUMAN node, coordinator review and an exclusive lease.
- The user's project folder is read and copied only, never written; the DeltaShell GUI is never touched.
- The narrow profiles stay unchanged and keep their meaning as verified runs.

## User decisions (2026-11-10)

1. **Garolim waits for Phase B.** Phase A does not run the Garolim model with waves switched off; its native
   acceptance uses a separate integrated test model (R4), and Garolim is checked for closure and refusal only.
2. **`dfm` generates the DIMR configuration** for FM + Waves in Phase B, from the MDU and `Waves.mdw`, through the
   existing `coupling` module; a GUI export is not required.
3. **Detached long runs are allowed in principle**, including multi-day wall clocks; each native run still needs its
   own approval.

## R6. Phase A split (coordinator, before dispatch; binding)

Phase A is delivered as two chains, each with its own I, V-Plan, V-Run and G; A2 starts after A1's G.

1. **A1 · admission, closure and report** (`RUN-OPEN-A1-*`):
   - `run start --profile open` on the **direct route only**, blocking, with the existing wall-clock limit
     (`--timeout` ≤ 3600 s) and the existing owned Job, `run status` and `run cancel`.
   - Reference catalog (R1.2) for `IniFieldFile` and the data files of its blocks, and for `SedFile`/`MorFile` and
     the files they name, also in `model validate`. Any other key or block that names a file stays refused as
     `unsupported_reference` (R1.1): for example `StructureFile`, legacy `ExtForceFile`, `RestartFile`.
     The existing authored readers (`layers_inputs.py`, `morph_inputs.py`) may be reused, not widened in meaning.
   - R1.3 (no feature gate) and R1.4 as a plain refusal: `Wavemodelnr ≠ 0` is refused before launch; the
     override of R1.4 is not part of A1.
   - The layered report and feature table (R3) in the manifest, `run start` output and `run status`.
   - A1 acceptance is R4 Phase A without the disk-estimate refusal and the detached lifecycle; the integrated test
     model's window must finish within the 3600 s wall clock.
2. **A2 · detached long runs and disk preflight** (`RUN-OPEN-A2-*`): R2.2 and R2.3 for `--profile open`, with
   the remaining R4 Phase A items. Planned after A1's G.

## R7. A1 V-Plan ambiguities (coordinator, after V-Plan and before any A1 candidate result; binding)

Rulings on the five ambiguities of `RUN-OPEN-A1-V-Plan` (plan-freeze sha256 `43e4a1fa…`), made without reading the
A1 candidate:

1. **A-INTERFACE.** Field names are the implementation's. V-Run binds the plan's unbound template to the
   candidate's actual manifest, `run start` reply and `run status` fields, records every pointer, and the coordinator
   reviews the binding before launch. A binding may only name where a layer or status is reported, never change what
   the plan expects it to say. A refused case need not create a manifest; its reply must carry the reason and, for
   Garolim, the feature table.
2. **A-FEATURE-SCOPE.** As the plan proposes: a feature's status may cite a gate that verified that feature alone,
   with the gate's scope stated; a configuration outside that scope (for example 14 layers, mud instead of sand,
   astronomic instead of harmonic tide) is reported as such, and the combination is never verified.
3. **A-CLOCK.** As the plan proposes: the CF time origin of outputs is the MDU `RefDate` as the engine writes it,
   with time-zone offsets honoured as encoded in the CF units.
4. **A-GAROLIM-CLOSURE.** A1 closure means the FM input graph (MDU, EXT, INI, sediment and morphology files and
   every file they name). Closure of the coupled graph (DIMR configuration, `Waves.mdw` and its files) belongs to
   Phase B; A1 does not claim it, and the Garolim refusal must say that waves are not handled.
5. **A-DIAGNOSTICS.** As the plan proposes (counts over the run's `.dia` files, first 32 lines, raw stdout/stderr
   scanned separately). Before launch, execution layers are reported as not performed, not as zero.

## R8. Files named inside `.sed`/`.mor` (coordinator, after A1-I; binding)

A1-I (candidate `6f07e42`) enumerated `SedFile`/`MorFile` but refused every file name inside them (`BcFil`, file
values of keys such as `IniSedThick`, and library keys), because the engine opens such names relative to its working
directory. On the direct route `dfm` starts the engine with the staged MDU folder as working directory
(`runs.py:209`), so that folder is the base. Ruling:

1. File names inside `.sed`/`.mor` that the engine opens as data (at least `BcFil`, and the file form of keys that
   accept a number or a file) are resolved from the MDU folder and enumerated, staged and refused like any other
   reference (missing, outside the folder). Each key cites the engine source line that opens it.
2. Library keys that load executable code (`TranspLib`, `SettleLib` and the like) stay refused in A1.
3. The rest of A1-I stands. A follow-up I (`RUN-OPEN-A1-FIX-I`) applies this on top of `6f07e42`.

## R9. Base folder for names inside `.sed`/`.mor` (coordinator, after A1-FIX-I; binding, replaces R8.1's base)

The engine joins a name inside `.sed`/`.mor` to the folder of that file (`properties.f90:3229`, `rdmor.f90:727`;
`IniFluffMass` in `.sed` uses the `.mor` folder, `rdmor.f90:2197`), not to the working directory. R8.1's base is
therefore the folder of the `.sed`/`.mor` file that names it; this equals the MDU folder whenever those files sit
there, as in every A1 case. The rest of R8 stands. The open profile's `schema inspect` description is updated to
match (the only schema change allowed in A1-FIX-I).

## Out of scope

GUI parity, scientific calibration, MPI for user models (`parallel` stays separate), RTC, RR, water quality,
changing the narrow profiles.
