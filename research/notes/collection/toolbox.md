# Inspection toolbox

Portable tools are under `research/tools/`. Exact URLs, hashes and release versions
are in `sources.lock.json`. A locally calculated hash is a provenance fingerprint;
only records explicitly marked publisher-verified were compared to publisher
digests. Downloading a tool is separate from exercising it.

| Tool | Purpose | Current status |
| --- | --- | --- |
| [Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon) | File, registry, process/thread activity and process trees | Downloaded/extracted; capture not started |
| [Strings](https://learn.microsoft.com/en-us/sysinternals/downloads/strings) | ANSI/UTF-16 names, options, messages and file extensions | Downloaded/extracted; not launched |
| [ILSpy](https://github.com/icsharpcode/ILSpy) 11.2 | Browse managed types, callers, resources and decompiled methods | Self-contained GUI downloaded/extracted; GUI not launched |
| ILSpyCmd 11.2.0.10050 | Scriptable targeted .NET decompilation | Self-contained Windows package acquired from NuGet; help and selected types exercised |
| [Dependencies](https://github.com/lucasg/Dependencies) 1.11.1 | Native DLL imports/exports and loader dependencies | Downloaded/extracted; not launched |
| [pefile](https://github.com/erocarrera/pefile) 2024.8.26 | PE architecture, version resources, imports/exports, CLR header | Installed in research venv; exercised |
| [dnfile](https://github.com/malwarefrank/dnfile) 0.18.0 | Managed type/method/reference metadata without loading GUI DLLs | Installed in research venv; exercised |
| [pypdf](https://github.com/py-pdf/pypdf) | PDF indexing/text search | Installed in research venv; ten manuals indexed |
| netCDF4 / numpy / cftime | Read CF time axes, masks, metadata and numerical output | Pinned research venv; E004/E008 final times and 191-variable route comparisons verified |
| PowerShell/CIM | Installed processes, ancestry and loaded application modules | Scoped process capture exercised |
| Codex Windows Computer Use | Visual inspection and reversible GUI navigation | Live window inspected; accessibility tree unavailable in this view |

The ILSpy GUI archive was verified against the SHA-256 digest returned by its
official GitHub release metadata. No global .NET installation was required.
Windows Authenticode checks also returned valid Microsoft signatures for the
downloaded `Procmon64.exe` and `strings64.exe`.

## Repeatable utilities

| Script | Role |
| --- | --- |
| `scripts/acquire.py` | Source clones, release-tag check, portable tool downloads, acquisition metadata |
| `scripts/acquire_managed_cli.py` | Resolve NuGet tool packaging and acquire a self-contained Windows ILSpyCmd, or a matching isolated runtime if needed |
| `scripts/inspect_install.py` | Product settings, file inventory, selected PE/CLR metadata, launcher copies, bounded help/version probes |
| `scripts/decompile_targets.py` | Inspect selected model export, DIMR runner/API and scripting types; keep raw output local |
| `scripts/probe_console.py` | Execute one Python print marker with no project loaded; retain logs/warnings |
| `scripts/capture_processes.ps1` | Capture only processes and loaded modules belonging to the selected installation |
| `scripts/index_manuals.py` | Copy official local PDFs, verify copies, extract page-delimited text |
| `scripts/snapshot.py` | Hash files before/after a controlled action and report added/removed/modified files |
| `scripts/build_catalog.py` | Assemble acquisition lock and harvest candidate MDU fields from source |
| `scripts/audit_research.py` | Check collected commits/hashes, manual copies, decompilation evidence, local links and snapshot behavior |
| `scripts/prepare_export_experiment.py` | Copy the official f34 fixture into a fresh experiment folder with source fingerprints |
| `scripts/run_gui_export.py` | Exercise GUI-hosted save/export through the supported script interface in a fresh bounded host |
| `scripts/run_shell_script.py` | Execute a bounded console script, retain argv/logs, and require a completion marker |
| `scripts/compare_model_exports.py` | Compare exported files and MDU values and check known input references |
| `scripts/run_edit_experiment.py` | Replay independent control/scalar/boundary cases sequentially on copied projects |
| `scripts/verify_edit_experiment.py` | Verify exact MDU delta, ordered BC metadata and every data cell, repeated exports and unchanged projects |
| `scripts/run_serial_experiment.py` | Prepare copied short inputs and DIMR XML, run bounded direct-FM/DIMR processes, retain hashes/environment/logs |
| `scripts/verify_serial_experiment.py` | Verify CF final times/cadence, restart times, finite selected fields, route data agreement and unchanged inputs; separate from execution status |
| `scripts/verify_cli_workflow.py` | Replay application install/model/edit/validate/run/status commands on copied baseline; verify both routes and 191 output variables |
| `scripts/verify_failure_cancellation.py` | E009/E011 native failure/timeout/cancel replay, private-job descendant/owner-loss checks and separate same-executable controls |

Example targeted inspection:

```powershell
python research/scripts/decompile_targets.py --install '<install>' --target DimrRunner
```

Raw `.cs` files are inspection artifacts, not original GUI source. Consult IL and
native source when decompilation leaves uncertainty. Never treat decompiled code
as proof of a live event unless a corresponding trace confirms it.

## Process Monitor experiment setup

Use a copied/fresh experiment model and a unique output folder. Start a short
capture around one GUI action, then stop promptly. Preserve the native PML and
export the relevant rows for analysis.

Include the relevant shell process and its descendants. Inspect Process Create
events for the actual helper executable and command line; inspect working-folder
file operations and Load Image events for native libraries. Record paths, file
open/write order, DLL lookup failures and process exit. Filtering only
`dflowfm-cli.exe` would miss an API-hosted GUI run.

A file hash difference shows a changed file; it does not prove which UI field
caused the change without a controlled experiment. Keep baseline startup traces
separate from the action under study. A capture can contain unrelated local
paths, so keep raw traces under the ignored evidence directory.

## Optional deeper tools, not acquired

| Tool | Use when |
| --- | --- |
| [dnSpyEx](https://github.com/dnSpyEx/dnSpy) | A managed method needs breakpoints, arguments, or call stacks to resolve behavior |
| [Ghidra](https://github.com/NationalSecurityAgency/ghidra) | A native component has no sufficient source/API documentation; inspect PE exports and release source first |
| [WinDbg](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/) | Native crashes, loader failures, or a dump need analysis |

The current investigation did not patch application binaries, attach a debugger,
change installed settings, or start Process Monitor's capture driver.
