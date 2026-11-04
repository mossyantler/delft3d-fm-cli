# E004/E008: short serial direct-FM and DIMR runs

**Date:** 2026-11-04, Asia/Seoul. **Result:** both routes completed the requested
600-second simulation and produced matching output variable values. A second pair
repeated the experiment with an explicit installation-local PROJ resource path.
Warnings remain; this is execution/output verification, not model calibration.

See the [machine-readable summary](../../catalog/serial-experiment-summary.json) for
per-route times, output inventories, warnings, numerical field ranges, mass-balance
diagnostics and NetCDF comparisons.

## Baseline and controlled changes

Used the untouched ten-file export from
`experiments/E001-E002-replay-20261103/console-export-1/`. The E003/E005 edits were
not carried into this experiment. The original baseline and all ten input files
in each run remained unchanged after execution. Generated outputs/cache/logs were
recorded separately.

Each route received a separate copy with byte-identical prepared inputs. Only
three MDU value tokens changed during preparation:

| MDU field | Baseline | Short-run value |
| --- | --- | --- |
| `time/StopDateTime` | `19900806010000` | `19900805001000` |
| `output/HisInterval` | `300` | `60` seconds |
| `output/MapInterval` | `3000` | `60` seconds |

Start time remained `19900805000000`; reference date remained `19900805` and model
`TZone` remained `0`. Thus the requested model interval is **1990-08-05 00:00:00
through 00:10:00 UTC**, unrelated to the wall-clock experiment date.

The model's `TUnit = M` was retained. Output intervals are seconds independently
of that setting. `DtUser = 30`, `DtMax = 30`, the initial step, CFL, solver,
physics, mesh, bathymetry, boundaries and wind inputs were preserved. Restart
input remained empty. `RstInterval = 86400` was also preserved; the engine still
wrote initial and final restart snapshots for this short run.

The wind input spans 0-1500 minutes, covering the shortened interval. Harmonic BC
data was unchanged. Nine known input references resolved inside each run folder.

The input NetCDF declares 258 nodes, 479 links and 224 mesh elements. The computed
map contains 222 flow elements and 415 flow links. These are recorded separately;
output inspection must use the actual processed mesh dimensions.

## Execution paths and versions

| Route | Native command | Working directory |
| --- | --- | --- |
| Direct FM | `<kernels>/bin/dflowfm-cli.exe --autostartstop f34.mdu` | `direct/model/` |
| DIMR | `<kernels>/bin/dimr.exe dimr_config.xml` | `dimr/` |

`<kernels>` is the selected installation's
`plugins/DeltaShell.Dimr/kernels/x64/` directory. Both routes used the same child
environment: selected `share`, `lib`, and `bin` directories in PATH,
`OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, and `D3D_HOME` pointing to that kernel set.
The environment was derived from the installed launcher scripts; native
executables were invoked directly so their exit status was captured without a
batch wrapper. The batch files themselves were not executed in this experiment.

The DIMR XML was copied from the official release's sequential example, changing
only its component `workingDir` from `dflowfm` to `model`. It selects component
`DFlowFM`, library `dflowfm`, process `0`, and input `f34.mdu`. XML parsing and
component-file references were checked. XSD validation was not performed.

Runtime logs identify:

- FM: `1.2.184.Unknown`.
- DIMR executable: `2.00.Unknown`.
- DIMR library: `1.02.Unknown`.

Executable/DLL hashes, arguments, environment overrides, working directories,
process IDs, timeouts and raw stdout/stderr are retained. The exact source
revision of these installed binaries remains unknown. The reference repository's
release tag is not treated as proof of the binary build revision.

All four native processes returned 0 without a timeout. Kernel completion logs
report MPI disabled and a maximum OpenMP thread count of 1. This tests serial,
single-component DIMR execution, not MPI or online multi-component coupling.

## Final simulation time verified from file contents

The verifier discovers the one-dimensional CF time variable and reads its units
and calendar. It does not infer completion from a filename, exit code, or last
progress line. Time bounds are a separate two-dimensional variable.

Observed time units:

```text
seconds since 1990-08-05 00:00:00 +00:00
```

No explicit calendar attribute was present; decoding used the CF default
`standard` calendar. Both routes, in both run pairs, produced:

| Product | Samples / stored times | Verified final model time |
| --- | --- | --- |
| `f34_his.nc` | 11 samples: 0, 60, ..., 600 seconds | 1990-08-05 00:10:00 UTC |
| `f34_map.nc` | 11 samples: 0, 60, ..., 600 seconds | 1990-08-05 00:10:00 UTC |
| Initial restart | One sample at 0 seconds | 1990-08-05 00:00:00 UTC |
| Final restart | One sample at 600 seconds | 1990-08-05 00:10:00 UTC |

The verifier independently encodes the requested end datetime in each time
variable's units and compares it with the actual final value. History/map cadence
is checked against all eleven expected times. Finite, unmasked values were also
checked for representative water-level, depth and velocity fields.

Writing a restart snapshot does not establish that restart execution works; that
requires a separate experiment.

## Direct-FM vs DIMR numerical comparison

| Dataset | Variables compared | Result in each run pair |
| --- | --- | --- |
| History | 68 | All unmasked values equal |
| Map | 55 | All unmasked values equal |
| Initial restart | 34 | All unmasked values equal |
| Final restart | 34 | All unmasked values equal |
| **Total** | **191** | Matching dimensions, dtypes, masks and variable attributes |

Comparison used exact numerical equality with no tolerance, with matching masks;
masked storage bytes are not treated as physical values. Text variables also
matched. In the first run pair, history water level ranged approximately
1.8979678-1.9006240 m; velocities were finite and nonzero. The files contain
time-dependent model results, not just empty initialized datasets.

The NetCDF files were **not byte-identical**: each route generated different
global `uuid` attributes. These were the only global attribute differences
observed within each pair. The comparisons therefore separate file fingerprints,
provenance metadata and actual variable values.

History water level was written as `float32`; legacy map water level was
`float64`. The kernel warned that `MapFormat=1` cannot honor single-precision map
output. Actual format/precision must be inspected rather than inferred solely
from requested MDU settings. All inspected products use NetCDF3 classic storage.

The recorded maximum absolute `water_balance_volume_error` in the first pair was
about `1.4305e-6 m3`. This is a descriptive diagnostic; no project-specific
physical acceptance threshold or observational calibration was applied.

## Generated files and logging differences

Both routes generated a `f34.cache`, history/map files, initial/final restart
files and the model diagnostic log. Direct FM additionally created
`model/unstruc.dia`; DIMR created `model/output/f34_Cdwcoeff.tek`. These differences
did not correspond to differences in the compared NetCDF variable values.

The direct route printed `Start of the computation time loop`; the DIMR route
instead logged `DFlowFM.Initialize(f34.mdu)` and did not print that same banner.
Both printed the completion summary. Monitoring must not require identical log
messages from both entry points, and progress lines need not include every saved
time or the final model time.

Observed native wall times were 0.453/0.344 seconds for direct/DIMR in the first
pair and 0.203/0.203 seconds in the resource-path repeat. These very short runs
are not a performance benchmark.

## Warnings and resource-path repeat

| Observation | Action and remaining limit |
| --- | --- |
| `MapFormat=1` cannot support requested single map precision | Retained baseline; verified map data is double precision |
| `SigmaGrowthFactor` is deprecated; kernel suggests `zLayerGrowthFactor` | Retained baseline and logged the warning; no numerical setting migration was performed |
| Initial stderr included `Cannot find proj.db` | Located the existing installation-local database and repeated both runs with explicit child resource paths |
| `proj_create: unrecognized format / unknown name` remains | Retained diagnostic; CRS conversion correctness is not established by this experiment |

The existing database is at:

```text
<install>/bin/gdal/share/proj.db
```

The second pair explicitly set both `PROJ_DATA` and the compatibility variable
`PROJ_LIB` to that directory. The missing-database message disappeared, but the
remaining projection diagnostic persisted. The database is fingerprinted in the
fixture manifest; its metadata reports PROJ 9.1.1 and database layout 1.2. No
system-wide environment or installed files were changed, and no external database
was substituted.

Native `ERROR`/`FATAL` diagnostic lines were not observed. Nevertheless, successful
completion and agreement do not demonstrate correctness of every CRS operation,
physical adequacy of the initial/boundary conditions, or long-duration stability.

## Reproduce

Use a new, nonexistent experiment folder. The isolated research environment needs
the pinned requirements, including netCDF4, numpy and cftime for verification:

```powershell
research/.venv/Scripts/python.exe -m pip install -r research/requirements.txt

