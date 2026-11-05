# NATIVE-ADAPTER-V (V1) handoff

Reviewer model: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort.** AGENTS.md and RESUME.md read first.
Reviewed: adapter freeze **`481029ee17637b49a2518e4b62bee9071cd0cfcd0ba4751ae2144a6dce85c0fe`** (V1, unchanged) with
reader freeze `980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62`.
No Git, native, GUI, Job, FFI or process launch; no edit to the reader, adapter, product, checkpoint, shared docs or dispatch.
`native_authorized: false`. Review freeze: `freeze.json` sha256
`88467691615c1a921977bfa7d6f86a368647d75f1e97f964a2abc5cce4b3d3fc`
(`harness.py` `3cb131ad…`, `review_checks.py` `75fdc3ea…`, `VERIFICATION.json` `a2f7c6df…`).

## Verdict

**V1 is not clean offline V: do not issue a G grant for it.** It is sound in its admission skeleton, call
bounds and raw/state/survival pass keys, but my real-class harness reproduces **seven defects
(3 MEDIUM, 4 LOW)**. The coordinator's V3 corrections plus a bounded re-review are the right next step.
I did not review V2 (`1001d570`) or V3.

## What I independently verified (fresh V dirs, not the author's counts)

- Freeze/file hashes: all 14 adapter files, reader freeze + files, `predeclared_sha256` `d83da17f…` = `prepared-02`, 40 inputs byte-equal to #227, mutations touch only their own file, 191 installed payloads + wheel `e32bf84f…`, installation unchanged since inspection, five #227 manifests and historical states unchanged, canonical dispatch still `idle/228` (`2b4c7ad1…`), no `native-rev04` folder created.
- Author checks rerun: `run_checks` 21 pass, `check_composition` (my frozen reader) 13 pass, `check_admission` 20 pass; their `VALIDATION.json` receipts match the files.
- Product facts checked against the adapter: argv/cwd for direct and DIMR, path strings, exit code 5 for failed/timeout/cancel, protocol 2, `pid`+`ownership.native_identity` published in one atomic write as `running`, retained #227 logs show the initial-output marker ~0.1 s into the 2 s timeout window, real natural outputs satisfy `final_time_matches` / `final_restart_present` and sum to **191 variables over 4 datasets**; the admitted runtime has numpy/netCDF4.
- **My own harness** (`harness.py`): the adapter's REAL `Warm`/`Active`/`Driver`/`Replay`, the pinned REAL `RetainedProcess` class, and the frozen reader, on a scripted fake public CLI (`subprocess.Popen` replaced) and fake `kernel32` (`ctypes.WinDLL` replaced), virtual clock, labelled synthetic metadata copies of the #227 records. Result: a full 12-case, two-route `run()` passes (`passed_all12…`, max 2 concurrent, 12 attempts, all handles closed, manifests never rewritten, `comparison191` = 191); real pair and singles compose with the reader; natural race, audit refusal, survival refusal, warm-up failure, public JSON/exit mismatches, capture failures, deadlines and the real `warm_client.py` go/abort/EOF/tamper behave fail-closed. The author's composition used the checkpoint-shaped observer fixture; the real driver shape was never exercised before.
- Admission: 31 refusal variants each asserted for the **intended reason** (recorded in `VERIFICATION.json`).
- Static: only `public_driver.Warm` creates a process; no kill/terminate/Job API; observer access mask `0x101000` (no terminate/suspend).

## Reproduced findings (`test_defect_*` pass while the defect exists; they will FAIL after a fix → invert them)

| ID | Sev | Defect | Suggested fix |
|---|---|---|---|
| F1 | MEDIUM | The exact survival input bundle is never saved; `control_pre_cleanup`/`control_final` appear in no file, and a refused audit has no `control_samples`, so a refusal cannot be reproduced. | Save the full bundle + `expected_control` (with hash) before calling `audit_control_survival`. |
| F2 | MEDIUM | A pre-go failure (e.g. `Active.begin` recheck/deadline) registers an unstarted warm client; `dispose()` treats it as a live owner: waits the full 110 s, sends a spurious `run cancel` for a run that never started, then fails with "without terminal raw manifest", turning the real cause into `cleanup_unconfirmed_NOT_ACCEPTED`. | In `dispose`, if `not client.started`: abort immediately, skip cancel/manifest requirement. |
| F3 | MEDIUM | `Active.cancel()` sets `cancelled=True` before delivery; a failed `go()` (the pre-go storage case the README promises is abortable) is never retried by disposal, so the owner ends only by its own timeout. | Set the flag only after a successful `go()`; retry while the cancel client is unstarted. |
| F4 | LOW | `close_observer()` snapshots before closing; a snapshot exception leaves the observer HANDLE open and unclosable. | `try/finally` around the snapshot; always call `close()`. |
| F5 | LOW | A transient `OSError` (WinError 5/32/33) reading `manifest.json` escapes `sample()`/`finish()` and aborts a live case (the product itself retries the same race on its side). | Treat those errors as "unavailable now" in polling. |
| F6 | LOW | `Warm.go()` sets `started=True` before writing `go`; a broken pipe leaves `command_started: true` for a command never delivered. | Set after a successful write/flush. |
| F7 | LOW | Admission hash-pins `research_dependencies` but never binds which file fills the `observer` / `raw_output_reader` role; swapped slots are accepted. | Bind exact canonical paths like the auditor/package/contract. |

## Remaining limits and observations (not defects)

- Admission pins 5 of the **134** `.dll/.exe` files in the kernels `bin/lib`; the engines load more. Cheap to pin all (G decision).
- A pre-go failure still spends the single attempt (run stops; no native launched).
- The cleanup `run cancel` client for non-cancel families is created without an admission recheck; the raw-output reader module is loaded lazily after the last recheck.
- The lease is owner+sequence only (no state/expiry); reuse is blocked only because the grant binds an absent `run_root`.
- Operationally tight: the natural run lives ~0.3 s, so a missed live observer capture fails `NOT_OBSERVED` after a spent attempt; control must outlive both targets inside its 90 s timeout (nominally ≈10 s).
- Author `test_flow` temporarily creates folders under the author's preparation root.
- Not validated: real kernel32/observer snapshots, the real installed CLI, a real DIMR record, any native behaviour.

## Evidence and reproduction

Local (git-ignored) evidence under `research/experiments/`: `SHORT-CLOSE-NATIVE-ADAPTER-V-20261105-01/` (`run-checks-01`, `composition-01`, `admission-01`, `review-01…08`, `freeze-01`; failed iterations preserved), `…-02` (first adapter-mutation run, 2 survivors = review gaps), `…-03` (final: **10/10 adapter mutations caught**). Portable receipt: `VERIFICATION.json`.

```
.venv/Scripts/python.exe -I -B research/proposals/short-close-native-adapter-review/review_checks.py --out research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-V-<stamp>/<fresh-child>
```
For V3: set `NATIVE_ADAPTER_V_ADAPTER_DIR` to the V3 folder (mutation use only otherwise), update the `ADAPTER_FREEZE`/`WHEEL`/dispatch constants in `review_checks.py`, and invert the seven `test_defect_*` expectations. A scratch adapter copy must keep `prepare.ROOT` valid.
