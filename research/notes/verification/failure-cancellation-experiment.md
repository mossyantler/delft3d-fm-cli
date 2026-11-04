# E009/E011: native failure diagnostics and owned-process cancellation

**Date:** 2026-11-04, Asia/Seoul. **CLI:** 0.2.0. **Result:** passed for the copied
f34 serial fixture on 2026.02 OpenHMWQ. The final replay contains **18 native
engine executions**, **25 public CLI commands**, and 17 result groups, including
deliberate failures and concurrent same-executable controls. See the
[portable summary](../../catalog/failure-cancellation-summary.json).

## Inputs and scope

Copied the ten untouched inputs in
`experiments/E001-E002-replay-20261103/console-export-1/`. Each case has a separate
input copy and new run directories. Original baseline SHA-256, size and mtime
snapshots match before/after; case inputs also remain unchanged by execution.
Existing GUI/user projects were not fixtures.

All cases share the E004/E008 short preparation: StopDateTime becomes
19900805001000, HisInterval and MapInterval become 60 seconds. Start remains
19900805000000, TZone=0, RefDate=19900805 and TUnit=M. The requested end is
**1990-08-05 00:10:00 UTC**, independent of wall-clock test time.

Each E009 change is independent of the others:

| Case | Additional controlled change | Observation, both routes |
| --- | --- | --- |
| Missing BC | Remove only the copied `f34_001.bc` | CLI exit 4 before native launch; no run directory created |
| Corrupt mesh | Replace only copied `f34_net.nc` bytes with a short invalid text marker | Native exit 1; CLI exit 5, `failed`, initialization failure |
| Empty BC | Retain BC General metadata; remove all Forcing blocks | Native exit 1; CLI exit 5, `failed`, initialization failure |
| Unknown first function | Replace the first `function=harmonic` token with `E009_INVALID_FUNCTION` | Native exit 0 and completed 600-second outputs; no captured native ERROR/FATAL |
| Unmodified short control | No additional change | Native exit 0, completed, output times verified |

The unknown-function result is a negative finding: this specific first-block
mutation did not cause an observable native failure. It does not establish that
the function was interpreted correctly, that the signal was applied, or that
arbitrary function names are supported. CLI validation still treats BC contents
as opaque. Neither exit zero nor completed time axes establish boundary semantics.

E011 uses another independent copy with **DtMax=0.0001 seconds** so the tiny model
remains in its time loop long enough to interrupt. Other numerical and physical
settings are retained. This is a controlled lifecycle fixture, not a numerical
recommendation. Native initialization and initial-output completion are observed
before requested cancellation and owner-loss tests. Wall-clock timeout is 2
seconds; the model's requested duration remains 600 seconds.

## E009 diagnostics and side effects

Corrupt mesh primary diagnostic:

```text
** ERROR  : Failed to open: f34_net.nc
```

Empty BC primary diagnostic:

```text
** ERROR  : No signals for polyline file f34_001.pli found in f34_001.bc
```

The preceding `** ERROR : ...` placeholder is retained but is not selected as the
primary explanation. Subsequent lines identify polyline L1 and WATERLEVELBND, then
report external-forcing initialization failure. Exact source path/line and
surrounding context are retained in JSON, alongside all matching error lines.

Both entry points can create diagnostic/output folders before failing. Empty BC
initialization can also write a mesh cache. The manifest inventories actual
generated files rather than treating initialization as read-only. Diagnostics
separate static reference checks, failed native initialization, failed simulation,
and unperformed scientific validation. The JSON error includes the native exit
code and primary context; raw stdout/stderr and `.dia` remain authoritative.

Baseline projection, deprecated-key and legacy map-precision warnings remain
visible. They are not reclassified as the cause of these two deliberate failures.

## E011 isolation evidence

For each route, a separate slow native control runs concurrently using the
**same executable path** as the target: dflowfm-cli.exe for direct FM, dimr.exe for
DIMR. Record its PID and creation time before each target operation, and require
the same identity and live controller afterwards. Control cleanup is a separate
request issued only after those survival observations.

| Operation | Target result | Independent control |
| --- | --- | --- |
| 2-second native timeout | `timed_out`, CLI exit 5; job members drained, member handles signalled | Same PID/creation time, still running |
| Public `run cancel --wait 10` after native readiness | Request acknowledged; `cancelled`, run-start exit 5; job members drained and handles signalled | Same identity, still running |
| Python wrapper launching the actual native engine | Entire owned tree, including wrapper/interpreter/native descendants, drained; all retained member handles signalled | Same identity, still running |
| Kill only this experiment's controller via its retained Popen handle | Private job handle closes; native identity exits; unfinished manifest remains | Same identity, still running |

The final descendant tests each captured three Job members. Their exact PIDs,
member exit confirmations and empty final membership are retained in the replay.
No existing processes were terminated by name. No cancellation command used a
recorded native PID as a kill target.

The owner-loss test begins after the native run is ready. `run status` observes
effective `owner_lost`, with both owner and native identity no longer live, while
the raw manifest still says `running`. It does not fabricate a completed terminal
record. A later cancel request rejects the dead original controller with
`run_owner_unavailable`; it signals no replacement process with a reused PID.

## Partial outputs and state semantics

