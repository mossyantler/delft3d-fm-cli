# E001/E002: project save, engine export, and console export

**Date:** 2026-11-03, Asia/Seoul. **Result:** completed for scripted GUI-hosted and
console operations, with a second fresh replay. Interactive menus/dialogs and
simulation execution were not tested.

The GUI executable can save a project and export its model through its supported
`--run-file` entry point. The console can reopen that saved project and export
matching model input values. Saving a project and exporting engine inputs are
different products, even though the project data includes an engine input folder.

## Controlled fixture and method

Used a fresh copy of the official `f34` example from:

```text
Deltares/Delft3D @ 5a4649830b1e5072caf019fb4850bbdefd9ad431
examples/dflowfm/01_dflowfm_sequential/dflowfm/
```

This is the collected `DIMRset_2026.02` release. The source copy has ten files. The
imported model reports 258 grid vertices and 479 edges. No model parameters were
intentionally changed, and no calculation was started. Original upstream files and
the copied source inputs remained unchanged by content hash.

Installed GUI: 2026.02 OpenHMWQ; FlowFM plugin: 4.19.0.9954. Installed FM version:
1.2.184.Unknown. The installed kernel's exact source revision remains unknown.

Each host used its own process and experiment folders:

1. Import the copied MDU into a fresh model in a fresh GUI process.
2. Save the GUI project with `Application.ProjectService.SaveProjectAs`.
3. Export twice through `FMModelFileExporter.Export`.
4. Close the experiment project and GUI host.
5. In a console process, open that exact saved project and export twice.
6. Compare file hashes, MDU section/key/value lists, text differences, known input
   references, and project snapshots before/after console export.
7. Replay the GUI/console sequence in a second freshly prepared folder.

An exploratory console-only case also created a project, saved it, reopened it,
and exported it successfully.

Desktop activation initially failed with access denied and a black capture. Static
inspection showed that the GUI processes script arguments after its main window
loads, so the comparison continued through the existing GUI scripting entry point.
The result records identify `DeltaShell.Gui` and `DeltaShell.Gui.DeltaShellGui`,
distinguishing the GUI host from `DeltaShell.Console`. This is **not an interactive
File/Save As or Export-dialog test**.

## Products observed

| Operation | Product | Observed contents |
| --- | --- | --- |
| GUI project save | `gui-baseline.dsproj` plus `gui-baseline.dsproj_data/` | SQLite3 database and ten model input files |
| GUI engine input export | A standalone export folder | Ten files, including one MDU and nine referenced input/data files |
| Console export of GUI-saved project | Another standalone export folder | Same ten filenames; all MDU section/key values match GUI export |

The project database is 806,912 bytes with 92 tables in this fixture. Read-only
SQLite `PRAGMA integrity_check` returned `ok`. It contains one `projects` row and
one `fm_model` row. Its model inputs are under:

```text
gui-baseline.dsproj_data/f34/input/
```

The database alone is not a portable model. The companion data directory matters.
Database byte equality between separately saved projects was not required or
claimed; the independent saves produced different database hashes.

The exported file set is:

```text
f34.mdu
f34_net.nc
f34_bnd.ext
f34_001.pli
f34_001.bc
f34.wnd
f34_thd.pli
f34_drypoints_dry.xyz
f34_obs.xyn
f34_crs.pli
```

No DIMR XML was produced by this **model-file exporter**. An integrated/DIMR
configuration exporter is a separate route and was not exercised here.

## Comparison findings

| Comparison | Finding |
| --- | --- |
| Saved GUI project's internal input folder vs first GUI engine export | All ten files were byte-identical in the primary experiment |
| First vs second GUI export | Nine files byte-identical; MDU generated timestamp differed; no key/value changes |
| GUI export vs console export of its saved project | Nine files byte-identical; MDU generated timestamp and some key ordering differed; no key/value changes |
| Repeated console exports | Same filenames and MDU key values; generated timestamp may differ |
| Saved project before vs after console reopen/export | All eleven project/data files unchanged, including metadata in the captured snapshots |
| Original source copy before vs after the whole experiment | All ten files unchanged |
| Second fresh GUI/console replay | Confirmed nine identical non-MDU files and zero MDU key/value changes; saved project unchanged |

Nine known input references from the MDU and new-style EXT resolved to files inside
each export folder. This is a scoped reference check, not a complete schema,
boundary-support-point, initialization, or scientific validation.

### Import/export is a migration, not a lossless MDU copy

Comparing the older example input with export from the current plugin found:

- Twelve added keys: seven vertical-layer geometry fields, four history/map output
  fields, and `wind/RhoWaterInWindStress`.
