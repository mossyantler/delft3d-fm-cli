# Research and evidence guide (`research/`)

Read the root [AGENTS.md](../AGENTS.md) first. This file governs experiments,
native replays, GUI/console investigation, evidence and the research tools. The
[research index](README.md) lists the collected repositories, manuals and tools.
Read only the notes your task touches:

- [Investigation procedure](notes/replay/investigation-procedure.md): controlled
  experiments and evidence requirements. Read it before designing any experiment.
- [Initial findings](notes/collection/initial-inspection.md): confirmed behavior and gaps.
- [Capability map](notes/collection/capability-map.md): proposed workflows and source entry points.
- [Toolbox](notes/collection/toolbox.md): available inspection utilities and their usage.
- [First CLI slice](notes/verification/cli-first-slice.md): the original command contract and its native replay.

The direction: explicit input files and native engine interfaces are the core
control surface. The Windows GUI is a reference for model construction,
validation, export and execution; record how its behavior maps to files and
engine calls. `DeltaShell.Console.exe` is an optional project import/export
bridge.

## Evidence and version discipline

- Record GUI version, executable version and hash, source revision, input format
  version and helper-library version as separate facts. The suite observed on
  2026-11-03 is **2026.02 OpenHMWQ**. Its FM engine reports `1.2.184.Unknown`,
  and that string says nothing about the source commit. The collected engine
  release is `DIMRset_2026.02`; its SHA is in the [lock](sources.lock.json).
- Check the actual options and DLL layout of the selected installation. For
  example, this DIMR executable rejects `--help`, and the 2026.02 GUI expects
  native libraries under `lib`.
- An advertised option, an exported symbol, a successful decompilation or a
  console print does not establish a working modeling capability. The MDU
  [candidate index](catalog/mdu-candidates.json) is incomplete. Complete source
  builds are unverified.
- Record upstream revisions and local artifact hashes when acquiring new
  references ([sources](sources.json), [lock](sources.lock.json)). Upstream
  checkouts are read-only references.
- HYDROLIB-core, MeshKernel/MeshKernelPy and dfm_tools/xugrid are research
  references. None is an approved or tested application dependency.
- Keep raw GUI decompilation and installed-program artifacts in ignored local
  evidence. Implement from documented behavior and appropriate source interfaces.

## Running experiments

- Work on fresh projects or copied official examples under `experiments/`.
- One controlled operation per experiment. Keep the baseline and changed inputs,
  file snapshots, relevant traces and logs, and the interpreted difference.
- Run shell experiment cases sequentially until shared scratch-directory
  isolation is understood; one concurrent startup failed.
- GUI project save (`.dsproj` and its data) and export of a complete engine input
  set are separate operations. Follow file references instead of copying the MDU
  alone.
- Keep observed GUI/console changes, engine-only evidence and proposed commands
  apart. Before extending a GUI workflow, find its task ID in the
  [GUI/console workflow inventory](notes/collection/gui-workflows.md) and keep that
  ID attached to file changes, pinned engine entry points, the public command
  contract and the experiment evidence. The
  [M0 audit](catalog/gui-workflows-audit.json) checks the table's structure and
  references; it certifies neither GUI behavior nor engine equivalence.
- Live Windows UI inspection uses supported Computer Use tools. Repeatable
  automation prefers native files, source, the console and engine interfaces.
