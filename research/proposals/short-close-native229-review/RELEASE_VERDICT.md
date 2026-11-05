# NATIVE229-CLOSE-V release-only verdict

Reviewer: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort**; AGENTS.md read first.
Pure read-only JSON postmortem of `research/experiments/SHORT-CLOSE-G-native-rev04-229-20261105-01`
and the grant folder `SHORT-CLOSE-NATIVE-G-20261105-01`, using the exact frozen reader
`980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62`. No process/PID/Job/HANDLE/FFI/native/GUI query or launch, no edit to
any record, source, reader, adapter or dispatch, no Git. All 192 run-root files, the 6 grant-folder files, the dispatch
(`ff534d85…`), the reader and adapter V3 (`daffc237…`) re-hashed **byte-identical** after the readback.

Review freeze `freeze.json` sha256 **`9c16257fef03c7ddc6d3d510c93879b63d0b83accf61d3b109d2b0090b28179c`**
(`readback.py` `d25af149…` 27360 B; `VERIFICATION.json` `251cd1af…` 8422 B). Run-root file listing digest `e0e3520a…`.
Final run `readback-02`: **31/31 checks pass** (`readback-01` preserved: 1 check failed because of my own wrong assumption that monotonic stamps are multiples of 15.625 ms; they are whole milliseconds advancing in ~15.6 ms steps; no evidence difference).

## Verdict

**RELEASE-SAFE BY RAW RECEIPTS. The lease-229 slot can be released. The trial is NOT ACCEPTED** (`stopped_no_retry_NOT_ACCEPTED`).
Releasing the lease is a cleanliness statement about what was started, not an acceptance of the trial. The six direct
attempts are spent (one attempt per case, no retry); any further run needs a new fresh folder and a new lease.

## What the raw receipts establish

1. **Six original lifetime/Job/collector closures** (natural, bad-mesh, empty-bc, control, timeout, cancel; all direct): frozen-reader
   `qualified_full_lifetime_close` for each; two retained members each with same-HANDLE exit confirmed; final original-Job accounting
   `TotalProcesses=2 ActiveProcesses=0`; Job empty; real Job `CloseHandle` (int, nonzero); collector closed. My reruns equal the adapter-saved
   audits and state assertions exactly. Public states: completed / failed / failed / timed_out / cancelled / cancelled, none `cleanup_failed`;
   both forced targets achieved a stop (not natural races).
2. **Six observer `CloseHandle` receipts**: real int `1`, same observer object/birth/image as each live capture, exited final sample before
   the close, accepted by the frozen reader; six distinct observer objects. Observers are read-only (`QUERY_LIMITED|SYNCHRONIZE`) and give no lifetime coverage.
3. **Eight public-client invocations** all returned with parsed protocol-2 JSON: natural start 0 (ok); bad-mesh and empty-bc 5 (`native_failure`);
   timeout 5 (`run_timeout`); cancel and control starts 5 (`run_cancelled`); the two `run cancel` requests 0 (ok). Every `go` was delivered exactly
   once (no unstarted or unknown-delivery client); stdout/stderr hashes match their receipts; stderr empty for all eight.
4. **Bounds**: 6 of 12 launches, peak 2 concurrent owners (from raw timelines), no DIMR folder or manifest, empty `cleanup-errors`/`audit-errors`,
   no manifest-polling errors. Grant `552ebe0a…`, adapter V3 and reader pins, `lease_sequence 229`, run root all match; the dispatch slot is still
   `SHORT-CLOSE-NATIVE-G`/229 for this run (not yet released).

## The refused gate, precisely (not an exit or physics finding)

`cancel-direct` control survival is **refused** by the frozen reader (`audit_state: refused`, control lifetime passed):
`control_after->control_pre_cleanup: monotonic stamp reused by a different snapshot`. Raw facts: two distinct **live** samples of the
same observer object, UTC `12:17:55.133410` and `12:17:55.135944` (2.534 ms apart, `in_a_job` true), identical `monotonic_ns 111819015000000`
(`GetTickCount64`, 15.625 ms tick; the 18 distinct stamps in the run are whole milliseconds at least 78 ms apart per observer). Evaluating the
reader's **20 gates one by one** with its own unchanged helpers: cancel bundle **19/20 pass**, only that gate fails; timeout bundle **20/20**
(and the reader's confirmed verdict reproduces identically). This is a chronology-ordering gate. It says nothing about process exit, Job closure or
physics, and it does **not** confirm survival: survival for the cancel-case control stays **NOT confirmed**. Timeout control survival:
`independent_control_survival_confirmed`.

Producer note (not applied here): the reader refuses ANY pair of adjacent distinct samples of one observer that share a tick (`control_before->after`,
`after->pre_cleanup` unless the very same snapshot, `pre_cleanup->final`, `target_before->exit`, and a close-wrapper final snapshot unless identical to
the previous sample). In this trial the two close-wrapper finals were identical to their preceding samples, so those pairs passed.

## Not established (do not infer)

- Cancel-case control survival confirmation; causal kill attribution (`live_then_signalled_cause_not_proven`); clean native finalization or
  scientific validity of any forced case; any DIMR behaviour; the 191-variable comparison (not run, `comparison191.json` absent).
- Liveness **after** the recorded times: by instruction no live query was made; the receipts bound the state at record time (last events 12:17:55).
- Natural-direct outputs: only the adapter-saved raw-output receipt was read (history/map final times match, final restart present); not recomputed here.

Evidence: `research/experiments/SHORT-CLOSE-NATIVE229-CLOSE-V-20261105-01/{readback-01,readback-02,freeze-01,run-root-before.sha256,grant-folder-before.sha256}` (git-ignored); portable receipt with all key file hashes: `VERIFICATION.json`.