In the final replay, both timeout cases and both requested-cancel cases retained
readable initial restart, history and map files. Each had **one time sample at
1990-08-05 00:00:00 UTC**, not the requested 00:10:00. No final restart was present.
Other interruption times may leave unreadable or incomplete files; the collector
records read errors and never assumes that a created file is usable.

Native exit 1 occurs for both actual initialization errors and forced termination
in these cases. The CLI therefore records stop reason separately from native
exit code. `verification.state=not_completed` and simulation `aborted` distinguish
timeout/cancel from normal final-time verification.

| State | Meaning |
| --- | --- |
| `failed` | Native/verification/I/O failure; diagnostics retained |
| `timed_out` | Wall-clock bound triggered and owned-tree exit confirmed |
| `cancelled` | Live owner acknowledged request and owned-tree exit confirmed |
| `interrupted` | Python interruption handled and owned-tree exit confirmed; terminal delivery not tested here |
| `cleanup_failed` | Stop was attempted but tree exit could not be confirmed; original stop reason retained |
| Effective `owner_lost` | Read-only observation of a missing original controller, not a repaired manifest |

Termination is **forced**, not graceful native finalization. An initial restart or
readable partial map/history does not establish restartability, a valid completed
simulation or scientific correctness.

## Implementation and regression evidence

`windows_job.py` creates a private, non-inheritable kill-on-close Windows Job
Object. CPython Popen creates a suspended native child with stdin=DEVNULL. The
retained process handle is assigned before the initial thread resumes. Assignment
or resume failure kills that still-suspended child without running engine code.
Breakaway is not enabled. No foreign PID receives terminate rights.

The owner uses TerminateJobObject. It retains synchronization handles for known
members, confirms their Job membership, waits for process exit signals and checks
that final Job membership is empty. A regression exposed that the PID list can
empty before the last process signals; the final implementation checks both.
Another regression confirms child cleanup when the parent already exited.

`run cancel` checks the controller PID **and creation time**, then atomically
writes `cancel.request.json` with the matching run ID. The synchronous owner polls
that request and its deadline. Requests with stale run IDs are ignored; terminal,
foreign-directory or unavailable-owner records are refused. The request command
does not itself signal any PID. Its JSON distinguishes a written request from an
observed cancelled state. CLI `run start` still owns the entire native lifecycle;
there is no daemon, adoption or resume implementation.

The regression suite has **25 tests**: the earlier preservation/time checks plus
primary-error context, stale/foreign cancellation refusal, lost-owner observation,
cleanup uncertainty, real Windows parent-exit/child cleanup, and refused
assignment before execution. Cleanup-failure injection is a unit test; native Job
API failure recovery is not claimed as an integration-tested OS failure mode.

The original public CLI workflow was replayed again as
`experiments/CLI-job-regression-20261104/`: all 16 commands passed, both routes
reached the 600-second end, all 191 compared output variables matched, and the
baseline remained unchanged after the ownership changes.

## Reproduce and retained evidence

Install the application and run extra in `.venv`. Use a nonexistent output folder:

```powershell
.venv/Scripts/python.exe -m pip install -e '.[run]'
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe research/scripts/verify_failure_cancellation.py --baseline research/experiments/E001-E002-replay-20261103/console-export-1 --install 'C:/Program Files/Deltares/Delft3D FM Suite 2026.02 OpenHMWQ' --out research/experiments/E009-E011-new-replay
```

Local evidence:

- `experiments/E009-E011-probes-20261104/`: original native failures, negative
  function probe and old timeout behavior without postmortem summary collection.
  A preparation assertion corrected before the BC run is noted alongside the
  retained probes; it did not modify the original baseline.
- `experiments/E009-E011-job-smoke-20261104/`: private-job parent/child smoke test
  and unrelated Python control.
- `experiments/E009-E011-job-native-smoke-20261104/`: first actual FM Job timeout
  with retained initial output times.
- `experiments/E009-E011-native-20261104/`: initial full matrix before the member
  exit-signal strengthening; retained separately.
- `experiments/E009-E011-replay-20261104/`: final full matrix with member-handle
  confirmations, complete controller invocation records and implementation hashes.

Each final run manifest fingerprints selected executables/DLLs, arguments,
working directory, environment, model inputs and generated files. Suite product
metadata remains distinct from FM `1.2.184.Unknown`, DIMR executable
`2.00.Unknown`, DIMR library `1.02.Unknown`, CLI and NetCDF reader versions. The
reference checkout is DIMRset_2026.02, commit
`5a4649830b1e5072caf019fb4850bbdefd9ad431`; the installed binary source revision
is still unknown. That source revision is not inferred from runtime versions.

## Documentation and limits

FM User Manual §8.9, printed p.143 / PDF p.169, and Appendix F.1, printed p.494 /
PDF p.520, guide diagnostic review; §7.4.5 and Appendix A distinguish DtMax seconds
from relative model time units. Actual outcomes above are runtime observations.

Windows ownership semantics use Microsoft's primary documentation:
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject),
[IsProcessInJob](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob),
[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject),
and [process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).

Still unverified: graceful native shutdown, actual terminal Ctrl+C delivery,
controller death in the suspended creation/assignment window, MPI/coupled process
trees, cancellation of other suite versions, full BC semantics and scientific
validation. The observed native failures are two initialization cases, not an
exhaustive error catalogue or a deliberately induced numerical instability.
