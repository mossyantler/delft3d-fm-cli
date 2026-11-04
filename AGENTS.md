# Agent guide

## Purpose and current phase

Build an AI-friendly Delft3D Flexible Mesh CLI for creating model input files,
inspecting and editing configurations, validating models, managing simulations,
and inspecting outputs. Broad suite coverage is the long-term objective; deliver
one reproducible workflow at a time.

The project contains an initial Python application in `src/dfm_cli/`, research
utilities and an evidence collection. Implemented commands are documented in
README and `dfm schema inspect`; other names in the capability map remain
proposals. Update this guide when implementation or development commands change.

## Start here

CLI 0.3 uses JSON protocol 2, manifest 3. See the [release verification and migration](research/notes/verification/cli-03.md) and [experiment index](research/notes/experiments.md). Keep historical manifests read-only. A process lookup failure is never proof that a process exited.

For performance work use the [0.3.1 scale benchmark](research/notes/verification/cli-scale-031.md): measure MDU, NetCDF and logs in separate processes on identical inputs. Preserve diagnostic context, markers and file hashes when changing the scanner.

Read [README.md](README.md), then only the research documents relevant to the task:

- [Research index](research/README.md): collected repositories, manuals and tools.
- [Initial findings](research/notes/collection/initial-inspection.md): confirmed behavior and gaps.
- [Capability map](research/notes/collection/capability-map.md): proposed workflows and source entry points.
- [Investigation procedure](research/notes/replay/investigation-procedure.md): controlled experiments and evidence requirements.
- [Serial run findings](research/notes/replay/serial-experiment.md): E004/E008 commands, final-time checks and remaining warnings.
- [First CLI slice](research/notes/verification/cli-first-slice.md): implemented contract, public-command native replay and limits.
- [E009/E011 findings](research/notes/verification/failure-cancellation-experiment.md): native failures, forced stops, partial outputs and process ownership evidence.
- [Toolbox](research/notes/collection/toolbox.md): available inspection utilities and their usage.
- [Source registry](research/sources.json) and [lock](research/sources.lock.json): provenance and exact acquired revisions.

Search the relevant files instead of loading whole manuals, inventories, or
source trees. Use `rg --no-ignore` when searching artifacts excluded by Git.

## Architecture direction

- Use explicit input files and native engine interfaces as the core control surface.
- Treat the Windows GUI as a reference for model construction, validation, export,
  and execution. Record how its behavior maps to files and engine calls.
- Evaluate `DeltaShell.Console.exe` as an optional project import/export bridge.
  Project create/save/reopen/export and scripted GUI-hosted export now work for
  the controlled f34 fixture; see the E001/E002 findings for required settings.
- Start batch execution with owned subprocesses. Put future BMI/DIMR stepping and
  variable exchange in a separate worker with an explicit lifecycle.
- Evaluate HYDROLIB-core for typed file validation, MeshKernel/MeshKernelPy for
  meshing, and dfm_tools/xugrid for data processing. Collected revisions are
  research references, not an approved or tested application dependency set.
- Python 3.12+, setuptools packaging and standard-library argparse implement the
  initial CLI. Keep inspection/editing independent of research checkouts. The
  optional `run` extra provides the NetCDF reader used for output verification;
  the broader integration libraries above remain research references.

## Evidence and version discipline

Distinguish observed runtime behavior, documentation claims, static code analysis,
and implementation proposals. Support findings with a source commit and file/line,
manual section and PDF page, or an experiment ID with retained artifacts.

The installed suite observed on 2026-11-03 is **2026.02 OpenHMWQ**. Its FM engine
reports `1.2.184.Unknown`; do not infer its source commit from the suite version.
The collected engine release is `DIMRset_2026.02`; see the lock for its SHA.
Discover current installations and capabilities instead of hardcoding this machine.

Keep GUI version, executable version/hash, source revision, input format version,
and helper-library version separate. Check actual options and DLL layout for the
selected installation. For example, this DIMR executable rejects `--help`, and
the 2026.02 GUI expects native libraries under `lib`.

