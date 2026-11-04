# Repeatable workflow discovery

The purpose of each experiment is to map **one user operation to files, native
interfaces, and observable results**, then express that behavior as a CLI contract.
Use a fresh project or a copied official example. The user's open unsaved project
was observed only and is not an experiment fixture.

Completed scopes: [E001/E002](export-experiment.md) covers scripted GUI-hosted
save/export and console reopen/export; [E003/E005](edit-experiment.md) covers one
history-interval edit and one harmonic amplitude edit; [E004/E008](serial-experiment.md)
covers a copied f34 short serial run, direct-FM/DIMR comparison and final output
time verification. This does not establish a minimal model from scratch. Other
capabilities in the queue still need their own evidence. [E009/E011](../verification/failure-cancellation-experiment.md)
now covers native initialization failures, serial timeout/cancellation, descendant
ownership, controller loss and surviving same-executable native controls. Run shell-host cases sequentially pending
scratch-directory isolation; preserve any failed attempt separately.

## Evidence record

For each experiment create `research/experiments/<id>/` and record:

```json
{
  "id": "E001",
  "question": "What changes when one selected output interval changes?",
  "gui_version": "2026.02",
  "kernel_version": "1.2.184.Unknown",
  "kernel_sha256": "from installation inventory",
  "source_reference": "commit and file/line or manual section/page",
  "baseline": "path to immutable input snapshot",
  "action": "one exact GUI/console operation and value",
  "observed_files": [],
  "observed_processes": [],
  "observed_api": [],
  "expected_semantics": "units, references, times, outputs",
  "result": "unconfirmed",
  "limitations": []
}
```

Keep observed facts, static code interpretation, documentation claims and CLI
design proposals distinguishable. Include negative and failed probes.

## File experiment

1. Establish a baseline input set and record the versions. If testing GUI export,
   export the unchanged baseline once to account for timestamps/default writing.
2. Take a baseline snapshot. Snapshot JSON must live outside the inspected folder.
3. Perform exactly one selected action in the copied model.
4. Save/export into a separate experiment destination as appropriate. Project save
   and kernel-input export are different operations.
5. Take the new snapshot, compare hashes, then inspect textual/structured changes.
6. Resolve all referenced files, including new BC/PLI/EXT/initial-field files.
7. Cross-check against native source and the matching manual, then record the
   proposed command and validation rules.

```powershell
python research/scripts/snapshot.py take research/experiments/E001/model --out research/experiments/E001/before.json
# Perform the single controlled action in the copied/fresh model.
python research/scripts/snapshot.py take research/experiments/E001/model --out research/experiments/E001/after.json
python research/scripts/snapshot.py diff research/experiments/E001/before.json research/experiments/E001/after.json --out research/experiments/E001/diff.json
```

For NetCDF compare dimensions, topology, attributes, variable location, time units
and data with suitable scientific tools. A changed binary hash does not describe
the semantic change. For BC/EXT inspect repeated blocks and column metadata;
generic INI normalization can hide or lose important structure.

## Execution experiment

Record the actual executable/helper, argument array, working directory, relevant
environment overrides, loaded libraries, input snapshot, start/stop timestamps,
stdout/stderr, diagnostic log, and outputs. Capture the GUI's API-hosted path and
the direct batch path separately.

First use a bounded serial model with a short explicit end time in a scratch
folder. Verify native initialization, final requested simulation time, output time
axis, and process exit. An exit code alone is insufficient to establish completion.
Initialization itself can produce files and is not a read-only validation method.

Only after the serial case is understood, test MPI partition/rank agreement,
cancellation/partial outputs, restart, and online coupling with their own cases.
Run cancellation must target processes owned by that experiment.

## Experiment queue

| ID | Question | Required evidence |
| --- | --- | --- |
| E001 | How do project save and MDU export differ? | Two baseline exports, project/file trees, dependency graph |
| E002 | Can console scripts load and export a fresh project? | Script, console argv/log, exported inputs, GUI-open comparison |
| E003 | Which files change for one MDU scalar? | Baseline/repeat/control snapshots, exact key/value/unit |
| E004 | What is the minimal complete runnable 2D model? | Small grid and boundary data, native run and final output time |
| E005 | How is one boundary serialized? | EXT/PLI/BC blocks, names, quantities, units, reference time |
| E006 | How are CRS, vertical reference and bathymetry represented? | Explicit spatial metadata and exported values |
| E007 | How does GUI Run initialize and launch its API host? | Short Process Monitor trace, actual helper command and modules |
| E008 | How do direct FM and DIMR runs differ? | Same input model, two controlled working folders and outputs |
| E009 | What do failed validation and initialization produce? | Deliberately invalid copied input, exact errors and side effects |
| E010 | How is real progress reported? | Engine time, stdout/dia messages, GUI time display, output time |
| E011 | How should cancellation be represented? | Owned-process lifecycle, partial output and finalized state |
| E012 | How are parallel files and rank lists generated? | Partitioned MDU/meshes, DIMR XML, MPI argv, outputs |
| E013 | Which state is required for restart? | Restart metadata, same-grid check, actual restart interval |
| E014 | Which GUI fields are unsupported by the chosen helper library? | Engine-vs-HYDROLIB field reconciliation and preservation tests |
| E015 | How are Waves/WAQ/RTC/RR components coupled? | Component input sets, clocks, exchange names, small integration runs |

## Completion criterion for one capability

A capability is understood when a small reproducible example, exact versioned
file/API mapping, expected side effects, success/failure observations, and a
reviewable CLI behavior are documented. A screenshot, exported symbol, or method
name alone is a starting point, not completion evidence.