python research/scripts/run_serial_experiment.py --baseline research/experiments/E001-E002-replay-20261103/console-export-1 --install 'C:\Program Files\Deltares\Delft3D FM Suite 2026.02 OpenHMWQ' --proj-data 'C:\Program Files\Deltares\Delft3D FM Suite 2026.02 OpenHMWQ\bin\gdal\share' --out research/experiments/E004-E008-new-replay

research/.venv/Scripts/python.exe research/scripts/verify_serial_experiment.py research/experiments/E004-E008-new-replay
```

The first command prepares the three controlled MDU edits, copies identical model
inputs to both routes, checks known references, generates DIMR XML, runs each
native process sequentially with a 45-second bound, and preserves logs/manifests.
It records execution status only. The second command establishes final times,
variable agreement and preservation, retaining a separate `verification.json`.

Local evidence:

- `experiments/E004-E008-serial-20261104/`: first native pair, unchanged baseline
  snapshots, raw logs, file inventories, time axes and four NetCDF comparisons.
- `experiments/E004-E008-proj-20261104/`: resource-path repeat with the same model
  inputs and the same verification checks.

`analysis/` holds per-dataset comparisons and post-run snapshots. The research
source/dependency lock records the added NetCDF reader environment.

## Sources and next work

Reference source entry points: FM `net_main.F90`, `read_commandline.F90`,
`print_help_commandline.F90`, DIMR `dimr_exe.cpp`, official sequential example XML,
and the installed `run_dflowfm.bat`/`run_dimr.bat` environment setup.
The reference checkout is `DIMRset_2026.02`, commit
`5a4649830b1e5072caf019fb4850bbdefd9ad431`; see the capability map for full
source paths and the acquisition lock for provenance. Native behavior above is
supported by the retained run artifacts, independently of that source revision.

Manual references: FM User Manual §§8.1-8.3, printed pp.124-127 / PDF pp.150-153;
§8.7, printed pp.140-142 / PDF pp.166-168; §7.4.14, printed pp.118-121 / PDF
pp.144-147. DIMR User Manual §2.1.2, printed p.2 / PDF p.8, and §2.3.3, printed
pp.5-6 / PDF pp.11-12. Runtime evidence takes precedence where this installed
version differs from older documentation.

This completes E004/E008 for a copied, short serial fixture. It does not produce
a minimal model from scratch or validate GUI Run's live helper process (E007),
MPI, cancellation, restart execution, multi-component coupling, calibration, or
other versions/platforms. The next implementation step can use this fixture for
installation/model inspection and serial run/status verification while those
capabilities remain separate work items.

Final checks passed: research-script compilation, artifact/provenance audit,
both independent output verifications, documentation links including `AGENTS.md`,
current native binary hashes against both manifests, exactly the three planned
MDU field changes, and byte preservation of the other nine input files.
