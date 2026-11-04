# Research workspace

Initial collection: **2026-11-03, Asia/Seoul**.

This workspace combines installed-program evidence, official manuals, pinned
engine source, supporting libraries, and portable Windows inspection tools.
It is the evidence base for implementing the CLI; it is not a claim of complete
GUI feature coverage. One short serial fixture is now verified through direct FM
and DIMR; broader simulation workflows remain untested.

Canonical tools are grouped under `workflows/collection/`, `workflows/replay/` and `workflows/verification/`. Run them as modules from the repository root. The previous `scripts/` paths still forward commands and imports. Raw evidence stays in its original location.

Start with the [experiment index](notes/experiments.md) or the [0.3 release verification](notes/verification/cli-03.md).

## Read first

| Document | Purpose |
| --- | --- |
| [Initial findings](notes/collection/initial-inspection.md) | What was actually inspected, what was learned, and remaining uncertainties |
| [E001/E002 export findings](notes/replay/export-experiment.md) | Verified project save, GUI-hosted export, console reopen/export, and replay instructions |
| [E003/E005 edit findings](notes/replay/edit-experiment.md) | Exact scalar/BC deltas, property ownership, sparse-point mapping, preservation requirements and replay |
| [E004/E008 serial findings](notes/replay/serial-experiment.md) | Native commands, identical inputs, verified final output times, data comparison and remaining diagnostics |
| [First CLI slice](notes/verification/cli-first-slice.md) | Implemented command contract, preservation tests and public-command native verification |
| [E009/E011 failure/cancellation findings](notes/verification/failure-cancellation-experiment.md) | Actual native failures, primary errors, forced owned-tree stops, surviving native controls and partial output evidence |
| [Capability map](notes/collection/capability-map.md) | Proposed CLI workflows and the source/interface for each |
| [Investigation procedure](notes/replay/investigation-procedure.md) | Repeatable GUI experiments, traces, and evidence requirements |
| [Toolbox](notes/collection/toolbox.md) | Acquired tools, commands, status, and optional deeper tools |
| [Source registry](sources.json) | Official source/documentation URLs and their roles |
| [Acquisition lock](sources.lock.json) | Exact repository commits and downloaded artifact hashes |
| [MDU candidates](catalog/mdu-candidates.json) | 530 literal engine writer keys and 456 annotated HYDROLIB fields; incomplete candidate index |

## Collected locally

| Location | Contents |
| --- | --- |
| `upstream/Delft3D/` | Sparse checkout of `DIMRset_2026.02`; FM, DIMR, Waves, WAQ, RTC/FBC, RR, morphology, common utilities, two official examples |
| `upstream/HYDROLIB-core/` | Python model-file parsers, typed models, serializers, and tests |
| `upstream/MeshKernel/`, `upstream/MeshKernelPy/` | Native meshing algorithms and Python wrapper |
| `upstream/dfm_tools/`, `upstream/xugrid/` | Model preprocessing, output processing, and unstructured-grid data tools |
| `manuals/` | Ten official local PDFs, 1,636 PDF pages total, searchable text and SHA-256 manifest |
| `tools/` | Process Monitor, Strings, ILSpy GUI, ILSpyCmd, Dependencies |
| `evidence/installation/` | 2,928 installation file entries, selected binary PE/CLR metadata, launcher copies, process/module inventory, help/version probes |
| `evidence/managed-inspection/` | Targeted decompilation for local interface research and its source-assembly hashes |
| `evidence/console-probe/` | A successful side-effect-free IronPython print probe, with startup warnings preserved |
| `assets/export-experiment/` | Portable IronPython GUI-hosted save/export and console export scripts |
| `assets/edit-experiment/` | Guarded IronPython edits for independent control/scalar/boundary cases |
| `experiments/E001-E002-*/` | Controlled export fixtures, failure/success logs, snapshots and comparisons; retained locally |
| `experiments/E003-E005-*/` | Edit probes, comparisons, rejected attempts, and verified sequential replay; retained locally |
| `experiments/E004-E008-*/` | Two direct/DIMR pairs, input manifests, raw logs, NetCDF comparisons and separate verification results; retained locally |
| `experiments/CLI-*/` | Application CLI replay: previews/applies, validation, native runs, status JSON, file comparisons and verification |
| `experiments/E009-E011-*/` | Native failure probes, ownership checks, cancelled/timed-out outputs and full replay evidence |
| `.venv/` | Isolated inspection environment, including `pefile`, `dnfile`, `pypdf`, `netCDF4`, `numpy` and `cftime` |

The checked-out helper libraries were acquired from their default branches and
locked by commit. They are research references, **not a validated dependency set
for the 2026.02 engine**. The engine checkout is sparse and cannot yet be treated
as a complete build tree. The installed engine reports an unknown source revision.

## Reproduce

Run from the project root in PowerShell:

```powershell
python -m venv research/.venv
research/.venv/Scripts/python.exe -m pip install -r research/requirements.txt

python research/scripts/acquire.py repo Delft3D
python research/scripts/acquire.py repo HYDROLIB-core
python research/scripts/acquire.py repo MeshKernel
python research/scripts/acquire.py repo MeshKernelPy
python research/scripts/acquire.py repo dfm_tools
python research/scripts/acquire.py repo xugrid
python research/scripts/acquire.py tools
python research/scripts/acquire_managed_cli.py

research/.venv/Scripts/python.exe research/scripts/inspect_install.py --install '<Delft3D suite installation root>' --probe-help
python research/scripts/decompile_targets.py --install '<Delft3D suite installation root>'
python research/scripts/probe_console.py --install '<Delft3D suite installation root>'
./research/scripts/capture_processes.ps1
research/.venv/Scripts/python.exe research/scripts/index_manuals.py '<folder containing locally collected FM manuals>'
python research/scripts/build_catalog.py
python research/scripts/audit_research.py
```

Acquisition retains existing clones and records their current commits. A fresh
helper clone or a fresh `latest` tool acquisition can select newer content; compare
the resulting lock with the saved lock. To reproduce a specific helper revision,
fetch and check out the commit in `sources.lock.json`. The engine acquisition
checks that an existing checkout still matches the requested release tag.

No system-wide runtime, compiler, PATH modification, or Process Monitor driver
installation was performed. ILSpyCmd's Windows package is self-contained.
