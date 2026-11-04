# Capability and implementation map

Implemented commands are `install discover/inspect`, `schema inspect`, `model
inspect/validate/set`, and `run start/status/cancel`, with the limited contract described
in [the first CLI slice](../verification/cli-first-slice.md). Other names and broader behavior
below remain proposals. Source paths are relative to the corresponding checkout
in `research/upstream/`.

## Interfaces to build around

| Layer | Role | Evidence / confidence |
| --- | --- | --- |
| Explicit model files | Durable editable model state and dependency graph | Manuals, native reader/writer source, HYDROLIB serializers; high confidence |
| Native subprocesses | Batch runs, partitioning, logs, process lifecycle | E004/E008 completed serial runs; E009/E011 verified native failures, forced job termination, descendant ownership and unrelated native survival; MPI untested |
| Native API worker | Initialize, update, current time, variable exchange | DLL exports, source and GUI wrapper inspected; worker integration untested |
| Delta Shell console | Optional `.dsproj`/GUI workflow bridge | E001/E002 verified project create/save/reopen/export for the f34 fixture; broader workflows untested |
| Windows GUI | Reference outputs and experimental comparison | One live model surface inspected; complete control coverage untested |

The initial CLI should discover capabilities per installation. GUI version, kernel
version, binary hash, source revision, schema version, and helper-library version
must remain separate fields. A missing source revision is an explicit unknown.

## Workflow coverage

| Proposed workflow | Inputs / products | Best implementation reference | Remaining discovery |
| --- | --- | --- | --- |
| `dfm install inspect` | Installation root, executable/DLL paths, versions, capabilities | Local `product.json`, PE metadata, launcher scripts, console/engine help | Multiple installations and missing runtime diagnostics |
| `dfm schema inspect` | Supported sections, keys, types, units, constraints | FM `unstruc_model.f90`; HYDROLIB `dflowfm/mdu/models.py`; manuals | Reconcile candidate key sets per engine version |
| `dfm model inspect` | MDU and complete referenced-file graph | HYDROLIB base file manager; native model/file resolution source | Path modes, aliases, cycles, external resources |
| `dfm model set` | Local value changes and reviewable diff | Implemented byte-splice preview/apply with input hash; E003 property probe | More fields, multiple-value windows and broader native semantic validation |
| `dfm model validate` | Syntax, references, semantic checks, optional initialization | HYDROLIB parsers/validators; engine initialization | Distinguish validation levels and side effects |
| `dfm model create` | Versioned templates and complete input sets | Official example models; native writer; HYDROLIB models | Minimum runnable 2D/3D cases and explicit CRS/datum |
| `dfm boundary create/edit` | EXT, BC, PLI and referenced data | E005 harmonic cell edit and sparse-point/frequency mapping; HYDROLIB and native EC module | Other functions, new boundaries, corrections, snapping and run validation |
| `dfm initial edit` | Initial fields, bed levels, physical parameters | HYDROLIB `inifield`, `friction`, `onedfield`; FM manual | Spatial methods, missing data, datum, quantity units |
| `dfm structure edit` | Structures, cross sections, storage nodes, laterals | HYDROLIB `structure`, `crosssection`, `storagenode`; FM/1D source | Cross-file IDs, topology, coupled behavior |
| `dfm mesh create/edit/check` | 1D/2D/curvilinear meshes and quality metrics | MeshKernel API, MeshKernelPy, HYDROLIB net I/O, RGFGRID manual | Versioned algorithms, CRS, quality thresholds and export parity |
| `dfm mesh link/refine` | 1D/2D connections, refinement and derived networks | Installed FM options; native geometry code; MeshKernel | Explicit output paths and geometry invalidation |
| `dfm project import/export` | `.dsproj`, `.dsproj_data`, exported model inputs | E001/E002 replay scripts, Delta Shell model exporters and persistence plugins | Other model types, interactive dialogs, unknown-key preservation, external linked files |
| `dfm run start/status` | Run manifest, working folder, stdout/stderr, outputs | Synchronous Job Object ownership, active-record identity observations, E004/E008 completion and E009/E011 failure records | Durable background worker, live model-time progress and broader models |
| `dfm run cancel` | Native worker/process lifecycle, partial outputs | Implemented live-owner request and forced job stop; E011 same-executable controls, descendant and owner-loss tests | Graceful shutdown, terminal Ctrl+C delivery, MPI and coupled cancellation |
| `dfm run partition` | Partitioned MDU/mesh, MPI rank allocation | FM partition option; official parallel example; DIMR config | Cross-platform launch, rank agreement, map/history ownership |
| `dfm run restart` | Restart files and correct time/model state | FM restart source and user manual | Unchanged-grid requirements and repartition behavior |
| `dfm couple configure` | DIMR XML, components, clocks, couplers | DIMR schemas and `packages/dimr_lib`; HYDROLIB DIMR model | Coupling values, units, scheduling, rank semantics |
| `dfm results inspect/export` | NetCDF history/map/restart, time ranges, station data | E004/E008 NetCDF time/mask/value comparison; dfm_tools, xugrid and FM output source | Parallel output assembly, broader variable locations and lazy reads |
| `dfm diagnose` (proposed) | Configuration/run errors, warnings, requested vs actual time | E009/E011 primary error/context and partial time axes already included in run JSON/manifests | Dedicated diagnose command, broader versioned patterns, complete BC/file semantics |
| Morphology / Waves / WAQ / RTC / RR extensions | Component-specific inputs, resources, coupling, outputs | Collected engine components and corresponding manuals | Separate component validation and end-to-end cases |