The MDU candidate index is incomplete. An advertised option, exported symbol,
successful decompilation, or console print does not establish a working modeling
capability. E001/E002 established scripted GUI/console project export for one
fixture; E004/E008 verified short serial direct-FM and single-component DIMR
runs of that fixture. Complete source builds remain unverified.

Read [E001/E002 findings](research/notes/replay/export-experiment.md) before using the
console bridge. In this installation, set `persistenceDefault` and
`useNewPersistence` in the script before project operations: command-line app
settings are applied too late. Console script exceptions can return exit code 0,
so require a completion result and inspect artifacts. GUI/console export can
migrate and reorder MDU fields; it is not a preservation-oriented setting editor.

Read [E003/E005 findings](research/notes/replay/edit-experiment.md) for the verified edit
mappings. In this suite bridge, change the owning `HisOutputDeltaT` TimeSpan for a
history-interval edit; setting raw `HisInterval` alone did not survive export.
Harmonic API frequency is in deg/h while this BC stores period in minutes;
support-point API indices are zero-based. Verify the written value/cell and all
non-target metadata and signals. Run shell experiment cases sequentially until
shared scratch-directory isolation is understood; one concurrent startup failed.

Read [E004/E008 findings](research/notes/replay/serial-experiment.md) for the verified
native commands and child environment. Both routes reached 600 seconds with
matching NetCDF variable values. Check CF time units/calendar and actual final
history/map/restart times; log banners differ between routes. UUID provenance can
change file hashes without changing variable data. Preserve legacy-format,
deprecated-key and projection diagnostics; CRS correctness remains unverified.

## Working on models and GUI behavior

- Use fresh projects or copied official examples under `research/experiments/`.
  Existing user projects, including unsaved GUI sessions, are not test fixtures.
- Run one controlled operation per experiment. Keep baseline and changed inputs,
  file snapshots, relevant traces/logs, and the interpreted difference.
- Separate GUI project save (`.dsproj` and associated data) from exporting a
  complete engine input set. Follow file references rather than copying only MDU.
- Preserve unknown keys, comments, ordering, numeric precision, and repeated
  blocks/columns. Generic INI rewriting can destroy BC and other file semantics.
- Resolve paths using the selected model/version's rules, including
  `PathsRelativeToParent`. Distinguish old and new EXT formats by content/settings.
- Read units, BC time origins, relative/absolute model dates, CRS and vertical datum
  explicitly. Do not guess them or apply defaults to an existing calibrated model.
- Keep raw GUI decompilation and installed-program artifacts in ignored local
  evidence. Implement from documented behavior and appropriate source interfaces.
- Use supported Computer Use tools for live Windows UI inspection. Prefer native
  files, source, console, and engine interfaces for repeatable automation.

## CLI behavior to implement

- Provide structured JSON results/errors, documented exit codes, and optional
  JSONL progress. Keep logs separate from machine-readable stdout.
- Expose discoverable commands, parameters, schema/capability information, and
  explicit limitations so an AI agent need not guess.
- Support previews and explicit application of edits without interactive prompts.
  Restrict each change to the requested fields and preserve unrelated content.
- Give every run a manifest with input fingerprints, selected executable/hash,
  argument array, working directory, relevant environment overrides, and output/log paths.
- Pass subprocess arguments as arrays and scope environment changes to children.
  Track run-owned processes and cancel only that process tree.
- Report syntax validation, reference validation, semantic checks, engine
  initialization, completed simulation, and scientific validation separately.
- Verify completion against the requested final simulation time and output time
  axis. File existence or process exit alone does not establish completion.
- Start with short serial cases. Add DIMR, MPI, restart and component coupling
  through separate reproducible cases. Initialization may itself write files.

## Repository and development workflow

Keep project code, documentation, schemas, and small portable fixtures reviewable.
Downloaded upstream checkouts, tools, manuals, raw evidence, virtual environments,
and experiment outputs are excluded by `.gitignore`; do not add them wholesale.
Record upstream revisions and local artifact hashes when acquiring new references.
Treat upstream research checkouts as references and avoid incidental edits there.

The current environment is Windows/PowerShell with Python 3.12. From the root:

