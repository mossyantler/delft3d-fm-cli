# Delft3D FM CLI

An AI-friendly command line tool for inspecting, editing, validating, and running Delft3D Flexible Mesh (D-Flow FM) models.

The CLI uses explicit model files and engine executables, returns structured JSON, and records each run in a manifest. The initial release focuses on a reproducible Windows serial workflow. It is a research-backed starting point, not a complete replacement for the Delft3D GUI or scientific review.

## Current capabilities

- Discover Delft3D suite installations and inspect selected executables and libraries.
- Inspect an MDU and the supported input references it points to.
- Validate UTF-8/ASCII MDU syntax, selected references, and a limited set of time and output settings.
- Preview or apply selected MDU edits while preserving comments, line endings, ordering, and unrelated bytes. Applying an edit requires the preview's SHA-256 to catch stale input.
- Copy supported inputs into an isolated run folder and launch short serial runs through D-Flow FM directly or through a single-component DIMR configuration.
- Check run completion from engine diagnostics and the history, map, and final restart NetCDF time axes.
- Report run status and request cancellation through the live run owner. Windows Job Objects scope forced termination to the run's process tree.
- Return one JSON result or error on stdout; optional JSONL progress and native logs are kept on stderr and in the run folder.

## Requirements and installation

Python 3.12 or later. Model inspection and editing use the standard library. NetCDF output verification needs the `run` extra. Native model execution currently supports the tested Windows x64 Delft3D layout.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[run]'
.venv/Scripts/dfm.exe --version
.venv/Scripts/dfm.exe schema inspect
.venv/Scripts/dfm.exe install discover
```

Both the installed `dfm` command and `python -m dfm_cli` can be used. Select the suite installation explicitly when multiple versions are present:

```powershell
.venv/Scripts/dfm.exe install inspect --install 'C:/Program Files/Deltares/<Delft3D Suite>'
```

## Inspect, validate, and edit

Point commands at a **copy** of your model while exploring. The validator covers a documented subset; it does not parse the scientific contents of BC, PLI, mesh, or forcing data.

```powershell
$dfm = '.venv/Scripts/dfm.exe'
$mdu = 'C:/models/copied-case/flow.mdu'

& $dfm model inspect $mdu
& $dfm model validate $mdu

# Preview is read-only.
$preview = & $dfm model set $mdu output/hisinterval 60 | ConvertFrom-Json
$preview.result.diff

# Apply only if the input still matches the preview.
& $dfm model set $mdu output/hisinterval 60 --apply --expect-sha256 $preview.result.before_sha256
```

The currently editable settings are `output/hisinterval`, `output/mapinterval`, and an absolute `time/stopdatetime` later than the explicit start. Interval edits accept positive scalar seconds. Repeated target keys and unsupported interval windows are refused.

## Run and inspect status

The tested run profile is a cold-start, 2D, UTC serial model of at most 600 seconds, with the supported input graph and regular history/map schedules. Run folders must be new and outside the source model directory. Supply a Delft3D installation and a prepared model copy.

```powershell
$dfm = '.venv/Scripts/dfm.exe'
$mdu = 'C:/models/copied-case/flow.mdu'
$suite = 'C:/Program Files/Deltares/<Delft3D Suite>'

& $dfm run start $mdu --install $suite --route direct --out 'C:/runs/case-direct' --timeout 45 --progress
& $dfm run status 'C:/runs/case-direct'

# The alternate route writes and runs a DIMR configuration.
& $dfm run start $mdu --install $suite --route dimr --out 'C:/runs/case-dimr' --timeout 45
```

While a run is active, request cancellation from another terminal:

```powershell
& $dfm run cancel 'C:/runs/case-direct' --wait 10
```

A cancellation request, owner acknowledgement, and confirmed process-tree termination are reported separately. A request does not imply that a run has stopped. Timeout and cancellation force termination; graceful native finalization is not claimed. The manifest stores input fingerprints, executable identity, arguments, working directory, environment overrides, state, diagnostics, outputs, and verification results. Manifest schema v3 is written; v1/v2 records remain readable.

Completion requires native serial completion markers and checks of the history/map cadence and final restart time. This is not physical or scientific validation. The tested 2026.02 installation reports engine version `1.2.184.Unknown`; its source revision is unknown.

## JSON and exit codes

Every command response includes `protocol_version: 2`. Successes have an `ok` field and a `result`; failures return an `error` with a machine-readable code and details. `dfm schema inspect` describes the available commands, parameters, edit settings, run limits, and exit codes.

| Exit code | Meaning |
| --- | --- |
| 0 | Command succeeded |
| 2 | Argument or edit usage error |
| 3 | Unsupported capability, missing dependency/resource, malformed data, or I/O error |
| 4 | Validation or state/preview conflict |
| 5 | Native execution, timeout, cancellation, or interruption |
| 6 | Completion or output-time verification failed |
| 70 | Unexpected internal error |

## Development

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
python -m compileall -q src tests research/workflows research/scripts
```

Portable tests create their own temporary inputs. The native integration replays use a copied f34 example, the installed Delft3D suite, and fresh output folders; see the [experiment index](research/notes/experiments.md). Large-input timing and memory results, benchmark reproduction steps, and limits are in the [scale report](research/notes/verification/cli-scale-031.md). Research procedures and provenance are indexed in [research/README.md](research/README.md).

The checked-in repository contains source, tests, portable notes, and small research scripts. The `.gitignore` excludes downloaded suite/library checkouts, tools, manuals, virtual environments, and raw experiment runs.

## License

No project license has been selected yet. Until a license is added, repository publication alone does not grant reuse rights.
