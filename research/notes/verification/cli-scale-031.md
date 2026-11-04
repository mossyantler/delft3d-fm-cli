# CLI 0.3.1: large-input processing on Windows

The 0.3 improvements to MDU validation and NetCDF inventory/verification held on this larger synthetic workload. The slowest remaining phase in 0.3.0 was scanning native diagnostics. Version 0.3.1 reduces its median time by 80% while keeping the bounded diagnostic payload and the full raw logs. The command interface, protocol 2, manifest 3 and supported simulation profile are unchanged.

| Phase and input | 0.2.0 time / peak WS | 0.3.0 time / peak WS | 0.3.1 time / peak WS |
| --- | ---: | ---: | ---: |
| Validate 1.24 MiB MDU | 1,217.9 ms / 27.7 MiB | 24.6 ms / 27.3 MiB | 23.4 ms / 26.9 MiB |
| Verify and inventory 126.73 MiB of NetCDF | 260.3 ms / 47.7 MiB | 132.9 ms / 47.6 MiB | 134.1 ms / 47.7 MiB |
| Diagnose 51.06 MiB of failure logs | 3,112.5 ms / 191.0 MiB | 1,924.7 ms / 21.0 MiB | 389.8 ms / 21.0 MiB |

Time and peak working set (WS) are separate medians of five fresh processes per phase/version. The 0.3.1 code change affects only diagnostics; small differences between 0.3.0 and 0.3.1 in the other phases are run-to-run variation. See [all 45 samples, input/source fingerprints and native replay checks](../../catalog/cli-scale-031.json) and the [small f34 measurements](cli-03.md).

**Inputs and measurement boundary.** The MDU adds 5,000 distinct scalar keys with preserved comments to a copy of the prepared f34 input. Each NetCDF is a physically populated NetCDF3 file: the largest map contains eleven frames of 2.5 million float32 elements. History, map and two restarts use f34's 600-second clock. The synthetic failed run contains 320,000 stdout progress lines, 240,000 DIA progress lines, plus sparse warnings, native errors, context and stderr. No large native simulation is claimed. The results describe large spatial outputs and many ordinary log lines; they do not measure very long time axes, compressed/chunked HDF5, cold disks, JSON serialization or solver throughput.

Each worker imports the selected package, loads the verification libraries for the NetCDF case, then times one complete processing phase. For 0.2 the output case includes both verification and inventory, and the native-failure case includes both diagnostic scans. The parent verifies identical file hashes before and after, warming the file cache, and rotates version order by trial. Memory is the Windows kernel's process-lifetime peak resident working set, including imports and native libraries; it is not Python heap size or total allocations. Start working sets and CPU time are in the raw samples. Fixture generation, CLI startup, correctness comparisons and the separate profiler run are outside the timer.

**Why diagnostics changed.** A separate cProfile run counted 2,080,463 regex searches in the 0.3.0 worker. Most ordinary progress lines cannot possibly match any diagnostic. In 0.3.1 inexpensive literal checks decide whether to run the existing error/warning, version and execution-marker regexes. They inspect the whole line, so a mixed-case error late in a long message is still found. The same profiled workload made 77 regex searches. Errors, context, omission counts, version/marker values and the DIA digest matched the complete 0.3.0 diagnostic payload. Memory is still sensitive to the longest individual line.

**Correctness checks.** All three versions agreed on the MDU report, the NetCDF times, hashes and inventory, and the primary error/context. All 35 automated tests passed, including late, mixed-case and embedded error tokens and false completion markers. On the actual 2026.02 OpenHMWQ f34 fixture, 16 public commands verified direct FM and DIMR at 600 seconds, including the final restart and all 191 compared variables. The E009/E011 replay passed 25 public commands across 17 failure/ownership result groups; baseline fingerprints were unchanged. Raw native reports are under `research/experiments/CLI-scale-20261104/{serial,failures}`.

**Replay** from the project root using the application venv with `.[run]`, on Windows. The fixture and output report must be new. The two retained source paths are local experiment artifacts; each must contain the corresponding `dfm_cli` package, or supply an equivalent source snapshot and check its fingerprint.

```powershell
$py = '.venv/Scripts/python.exe'
$module = 'research.workflows.verification.benchmark_scale'
$casePath = 'research/experiments/CLI-scale-replay'
& $py -m $module prepare "$casePath/fixture" research/experiments/CLI-job-regression-20261104/prepared
& $py -m $module measure "$casePath/fixture" --samples 5 --source v020=research/experiments/CLI-03-performance --source v030=research/experiments/CLI-scale-20261104/v030 --source v031=src --out "$casePath/comparison.json"
```