```powershell
# Application development (a separate local venv):
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[run]'
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/dfm.exe schema inspect
python -m compileall -q src tests research/workflows research/scripts

# Only if the isolated research environment is missing:
python -m venv research/.venv
research/.venv/Scripts/python.exe -m pip install -r research/requirements.txt

# Research utility syntax and collected-artifact checks:
python -m compileall -q research/workflows research/scripts
python research/scripts/audit_research.py
```

The audit requires locally collected artifacts. On a fresh checkout, follow the
research index for acquisition first; missing artifacts are not CLI test failures.
Run `build_catalog.py` only when intentionally refreshing the acquisition lock and
candidate index. The current audit does not validate any simulation.

For native application integration use the application venv with `.[run]` installed. Use the commands in the [experiment index](research/notes/experiments.md). Each replay creates fresh baseline copies and run folders. Portable
tests generate their own inputs and do not require the installation or research
artifacts. Keep exit codes/JSON errors, preview hash checks and byte preservation
covered when changing edits. `run status` reads recorded state and additionally
checks PID/creation-time identity for active records. `run cancel`
requests a stop from the live owning controller; it never kills an arbitrary
manifest PID. No daemon, adoption or resume exists. Each native launch is assigned
to a private Windows Job Object before its first thread resumes. Preserve member
handle exit confirmation and empty-job checks; the root exiting or PID list
emptying alone is insufficient. Never reintroduce process-name/tree killing by
unverified recorded PID.

E009/E011 replay: `.venv/Scripts/python.exe
research/scripts/verify_failure_cancellation.py --baseline <baseline-folder>
--install <suite-root> --out <new-experiment-folder>`. This uses copied inputs and
same-executable native controls. Keep `failed`, `timed_out`, `cancelled`,
`cleanup_failed`, and read-only effective `owner_lost` distinct. Collect diagnostic
context and partial outputs on every native terminal path; forced termination
does not establish clean finalization, usable restart or scientific validity.

Run checks appropriate to the change. Documentation edits need link/content checks;
model editing needs meaningful preservation/reference checks; execution changes
need bounded integration cases. Add application development/test commands here
when they exist. Report changes, evidence, checks, and remaining uncertainties.

Research code lives under `research/workflows/{collection,replay,verification}`; invoke canonical tools with `python -m research.workflows.<group>.<name>` from the root. Legacy script paths forward to the same modules. Preserve the original experiment folders and the independent numerical comparator. A fresh CI environment can run unit tests without local suite artifacts; the native release check requires both replay commands in the experiment index.

## Next milestone

Establish one reproducible **export -> inspect -> edit -> validate -> run -> verify**
workflow before expanding feature coverage:

1. E001/E002 are complete for scripted GUI-hosted and console operations on the
   copied f34 fixture, with a second fresh replay. Reuse the documented baseline
   and replay scripts; interactive menu/dialog behavior remains untested.
2. E003/E005 are complete for the f34 history interval and one harmonic support
   amplitude, with separate control/case copies and a fresh sequential replay.
   Reuse the findings and scripts; modified-project save/reopen and other edit
   types remain untested.
3. E004/E008 are complete for the copied f34 short serial case, including final
   output times and direct-FM/DIMR data comparison, repeated with an explicit
   PROJ resource path. E007 GUI helper tracing remains separate and untested.
4. The first CLI slice is implemented and verified through public commands on
   the copied f34 fixture: install/model inspection, preserved preview/apply,
   partial validation and bounded serial direct/DIMR run/status. Its profile is
   explicit and limited; expand file coverage, failure/cancellation evidence and
   durable worker ownership through separate verified increments.
5. E009/E011 verified corrupted mesh/empty BC initialization failures, timeout,
   cooperative forced cancellation, native descendant ownership and controller
   loss on the serial fixture, with separate same-executable controls surviving.
   Full BC semantics, terminal Ctrl+C delivery, graceful native shutdown, MPI and
   coupled cancellation remain separate work.

Completed scopes above are fixture-specific. Consult the experiment
queue and capability map for later MPI, restart, meshing, and coupled workflows.
