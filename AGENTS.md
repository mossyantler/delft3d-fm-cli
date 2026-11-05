# Agent guide

## User-requested checkpoint

The user explicitly resumed work on 2026-11-05 in Herdr and authorized Claude
Code Sonnet 5.5 with high effort as an additional subagent option. Read
[RESUME.md](RESUME.md) and its checkpoint before continuing. Pending code under
`research/checkpoints/` is not accepted product code. Preserve the immutable
checkpoint; prepare new candidates separately and retain existing review gates.

### Herdr subagents

Codex and Claude Code may both perform assigned I/V work; keep independent
verification separate from authorship and serialize shared Git operations here.
For Claude use `herdr agent start <name> --kind claude --pane <available-pane>
-- --model claude-sonnet-5-5 --effort high`. Verify the startup banner and response;
do not silently substitute another model. Herdr 0.9.5 and Claude Code 2.1.318
were observed at resumption; discover capabilities again on another machine.
Read AGENTS.md explicitly in each Claude assignment. Give each worker a node,
owned paths, prerequisites and validation scope. Native slots still require the
coordinator's package/runner/reader review. Resolve the actual caller pane from
live agent state when inherited HERDR pane/workspace variables are stale.

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

For B13 input replay use the [portable three-case preparation](research/notes/verification/layers.md#portable-b13). Keep the historical #203 producer and independent numerical reader at their pinned paths.

For B12, `boundary preview` reads only the MDU/new EXT/PLI/BC input graph.
Keep a missing signal separate from zero and distinguish source-based evaluation,
installed-engine prescribed levels and receiving-station results. Preserve the
[two-file correction regression and raw input controls](research/notes/verification/boundary-preview.md).

For existing observation XYNs use `observation inspect/add/move`; the [raw history/map comparisons and 256-byte record boundary](research/notes/verification/observation-points.md) explain the tested geometry and serialization. `CrsFile` is an observation cross-section file. For a serial launch preserve the [FM Program identity gate](research/notes/verification/fm-model-identity.md) on the original and staged MDU. File-only inspection and preservation edits must continue to work on incomplete inputs.

For standalone `observation export` bind the MDU and XYN only; import validates the connected graph, source and all positions with one prepared mesh. `section reverse` changes only the selected CrsFile record bodies; an absent ObsFile is not an error. [G10/G12 file and native replay](research/notes/verification/spatial-transfer.md).

For 2D pumps distinguish the structure-relative reported sign from discharge in a fixed geographic direction. [G13's original NetCDFs](research/notes/verification/pump-orientation.md) reject a polyline-only hydraulic reversal on a four-link constant-capacity fixture. Do not expose such a reversal or rescale capacity from this observation. Check both banks' storage and a stationary control.
The public `pump inspect MDU [--id ID]` is read-only. `pump set` previews or applies exactly one existing orientation or signed capacity token; its `result.sha256` binds the request and input graph. Preserve ordinary file permissions and reject unsupported permissions before staging. `run start --profile pump-scalar --route direct` uses all six inputs, rechecks source/staged identities before launch and confirms member exits and the original Job close before recording completion. Keep the default short profile unchanged. [Installed replay, physics and terminal publication checks](research/notes/verification/pump-orientation.md#public-pump).

The [module evidence index](research/catalog/module-gates.json) records raw-output checks for the two directions of bounded FM–Waves exchange, in-kernel nitrification and BMI observation reads. Preserve each profile's mechanism and clock: stationary Waves samples start each scheduled interval; a process timer can count initialization separately from regular computation. The BMI clock gate checks observation reads against the NetCDF storage precision. A successful read does not establish that a controlled structure actually responded to a write. For morphology, keep the native signed section counters separate from dry stock: a frozen MorFac=0 bed can report transport without updating stock. The [two-design eight-case replay](research/notes/verification/morph-trial.md) checks both and joins final restart cells by physical coordinates. The separate DELWAQ 06 positive/control replay uses model-local time, 1,130 segments and retained volume records. Preserve duplicate non-target statistic columns by ordinal and refuse ambiguity in a physical target name.

Before extending a GUI workflow, look up its task ID in the
[GUI/console workflow inventory](research/notes/collection/gui-workflows.md).
Keep that ID attached to the file changes, pinned engine entry points, public
command contract and experiment evidence in the roadmap. The
[M0 inventory audit](research/catalog/gui-workflows-audit.json) checks the table's
structure and references; it does not certify GUI behavior or engine equivalence.

For B06, `source inspect/add/set/forcing-create` separates one preserved EXT edit
from creating a fresh BC. Bind apply to the exact preview `result.sha256`, full
input graph, request and destination. Preserve the ordered intake/outfall
coordinates and BC Name = SourceSink ID; do not append a boundary support suffix
or alias `salinity` to `salinityDelta`. The [six public-input trials](research/notes/verification/source-sink.md#public-225)
qualify a bounded inline 2D source case through a research runner, not a new
public run profile or GUI export. Reject decoded unsafe text before staging.

For G16 use the [existing 2D weir TIM example](examples/weir_series/README.md).
The three public `weir series-*` commands are file operations with explicit units and UTC origin. Keep the 0 s native history distinct from the authored first knot. The editor does not validate GUI CSV equivalence or qualify a run profile. For a matching 11-file, 48-cell channel use `run start --route direct --profile weir-series`; the [public replay](research/notes/verification/weir-crest-series.md#public-run) compared all 189 variables per case, without certifying a hydraulic sign or GUI equivalence. Preserve the distinct pump/weir lifecycle keys.

For B13, use `boundary vertical-inspect/vertical-set` on an existing T3D
salinity cell. Bind preview/apply to `result.input_sha256`, the exact authored
time and position tokens, units, selected support, input graph and file
permissions. `VertPositionIndex` selects a BC value column; it is not a model
layer index. Do not renew generation sidecars after an edit or infer GUI export
behavior from the [three 20-second runs](research/notes/verification/layers.md#b13).

For B03 use `boundary series-set` for values at existing times, and
`boundary series-rows` for explicit insertion/deletion. A rows preview binds
the point, graph and request to the exact new BC and operation; do not reuse an
inspection hash. Preserve other lines and time coverage. The [installed CLI and
manual controls](research/notes/verification/boundary-series.md) distinguish
byte preservation, native results, and untested GUI behavior.

For O03/O04, use `model set` for the existing `output/Wrishp_obs` or
`output/Wrihis_balance` scalar, with exactly `0` or `1` for both the old and
new token. The preview hash is the MDU SHA-256. Preserve unrelated repetitions.
`model fields` points to this command separately from its `field-set` eligibility.
See the [installed CLI / manual f34 comparison](research/notes/verification/output-toggles.md)
for actual sidecars, variables and the unverified GUI scope.
For [location import](research/notes/verification/boundary-locations.md) and
[support/function edits](research/notes/verification/boundary-support.md), remove
retired forcing blocks from the active BC stream and retain the originals in the
archive or loss receipt. A commented block after active numeric data can change
results even when FM exits 0. Keep a target-last control with unequal surviving
signals, verify CF clocks and compare the complete native arrays. Horizontal PLI
conversion needs the optional `geo` extra, explicit source/target EPSG and XY
units and matching actual NetFile CRS metadata; the `as-is` path requires none
of those optional libraries and does not infer a datum.
Keep observed GUI/console changes separate from engine-only evidence and proposed commands. For P01–P04 see the [verified console round trip and limits](research/notes/verification/project-bridge.md). For R08 see [the two-rank MPI scope](research/notes/verification/parallel-trial.md); for S02/S03/S06 see [the three-layer salinity case](research/notes/verification/layers.md). E007 must trace Run on a fresh, owned GUI and project before identifying its helper or assigning GUI execution parity.

CLI 0.4.0.dev1 retains JSON protocol 2 and manifest 3. See the [bounded field editor](research/notes/verification/fields.md) and [native network controls](research/notes/verification/network-exchange.md) before broadening those commands. See the [release verification and migration](research/notes/verification/cli-03.md) and [experiment index](research/notes/experiments.md). Keep historical manifests read-only. A process lookup failure is never proof that a process exited.

For performance work use the [0.3.1 scale benchmark](research/notes/verification/cli-scale-031.md): measure MDU, NetCDF and logs in separate processes on identical inputs. Preserve diagnostic context, markers and file hashes when changing the scanner.

For E014, `model fields` describes MDU text only. A static editor is not a validated edit: use `edit_eligibility.state` and inspect the connected input/candidate preview. See the [three concrete models](research/notes/verification/fields.md). For B09, keep the selected PLI's imports distinct from other boundaries sharing its BC; pass both [the independent checks and manual-mode comparisons](research/notes/verification/boundary-import.md) before accepting any expanded merge policy.

B04 `boundary export` collects active BC blocks and PLI locations into a fresh directory. Process groups require an explicit map; never infer GUI process membership. Preserve source block bytes, inventory and staging ownership. See [four-group export checks](research/notes/verification/boundary-export.md). For a forced stop, unavailable or foreign member handles cannot prove exit; observe the request return and the retained original handles separately ([E011 follow-up](research/notes/verification/job-force.md)).

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
- Batch execution uses owned subprocesses. The isolated BMI worker supports the checked 48-cell weir control and observation reads; see [physics and lifecycle evidence](research/notes/verification/live-worker.md). Keep other live interfaces in a separate worker with an explicit lifecycle.

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

### Git checkpoints for task nodes

Every completed agent work node, including implementation (I), independent
verification (V), integration (G), and documentation/research nodes, MUST have
at least one non-empty Git commit before it is reported complete. Include the
node ID in the commit subject, for example `fix(SHORT-CLOSE-I): verify closure
before completion`. Keep each node's changes separate; one bulk commit must not
substitute for commits for several completed nodes.

In the shared checkout, the coordinator serializes staging, commits and pushes.
Agents submit their node ID, owned paths, patch and validation results; they must
not manipulate the shared index concurrently. An explicitly assigned isolated
worktree may commit on its own branch. Commit only the node's reviewed files.
For ignored local experiments, commit a small portable findings/provenance index
with evidence references instead of force-adding raw artifacts or making an
empty commit. A committed candidate is not automatically accepted product code.

Minimum workflow for each node:

1. Inspect `git status --short` and `git diff -- <node-owned-paths>`. Check that
   any staged changes belong to this node; preserve other workers' changes.
2. Run the checks appropriate to the node and review their actual results.
3. Stage explicit paths with `git add -- <node-owned-paths>`, inspect
   `git diff --cached`, and commit with `<type>(<node-id>): <concrete change>`.
4. Report the node ID, commit hash and validation scope in its handoff or
   [delivery graph](DELIVERY.md). Do not mark the node complete without its commit.
5. After integration approval, fetch the selected remote, check the branch and
   upstream, and push the approved commits with `git push origin <branch>`.
   Verify the remote branch SHA matches the intended local commit. Keep pushes
   fast-forward; do not rewrite published history to combine node checkpoints.

The current environment is Windows/PowerShell with Python 3.12. From the root:

```powershell
# Application development (a separate local venv):
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[run]'
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/dfm.exe schema inspect
python -m compileall -q src tests research/workflows research/scripts

# Build a snapshotted wheel and verify a clean install outside the checkout (optional):
.venv/Scripts/python.exe -m research.workflows.verification.verify_wheel --out research/experiments/<fresh-package-check>

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

Use the [product roadmap](ROADMAP.md) and [delivery graph](DELIVERY.md) for dependencies, write ownership and review gates. [M1–M3 product verification](research/notes/verification/roadmap-2d.md) covers the harmonic edit, scalar 2D results and a relocatable synthetic channel; do not generalize to other CRS or boundary functions. M4 planar mesh replacement passed its separate native and topology gates; M5's opt-in extended profile passed the 1,200-second authored case, forced cancel with same-executable control, timeout and raw NetCDF checks. A signal request is still not proof of cancellation. The milestones below preserve the earlier research scopes.

For [B03](research/notes/verification/boundary-series.md), bind a preview to the actual request bytes as well as the connected files and selected point. For [O02](research/notes/verification/checkpoint-schedule.md), keep the default final-checkpoint requirement separate from the opt-in configured schedule. A clean run with restart output disabled has verified history/map clocks and no checkpoint to resume from. Cold short serial launches trace Job members before resume; an empty Job alone is not a retained-handle proof.

For [B11](research/notes/verification/boundary-coefficients.md), keep a coefficient before the first Quantity, preserve raw rows, and do not generalize linear-scalar behavior to other BC functions. For `results stations`, require physical polygon identity and the actual all-times history/map join; distinguish masked, absent and unproven. Keep all CRS rechecks even when streaming the mesh without retaining bytes. [Release scope and receipt hashes](research/catalog/coefficients-stations-gates.json).

The first reproducible **export -> inspect -> edit -> validate -> run -> verify** workflow covers these fixture-specific cases:

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