- Each native replay creates fresh baseline copies and run folders, and needs a
  coordinator lease ([COORDINATOR](../COORDINATOR.md#resources-and-leases)).

## Findings that change how you work

- **E001/E002 console bridge** ([export findings](notes/replay/export-experiment.md)):
  set `persistenceDefault` and `useNewPersistence` inside the script before any
  project operation, because command-line app settings apply too late. A console
  script exception can still return exit code 0, so require a completion result
  and inspect the artifacts. GUI/console export can migrate and reorder MDU
  fields, so it is never a preservation-oriented editor.
- **E003/E005 edit mappings** ([edit findings](notes/replay/edit-experiment.md)):
  change the owning `HisOutputDeltaT` TimeSpan for a history-interval edit,
  because a raw `HisInterval` change alone did not survive export. Harmonic API
  frequency is in deg/h while this BC stores the period in minutes. Support-point
  API indices are zero-based. Verify the written value/cell and all non-target
  metadata and signals.
- **E004/E008 serial runs** ([serial findings](notes/replay/serial-experiment.md)):
  both routes reached 600 s with matching NetCDF values. Check CF time
  units/calendar and the actual final history/map/restart times; log banners
  differ between routes. UUID provenance can change file hashes without changing
  data. Preserve legacy-format, deprecated-key and projection diagnostics. CRS
  correctness is unverified.
- **E009/E011 failure and cancellation**
  ([findings](notes/verification/failure-cancellation-experiment.md)): copied
  inputs and same-executable native controls. Full BC semantics, terminal Ctrl+C
  delivery, graceful native shutdown, MPI and coupled cancellation remain
  separate work.
- **Scoped references:** P01–P04 [console round trip](notes/verification/project-bridge.md);
  R08 [two-rank MPI](notes/verification/parallel-trial.md); S02/S03/S06
  [three-layer salinity](notes/verification/layers.md); B13 input replay uses the
  [portable three-case preparation](notes/verification/layers.md#portable-b13),
  with the historical #203 producer and the independent numerical reader at their
  pinned paths; M1–M5 [product verification](notes/verification/roadmap-2d.md)
  does not generalize to other CRS or boundary functions. E007 must trace Run on
  a fresh, owned GUI and project before identifying its helper or assigning GUI
  execution parity.

Completed workflow scopes (E001–E011, the first CLI slice, M1–M5) are
fixture-specific. Interactive menu/dialog behavior, modified-project
save/reopen and other edit types are untested. Later MPI, restart, meshing and
coupled work is listed in the [experiment index](notes/experiments.md) and the
[capability map](notes/collection/capability-map.md).

## Layout

- `workflows/{collection,replay,verification}/` hold the canonical tools. Run them
  as modules from the root: `python -m research.workflows.<group>.<name>`. Old
  `scripts/` paths forward to the same modules.
- `notes/` holds findings: `collection/` for inventory and capability,
  `replay/` for controlled experiments, `verification/` for gates.
  [`notes/delivery/`](notes/delivery/history-to-20261106.md) archives the
  delivery history up to 2026-11-06; search it by node ID.
- `catalog/` holds gate receipts and indexes. `checkpoints/` is immutable.
  `proposals/` holds candidate code and reviews. `experiments/`, `evidence/`,
  `upstream/`, `manuals/` and `tools/` stay local and Git-ignored.
- Keep the original experiment folders and the independent numerical comparator
  in place.

## Commands

From the repository root:

```powershell
# Snapshotted wheel and clean install outside the checkout:
.venv/Scripts/python.exe -m research.workflows.verification.verify_wheel --out research/experiments/<fresh-package-check>

# Isolated research environment (only if missing):
python -m venv research/.venv
research/.venv/Scripts/python.exe -m pip install -r research/requirements.txt

# Research syntax and collected-artifact audit:
python -m compileall -q research/workflows research/scripts
python research/scripts/audit_research.py

# E009/E011 replay (copied inputs, same-executable controls; needs a lease):
.venv/Scripts/python.exe research/scripts/verify_failure_cancellation.py --baseline <baseline-folder> --install <suite-root> --out <new-experiment-folder>
```

The audit requires locally collected artifacts. On a fresh checkout, acquire them
first using the research index; missing artifacts are not CLI test failures. The
audit validates no simulation. Run `build_catalog.py` only when intentionally
refreshing the acquisition lock and candidate index. Native integration uses the
application venv with `.[run]`, and the commands are in the
[experiment index](notes/experiments.md).
