# First application CLI slice

Historical v0.1.0 scope below. Follow-up [E009/E011](failure-cancellation-experiment.md)
adds v0.2.0 `run cancel`, private Windows Job Object ownership, active-record
identity observations and failure/partial-output diagnostics. The old source
fingerprints and test counts describe that earlier implementation.

Implemented 2026-11-04 in `src/dfm_cli/`, packaged by `pyproject.toml`. The standard
library `argparse` supplies discoverable commands without a CLI framework runtime
dependency. NetCDF verification is an optional, pinned `run` dependency. The
application does not import research scripts or require downloaded source trees.
The [verification summary](../../catalog/cli-workflow-summary.json) records the three
run pairs, tested package versions and final application source fingerprints.

## Implemented contract

| Command | Behavior |
| --- | --- |
| `install discover` | Explicit roots/immediate children or ProgramFiles/Deltares, plus DFM_INSTALL; reports all candidates |
| `install inspect` | Known suite layout, whitelisted product settings, selected executable/DLL hashes and installed PROJ resource path; no native loading |
| `schema inspect` | Implemented commands, editable field subset, exit codes and limits |
| `model inspect` | Read-only MDU entries, limited reference graph, fingerprints, explicit absolute model clock and unresolved/unsupported inputs |
| `model validate` | Syntax, selected references and limited time/interval checks; no engine initialization or physical validation |
| `model set` | Default preview, or explicit apply with expected input hash; replace one existing value token only |
| `run start` | Fresh input staging, direct or single-component DIMR subprocess, wall-clock bound, manifest and separate logs, CF output-time verification |
| `run status` | Persisted manifest/verification, explicitly distinguished from live process state |

Supported edits: scalar positive `output/hisinterval`, `output/mapinterval`, and
absolute `time/stopdatetime`. The field units and GUI-owner distinction come from
[E003/E005](../replay/edit-experiment.md). This editor works directly on MDU bytes, avoiding
the GUI exporter's broad normalization. It does not edit BC files.

Known MDU references are NetFile, ThinDamFile, DryPointsFile, LandBoundaryFile,
ExtForceFileNew, ObsFile and CrsFile. New EXT Boundary/Meteo LocationFile and
ForcingFile references are followed using PathsRelativeToParent. Absolute,
drive-relative and escaping paths are refused. Nonempty unknown file fields,
legacy EXT and unsupported nested input formats are reported, not silently copied.
Opaque BC/PLI/mesh content and arbitrary engine-specific options require further
validation; this is not a complete file schema or dependency resolver.

The run profile is deliberately limited to <=600 seconds, explicit absolute UTC
dates, Kmx=0, cold start, disabled Waves/trachytopes, regular positive scalar
history/map schedules aligned with DtUser, and unsplit output. Native commands,
working directories, PATH and PROJ handling follow [E004/E008](../replay/serial-experiment.md).
Generated DIMR XML has one DFlowFM start/component, process 0 and library dflowfm.
XML generation/native acceptance are tested; XSD validation is not claimed.

The manifest keeps static validation, attempted/native-confirmed initialization,
verified simulation completion and unperformed scientific validation separate.
Log completion is supplemented with all expected history/map times and a restart
dataset whose final CF time matches the requested end. UUID provenance does not
serve as a numerical comparison criterion.

## Native public-command verification

`scripts/verify_cli_workflow.py` uses a new copy of the untouched E001/E002 f34
export. Through the public CLI, it:

1. Discovers commands/installations and inspects the model and selected suite.
2. Previews and applies StopDateTime=19900805001000, HisInterval=60 and MapInterval=60,
   checking that preview makes no changes and apply produces the previewed hash.
3. Validates the prepared model without claiming native initialization.
4. Runs direct FM and DIMR separately and reads each persisted status.
5. Checks eleven history/map samples ending at 1990-08-05 00:10:00 UTC, plus the
   final restart; compares all 191 dataset variables with the research comparator.
6. Confirms unchanged source/prepared inputs and refusal to reuse a run directory.

The first replay is retained in `experiments/CLI-slice-20261104/`. All **16 public
CLI calls** passed, both native routes completed, and all **191 output variables**
agreed. Raw command JSON/stderr, native logs, manifests, NetCDF comparisons and
verification JSON are retained locally. Projection, legacy precision and
deprecated-key diagnostics remain visible; this does not establish CRS or
scientific correctness. The source baseline's ten input files stayed unchanged.

A second replay is retained in `experiments/CLI-replay-20261104/`. A third replay
in `experiments/CLI-isolated-20261104/` used the separate application `.venv`,
which contains the application and NetCDF reader dependencies without the PE/PDF
research tools. All three pairs passed: **48 public CLI calls and six native
runs**. The isolated replay also records CLI/Python/reader versions and parsed
runtime version strings, separately from suite product metadata and source SHA.

The regression suite includes byte preservation across BOM/CRLF/comments/unknown
precision/repeated unrelated keys, repeated-target refusal, stale-preview conflicts,
interval-window/nonfinite/injected-value refusal, nested path modes and sibling
references, missing/unknown/legacy input handling, explicit date precedence,
structured errors, partial/nonfinite/missing output refusal, zero-exit failure
manifests, and mocked owned-process timeout handling. Process-tree termination
against native FM/DIMR was not integration-tested at that point; E009/E011 now
provides that evidence for the serial fixture.
All **18 regression tests** passed in the isolated application environment.

Reproduce after installing `.[run]` in the research environment, with a new output
directory each time:

```powershell
research/.venv/Scripts/python.exe -m pip install -e '.[run]'
research/.venv/Scripts/python.exe research/scripts/verify_cli_workflow.py --baseline research/experiments/E001-E002-replay-20261103/console-export-1 --install 'C:/Program Files/Deltares/Delft3D FM Suite 2026.02 OpenHMWQ' --out research/experiments/CLI-new-replay
```

## Remaining work

Expand reference/schema coverage with independently verified formats; add a
durable background worker before asynchronous execution/resume; serial live-owner
cancel and native failure evidence are now covered by E009/E011. Pursue E007 GUI
helper tracing, restart execution and MPI as separate cases. HYDROLIB, MeshKernel,
project bridge and coupled engines are not application dependencies/capabilities
in this slice.
