# CLI 0.3.0: protocol migration and release verification

Windows, Python 3.12, installed 2026.02 OpenHMWQ. The engine reported `1.2.184.Unknown`; the source revision remains unknown. See the [portable result](../../catalog/cli-03-summary.json) and [experiment index](../experiments.md) for the inputs, commands and retained evidence.

## Reading responses

The command names, options and exit categories stay the same. Both successes and errors on stdout now carry `protocol_version: 2`; optional JSONL state events on stderr also carry the version. `schema inspect` lists commands from the same parser that executes them.

| Question a caller needs to answer | 0.2 lookup | 0.3 lookup and meaning |
| --- | --- | --- |
| Which state did the controller persist? | `result.record.state` | `result.recorded_state`; `result.record` retains the original manifest |
| Is the recorded owner still alive? | `result.live_process_state.owner_identity_live` boolean/null | `result.observations.owner`: `live`, `exited`, `pid_reused`, `unavailable`, `unknown` (no evidence), or `not_checked` (terminal). Native identity uses the same vocabulary. |
| Has an unfinished run lost its owner? | A false owner check could imply `owner_lost` | Only exit or PID reuse establishes `effective_state: owner_lost`. Missing evidence or access denial gives `effective_state: unknown`. |
| Did my stop take effect? | `request_written`, then `cancellation_applied` | Check `request_written`, `owner_acknowledged`, then `cancellation_applied`. `tree_termination_confirmed` is the separate cleanup observation. Acknowledgement applies to the run ID, including repeated requests. |

For example, an active status result previously contained `{"live_process_state":{"owner_identity_live":false},"effective_state":"owner_lost"}` after an access denial. It now contains `{"recorded_state":"running","observations":{"owner":"unavailable","native":"live"},"effective_state":"unknown"}` if only the owner lookup was denied. A caller must not signal the native PID based on this response.

New manifests use `schema_version: 3`. Status accepts v1/v2 without rewriting them. Control of old runs remains with their original CLI version. A malformed manifest returns exit 3 with `invalid_manifest`; an unavailable owner refuses cancellation with exit 4. Failed cleanup records `cleanup_failed` with the initial `stop_reason`. An acknowledged request can coincide with natural completion: consult the terminal state. Unknown or malformed requests do not stop the engine; the owner records the first rejected request.

Diagnostic lists retain up to 32 entries each, 1,024 characters per line, and two context lines on either side of each retained error. The first meaningful primary error is retained even after the excerpt limit. Use `diagnostics.omitted`, `clipped_source_lines` and the raw files for the remainder. Warning excerpts now count occurrences, including duplicates.

## Measurement

Use the application venv's Python for this and the native checks in the [index](../experiments.md):

```powershell
.venv/Scripts/python.exe -m research.workflows.verification.benchmark_cli research/experiments/CLI-job-regression-20261104 --failure-run research/experiments/E009-E011-replay-20261104/runs/bad-mesh-direct
```

Same files and interpreter, one warm-up and 15 uninstrumented samples per phase per version. Counts come from a separate instrumented pass. The pre-change source snapshot, and both measurements, are retained under `research/experiments/CLI-03-performance`. For the old implementation point the child Python's `PYTHONPATH` at that directory. The benchmark never launches FM/DIMR or updates a manifest.

| CLI phase | 0.2 median | 0.3 median | Logical work per invocation, before → after |
| --- | ---: | ---: | --- |
| Validate the ten-file model | 12.636 ms | 8.794 ms | MDU parses 2 → 1; parsed-file reads plus digest reads 145,535 → 58,474 bytes |
| Verify and inventory completed outputs | 26.754 ms | 17.075 ms | Four NetCDFs: opens 8 → 4, digests 8 → 4; digest reads 1,443,472 → 721,736 bytes |
| Scan bad-mesh diagnostics on the native failure path | 1.470 ms | 0.790 ms | Four log files: 8 → 4 scans; 5,294 → 2,647 bytes |

Bytes count explicit file reads, not OS disk traffic or internal NetCDF library reads. Timings exclude engine time and CLI startup. No wall-clock guarantee follows from this small fixture. Hashes still guard preview/apply, input staging and post-run input integrity.

## Native acceptance

The 16-command serial replay verified 11 history and 11 map samples per route, a restart at 1990-08-05 00:10:00 UTC, and identical values for 191 variables across four direct/DIMR datasets. The independent comparison is outside the product code.

The E009/E011 release replay covers two launch routes, deliberate mesh/BC failures, wall-clock timeouts, forced cancellations, descendants and controller death. Each same-executable control survived the target stop. A malformed `[]` stop request sent to each live control was recorded and ignored. Input fingerprints were unchanged. The unresolved projection warning remains visible. This evidence covers the copied serial fixture; it does not verify physical validity, graceful native shutdown, MPI or coupling.

The 34 automated tests passed, including both sides of the natural completion/cancellation race and denied Win32 access. The manifest reader accepted all 13 retained v1 records and 35 retained v2 records without modifying them. The installed entry point reported 0.3.0; dependency checks, legacy script imports and the research provenance/link audit passed.
