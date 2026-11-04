# Initial installation and interface findings

Observed 2026-11-03. Evidence paths below are relative to `research/`.

Follow-up: [E001/E002](../replay/export-experiment.md) subsequently verified scripted
GUI-hosted project save/export and console project create/reopen/export on a
copied official fixture. [E003/E005](../replay/edit-experiment.md) verified two isolated
edit/export mappings. [E004/E008](../replay/serial-experiment.md) verified short serial
direct-FM/DIMR runs and final output times. The untested items below describe this
earlier baseline; current limitations are recorded in those follow-up reports.

## 1. Installed target and provenance

Installed suite:

```text
<Delft3D suite installation root>
```

Two existing `DeltaShell.Gui.exe` processes were found. The visible window was an
unsaved `garolim*` project. It was inspected without saving, exporting, editing its
model values, or starting a simulation.

The GUI config reports release `2026.02`, distribution `OpenHMWQ`, a .NET Framework
4.6.1 target, and `.dsproj` persistence. The installation inventory contains 2,928
files. Selected PE/CLR inspection covers 47 binaries, including the
console, GUI plugins, native FM executable, FM DLL, and NetCDF DLL.

The FlowFM and DIMR plugins report version `4.19.0.9954.d10f019`. Other shell
plugins report a different component version. These are component versions, not
the FM engine version.

The installed FM executable reports:

```text
D-Flow FM Version 1.2.184.Unknown, Aug 11 2026
Source: Unknown
```

Therefore its exact source commit is **not established**. Binary hashes are saved
so future compatibility claims can refer to the actual installation.

The collected engine source is the official `DIMRset_2026.02` tag, commit
`5a4649830b1e5072caf019fb4850bbdefd9ad431`. Deltares recommends matching a GUI
release to its corresponding DIMRset tag. Its current GUI integration document
also notes that Windows libraries moved from `lib` to `bin` after 2026.02, while
the 2026.02 GUI expects `lib`. This is directly relevant to discovery logic.