## Exact source entry points

[E004/E008 findings](../replay/serial-experiment.md) establish 600-second completion and
agreement across 191 output variables for one serial fixture, with projection,
legacy output format and deprecated-key diagnostics retained. This does not
establish physical validity, a model created from scratch or other run modes.

Within **Delft3D**:

```text
src/engines_gpl/dflowfm/packages/dflowfm-cli_exe/src/net_main.F90
src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/read_commandline.F90
src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/print_help_commandline.F90
src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90
src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_utils/unstruc_files.f90
src/engines_gpl/dflowfm/packages/dflowfm_lib/src/unstruc_bmi.F90
src/engines_gpl/dflowfm/scripts/runscripts/
src/engines_gpl/dimr/packages/dimr/src/dimr_exe.cpp
src/engines_gpl/dimr/packages/dimr_lib/
src/engines_gpl/dimr/schemas/
src/engines_gpl/dimr/docs/source/DIMRAndBMIDesign.md
src/utils_lgpl/ec_module/
src/utils_lgpl/io_netcdf/
src/utils_lgpl/gridgeom/
src/utils_gpl/morphology/
examples/dflowfm/01_dflowfm_sequential/
examples/dflowfm/02_dflowfm_parallel/
doc/compiling_Windows.md
doc/compiling_Linux.md
```

Within **HYDROLIB-core**:

```text
hydrolib/core/base/file_manager.py
hydrolib/core/base/models.py
hydrolib/core/dimr/models.py
hydrolib/core/dflowfm/mdu/models.py
hydrolib/core/dflowfm/bc/models.py
hydrolib/core/dflowfm/ext/models.py
hydrolib/core/dflowfm/extold/models.py
hydrolib/core/dflowfm/polyfile/
hydrolib/core/dflowfm/net/
tests/
```

## Implementation decisions to preserve

1. Keep schema validation, reference validation, engine initialization, successful
   completion, and scientific validation distinct in JSON results.
2. Read existing unknown keys without silently dropping them. Generic INI parsers
   are insufficient for repeated BC blocks and repeated quantity/unit entries.
3. Model paths form a graph. Respect the selected version's relative-path rules;
   copying an MDU alone does not copy a model.
4. Treat dates, relative time units, BC time origins, output intervals, model CRS,
   display CRS, and vertical datum as different concepts.
5. Give each run an explicit input snapshot, working directory, executable hash,
   argument array, relevant environment overrides, log locations, and output list.
6. Use argument arrays and process-scoped environments. Track owned child
   processes; never cancel by killing every process with a shared name.
7. Provide JSON discovery/errors, stable exit-code categories, optional JSONL
   progress, and a preview/apply workflow for edits and generated files.
8. Begin with one small serial model, then add DIMR, MPI, restart, and component
   coupling as independently verifiable capabilities.

These are proposed CLI contracts. The available sources do not justify a claim
that every GUI function can already be reproduced through one engine API.
