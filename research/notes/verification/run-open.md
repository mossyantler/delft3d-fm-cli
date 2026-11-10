# RUN-OPEN A1 · Open run profile (`run start --profile open`)

The [Contract](../delivery/run-open.md) adds a run route for integrated user models: admission checks only that the
input graph is closed, and the result reports each layer and a feature table instead of refusing unverified feature
combinations. A1 is its first slice: direct FM, blocking, wall clock at most 3600 s. Detached long runs and the disk
preflight are A2; FM + Waves through DIMR, where the Garolim model first runs, is Phase B.

## What the product does (merged as `RUN-OPEN-A1-G`, candidate `227ccc0`)

- **Admission:** `--profile open` refuses a model only for missing or outside references, an uncatalogued key that
  names a file, legacy EXT, restart input, trachytopes, custom output paths, an input graph above 256 MiB, or
  `Wavemodelnr ≠ 0` (no coupled route yet). Layers, time zone, transport, sediment, morphology, meteo and duration
  are not refused.
- **Closure:** `model validate` and the open profile enumerate `IniFieldFile` and the data files of its
  `[Initial]`/`[Parameter]` blocks, `SedFile`/`MorFile`, and the data files named inside them (`BcFil` and the file
  form of number-or-file keys), resolved from the folder of the `.sed`/`.mor` file as the engine does (R9). Library
  keys (`TranspLib`, `SettleLib`) stay refused.
- **Report:** layers `input_closure`, `engine_initialization`, `simulation`, `outputs`, `diagnostics`; before a launch
  or after a refusal every execution layer is `not_performed`. Diagnostics count the run's `.dia` files (first 32
  lines); stdout and stderr are reported separately. `verification: open`, `combination: not verified`,
  `scientific_validation: not_performed`.
- **Feature table (R10):** one row per used feature with its configuration; a row cites a gate only when the gate's
  recorded scope covers that configuration and states the scope, otherwise `not verified by dfm` with the reason.
- **Ownership:** the open profile traces its Job members; a run is not reported completed unless every member's
  exit is confirmed (R11.2).

## Verification (2026-11-10)

| Check | Result |
| --- | --- |
| Author tests (I, four rounds) | full discover 2,015 OK, 47 skips, on `227ccc0` |
| Garolim copy (`GARO-SURVEY-20261110-01`, read-only) | `model validate` exit 0, FM graph closed (16 files); `run start --profile open` refused before launch for waves, input unchanged, no engine process; feature table: sigma layers and salinity cite `3D-G` with its three-layer scope, the other ten features `not verified by dfm` (astronomic tide, mud, 123 days among them) |
| Refusals | missing INI data file, sediment file outside the folder, unknown file-naming key: each refused before launch, inputs unchanged |
| Native #240 (user approval `HUMAN-20261110-02`) | integrated test model (12 cells, 3 sigma layers, `Tzone = 9`, salinity, temperature, INI fields, sample roughness, sand MPM sediment and morphology, rain), 20 s: public open run and manual `dflowfm`, both exit 0 with all-member exit proof |
| Public vs manual | history 69, map 57 and two restarts 44 variables each, exactly equal (rtol = atol = 0); only 4 creation-provenance attributes per file differ |
| Wheel | 214 product files equal to the candidate; payload equal between G's and V's wheels (`8f00b301…`) |

**Rounds.** V-Run 1 rejected the report before any launch (R7 rulings had not reached I; fixed as R10). V-Run 2's
single launch failed at initialization on a fixture error (`Unknown boundary "west" in morphology.mor`) and exposed
untraced Job members (R11). V-Plan's revision also fixed `rain.bc` `Name = global` (R11.3) and left a stale manual
inventory (R12). V-Run 3's reader measured CF times from a naive origin; R13 applied R7.3's `+09:00` origin to the
retained outputs, and the unchanged schedule `[0, 10, 20]` passed.

**Evidence:** [round 3 review](../../experiments/RUN-OPEN-A1-V-Run-r3-20261110-01/REVIEW.md),
[result](../../experiments/RUN-OPEN-A1-V-Run-r3-20261110-01/verification.json),
[revised plan](../../experiments/RUN-OPEN-A1-V-Plan-r2-20261110-01/REVISION.md),
[G acceptance](../../experiments/RUN-OPEN-A1-G-20261110-01/acceptance.json).

## Not established

- the Garolim model's engine run (Phase B: FM + Waves via a generated DIMR configuration);
- detached runs beyond 3600 s and the disk preflight (A2);
- any combination of features as verified, and scientific validity;
- an open run whose root exits 0 while a member exits nonzero is not refused (only exit confirmation was added);
- the open profile's `schema inspect` entry still says `evidence: pending`; it does not yet cite this acceptance.