Sources: [official GUI integration guidance](https://github.com/Deltares/Delft3D/blob/main/doc/guis_for_open_source.md),
`evidence/installation/product.json`, `binaries.json`, `files.json`, `processes.json`,
and `help-probes/dflowfm-cli.exe-version.stdout.txt`.

## 2. GUI surface observed

The FlowFM project tree exposed General, Area, Grid, Bed Level, Time Frame,
Processes, Initial Conditions, Boundary Conditions, Physical Parameters, Sources
and Sinks, Laterals, Numerical Parameters, Output Parameters, and Output.

The current map view also exposed GIS, spatial operations, a property panel, and
an operations panel. This confirms a broader workflow than editing MDU scalars:
the CLI will also need geometry, input-data preparation, output inspection, and
model-file dependencies.

The Windows accessibility snapshot returned no tree for this window; inspection
used screenshots. Robust core automation should use file/engine interfaces.
No claim is made that every GUI dialog or operation has been inspected.

## 3. Existing Delta Shell console is a real bridge

The installation contains `bin/DeltaShell.Console.exe`. Its actual help lists:

| Option | Advertised purpose |
| --- | --- |
| `--project`, `-p` | Load a project |
| `--run-activity`, `-r` | Run an activity or model in a project |
| `--run-file`, `-f` | Execute a script file |
| `--run-command`, `-c` | Execute a Python command |
| `--interactive`, `-i` | Start a scripting console |
| `--skip-default-libs`, `-s` | Skip standard Python libraries |
| `--app-setting`, `-a` | Supply an application setting |
| `--culture-name`, `-cn` | Select culture |

Only the help and print-command routes were exercised. Project load, activity
execution, import, and export through the console remain untested.

The following command returned exit code 0 and printed the expected marker:

```powershell
& '<install>\bin\DeltaShell.Console.exe' --skip-default-libs --run-command "print('DFM_CLI_RESEARCH_CONSOLE_OK')"
```

An initial help probe logged native/managed assembly scanning errors; the latest
saved help probe completed without those errors. The initial verbose startup
output was observed in the tool transcript but was overwritten before probe
history retention was added. The print probe
with `--skip-default-libs` had no `ERROR` lines but still reported ten dependency
warning lines, including some incompatible numerical-library DLLs. The successful
print demonstrates command execution, not that all toolbox functions work.

The scripting plugin contains IronPython 2.7.12. Targeted inspection of `ScriptHost`
shows injection of `Application`, optionally `Gui`, and `CurrentProject` when a
project is open. GUI presence must not be assumed in console scripts.

Sources: `evidence/console-probe/`, console help output,
`evidence/managed-inspection/ScriptHost.cs`; Delta Shell User Manual chapter 8,
especially printed pp.86-87 / PDF pp.97-98.

## 4. The GUI run path uses DIMR's API

Targeted ILSpyCmd inspection succeeded without decompilation errors for these
types: `DimrRunner`, `DimrApi`, `RemoteDimrApi`, `DimrApiFactory`, `DimrApiDataSet`,
`FMModelFileExporter`, `FMModelPartitionExporter`, `BcFileBoundaryExporter`, and
`ScriptHost`. Output remains local under the ignored evidence directory.

The observed `DimrRunner` path is:

1. Validate the model and reject error-severity validation results.
2. Disconnect existing output while preparing a run.
3. Select the model's `IDimrModelFileExporter`.
4. Prepare/clean a model working folder and export the model.
5. Generate `dimr.xml`, including component library, working directory, and input.
6. Create a DIMR API instance and initialize it with the XML path.
7. Obtain the API time step and stop time.
8. Repeatedly update, obtain current simulation time, and process messages.
9. Finalize/dispose and reconnect output/log files.

This is a static reconstruction of the inspected code. No live run trace was
captured, and this path need not cover every integrated-model configuration.

`DimrApiFactory` supports local and remote instances; the runner's default field
value and factory call lead to the remote path. `RemoteDimrApi` uses the shell's
remoting container. **Do not assume GUI Run simply spawns `run_dimr.bat`.** The
exact helper-process launch command and transport have not yet been traced.

`DimrApi` loads `dimr.dll`, sets the working directory during initialization,
sets serial-rank/MPI values for this API route, and calls initialize/update/finalize
and time/variable functions. `DimrApiDataSet` resolves native libraries under
`plugins/DeltaShell.Dimr/kernels/x64/lib`, executables under `bin`, and resources
under `share`.

Implementation implication: start with subprocess runs for durable batch jobs;
add a separate worker hosting BMI/DIMR when stepping, current time, or variable
exchange is required. Native initialization and MPI state belong to a worker,
not a long-lived AI host process. This is an architectural proposal.

## 5. Export is a model-to-files operation

`FMModelFileExporter` accepts a `WaterFlowFMModel`, resolves an MDU export path,
then delegates to model export with `switchTo: false`. The complete export
implementation was not yet followed recursively.

The partition exporter first exports model files and then partitions the network
through the FM API and writes partition MDU files. This means MPI support must
handle the model and referenced inputs, not just append a core count to a command.

The boundary exporter delegates to BC data builders, uses model reference time,
supports multiple-file behavior, filters data types/quantities, and can write a
separate correction BC file. Do not infer that exporting one boundary always
changes exactly one file. The support-point naming builder remains to inspect.

Source: selected exporter `.cs` evidence and assembly hashes in its manifest.

## 6. Native engine interface confirmed

The installed `dflowfm-cli.exe --help` and `--version` both returned 0. Help
advertises autostart/autostartstop, partitioning, OpenMP threads, verbosity,
refinement, 1D/2D-link creation, network saving, bed-level export, cut cells,
geometry cache control, preCICE, and water-quality process-library options.

This proves option advertisement, not successful operation of every option.
Some options overwrite inputs unless an explicit output is provided; future
wrappers should expose an explicit destination and retain the input model.

Native export inspection also found FM initialize/finalize/time/variable APIs and
more specialized mesh/computation functions. Presence of an exported symbol does
not establish argument types, units, valid states, or stability across releases.
Use the release source and test worker for those details.

DIMR's help handling differs from the FM executable:

| Invocation | Observed result |
| --- | --- |
| `dimr.exe --help` | Invalid option; usage; exit 1 |
| `dimr.exe -?` | Usage; exit 1; no stderr |
| `dimr.exe -i` | Reports an argument is required; usage; exit 1 |

The last behavior conflicts with the usage prose. The collected source's getopt
string also marks `i` as requiring an argument. Do not build version discovery on
an untested `-i` assumption. Use PE metadata and run-start logs until clarified.

Saved Windows launchers establish actual environment conventions. `run_dimr.bat`
sets `OMP_NUM_THREADS=1` when absent and prepares bin/lib/share paths. The two
launcher scripts build PATH differently. The CLI should capture a selected
installation and explicit child environment instead of mixing PATH installations.

## 7. Source and schema research now available

Six official repositories are locally checked out and commit-locked. The engine
checkout includes FM/DIMR and selected related components, not every dependency
needed to build the suite. Two official sequential/parallel examples are present.

`catalog/mdu-candidates.json` contains 530 literal `prop_set` section/key pairs from
the engine MDU writer and 456 annotated HYDROLIB MDU fields across 26 classes.
This deliberately remains a **candidate index**, not a generated complete schema:
dynamic section names, research options, defaults, aliases, cross-file validation,
and version differences need separate review.

Ten local official manuals were copied and hash-verified. Text was extracted from
1,636 PDF pages with page delimiters. The PDF extractor reported duplicate
dictionary-key warnings in some source PDFs. Layout, diagrams, and all table
values were not visually verified. Use the PDFs for interpretation.

## 8. Not established yet

- A complete mapping of every GUI control to file fields and kernel behavior.
- Console project import/export and unattended model execution.
- GUI save/export before-and-after file differences or Process Monitor traces.
- Successful standalone, DIMR, MPI, coupled, restart, or cancellation runs.
- NetCDF final-time checks, mass balance, or physical validity of any model.
- A working source build or exact matching of installed binaries to the release.
- Version compatibility of the acquired helper libraries with this engine.

The next experiments are described in [the investigation procedure](../replay/investigation-procedure.md).