- Removed `output/ClassMapInterval`, whose input value was `0`.
- Changed the recorded GUI/kernel version values to the installed versions.
- Reformatted Dalton and Stanton coefficients from `1.3d-3` to `0.0013`.
- Rewrote the generated header, comments/spacing, and key placement.

The added and removed keys are listed in the
[machine-readable summary](../../catalog/export-experiment-summary.json). No claim is
made that every migration is physically neutral or that this behavior covers
unknown/custom input keys. A CLI editing one existing setting should preserve the
rest of the file instead of silently performing a complete GUI-style rewrite.

## Console requirements and failures retained

The initial `CreateProject()` script failed with `ArgumentException`, parameter
`extension`, while `DeltaShell.Console.exe` still returned **0 with empty stderr**.
The console config does not define the GUI's persistence defaults.

Adding `--app-setting persistenceDefault=.dsproj` did not fix creation in the same
invocation. Inspection of this version's `CommandLineHandler.HandleOptions` shows
that `AppSettings` are applied after script execution. The working script sets:

```python
Application.SettingsManager.SetSetting('persistenceDefault', '.dsproj')
Application.SettingsManager.SetSetting('useNewPersistence', 'false')
```

These calls precede project creation/opening and change this process's application
settings. No installed configuration files were edited. The console then used
`ProjectService.OpenProject` and the same `FMModelFileExporter` used in the GUI host.

CLI implication: require a structured result/completion marker and validate the
expected artifacts. Native console exit status or empty stderr is insufficient.
The research wrapper rejects a run without its completion marker.

Native numerical-library loading warnings and legacy network convention/z-value
warnings were retained in the logs. Successful import/export does not establish
that the model is ready to run, that its bathymetry is correctly interpreted, or
that optional numerical/toolbox libraries are compatible.

## Reproduce

From the project root in PowerShell, select a new, nonexistent experiment folder
and the intended installation:

```powershell
$experiment = 'research/experiments/E001-E002-new-replay'
$install = '<Delft3D suite installation root>'

python research/scripts/prepare_export_experiment.py --out $experiment
python research/scripts/run_gui_export.py --install $install --experiment-root $experiment
python research/scripts/snapshot.py take "$experiment/gui-project" --out "$experiment/snapshots/project-before-console.json"
python research/scripts/run_shell_script.py --install $install --script research/assets/export-experiment/console_export.py --experiment-root $experiment --out "$experiment/console-run"
python research/scripts/snapshot.py take "$experiment/gui-project" --out "$experiment/snapshots/project-after-console.json"
python research/scripts/snapshot.py diff "$experiment/snapshots/project-before-console.json" "$experiment/snapshots/project-after-console.json" --out "$experiment/snapshots/project-diff.json"
python research/scripts/compare_model_exports.py "$experiment/gui-export-1" "$experiment/console-export-1" --out "$experiment/comparison-gui-console"
```

The GUI runner creates a separate host, waits for its script result and process
exit, and bounds its wait. The script closes its own saved experiment project and
window. It does not address existing GUI instances or load a user's open project.

## Evidence and source pointers

Primary artifacts, retained locally under the ignored experiments directory:

- `E001-E002-export-20261103/`: exploratory scripts, failures, GUI/console results,
  SQLite inspection, snapshots, text diffs, and verification report.
- `E001-E002-replay-20261103/`: fresh replay using the tracked portable scripts,
  GUI/console process results, project snapshots, and comparison report.

GUI, console, script, and inspected assembly hashes are included in the invocation
or inspection manifests. Targeted private inspection artifacts include:

| Type/method | Evidence role |
| --- | --- |
| `DeltaShell.Gui.App.App_Startup`, `HandleCommandLineOptions` | GUI script dispatch after main-window loading |
| `ProjectService.CreateProject`, `SaveProjectAs`, `OpenProject` | Project lifecycle and persistence selection |
| `PersistenceFactory.GetDefaultExtension`, `GetSupportedExtensions` | Missing console persistence settings |
| `CommandLineHandler.HandleOptions` | App-setting application order |
| `FMModelFileExporter.Export` | Delegation to `WaterFlowFMModel.ExportTo` with `switchTo: false` |
| `WaterFlowFMModel.ImportFromMdu`, `ExportTo` | Import synchronization and model-to-input writing |

Raw decompiled code remains in ignored local evidence, not application source.

## Next experiment

Follow-up: [E003/E005](edit-experiment.md) completed separate history-interval and
harmonic-amplitude edits on copies of this baseline, including exact deltas and
preservation checks. A separate short engine run must still establish
initialization, final output time, and run validity before this becomes an
executable CLI integration fixture.
