# Experiment index

Run commands from the repository root. Use new output folders for every replay. Paths under `research/experiments/` refer to local retained evidence, not portable fixtures. Source revisions and acquisition hashes are in the [lock](../sources.lock.json).

| Experiment | Input | Reproduce and interpret | Retained evidence |
| --- | --- | --- | --- |
| E001 / E002: project save and engine export | Acquired Delft3D f34 official example | [Export procedure and commands](replay/export-experiment.md); start with `python -m research.workflows.replay.prepare_export_experiment --out <new-folder>` | `E001-E002-replay-20261103` ([summary](../catalog/export-experiment-summary.json)) |
| E003 / E005: one scalar and one boundary | Fresh copies of `E001-E002-replay-20261103/gui-project` | [Edit replay](replay/edit-experiment.md); `python -m research.workflows.replay.run_edit_experiment --baseline <gui-project> --install <suite> --out <new-folder>` | `E003-E005-replay-20261104` ([exact deltas](../catalog/edit-experiment-summary.json)) |
| E004 / E008: direct FM and DIMR | Ten files from `E001-E002-replay-20261103/console-export-1` | [Serial procedure](replay/serial-experiment.md); `python -m research.workflows.replay.run_serial_experiment --baseline <export> --install <suite> --proj-data <proj-dir> --out <new-folder>`; independently check with `python -m research.workflows.verification.verify_serial_experiment <new-folder>` | `E004-E008-proj-20261104` ([summary](../catalog/serial-experiment-summary.json)) |
| CLI serial release check | Same ten exported files, edited on a copy | `python -m research.workflows.verification.verify_cli_workflow --baseline <export> --install <suite> --out <new-folder>` | `CLI-03-serial-release/verification.json` and four independent NetCDF comparisons |
| E009 / E011: failure, cancellation and process isolation | Same export; independent copies for each failure/control | `python -m research.workflows.verification.verify_failure_cancellation --baseline <export> --install <suite> --out <new-folder>` | `E009-E011-03-release/verification.json`; [0.2 evidence](verification/failure-cancellation-experiment.md), [0.3 release](verification/cli-03.md) |
| CLI processing benchmark | Retained completed and failed runs; no native launch | [Benchmark command and measurement scope](verification/cli-03.md) | `CLI-03-performance/` ([portable measurements](../catalog/cli-03-summary.json)) |
| CLI 0.3.1 scale benchmark | Enlarged MDU, four populated NetCDFs, long synthetic failure logs | [Fresh-process timing and memory replay](verification/cli-scale-031.md) | `CLI-scale-20261104/` ([samples and hashes](../catalog/cli-scale-031.json)) |

E006, E007, E010 and E012–E015 are still in the [investigation queue](replay/investigation-procedure.md). The 0.3 work does not establish those capabilities.
