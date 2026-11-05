# NATIVE-CLOCK-AUTH-V handoff

Reviewer: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort**; AGENTS.md read first.
Reviewed ONLY the final candidate `research/proposals/short-close-native-adapter-v6`, freeze
**`53a1db831f37b6a09b925711cd0beb19f0dd8b325e0d26f6f4436fd6776e82e5`** (re-hashed: all 14 files match; only `replay_adapter.py`
differs from V5 `9e72d539…`, three lines). Reader `980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62` and the
canonical observer source unchanged. Canonical dispatcher untouched: idle/230, `df973d4b…`.
No Git, native, GUI, Job, FFI, PID or process query/launch; no edit to any candidate, reader, product, shared doc, dispatch or earlier review/evidence
(trial-229 run root: all 192 files and the grant folder re-hashed byte-identical; V5 and V6 folders unchanged). `native_authorized: false`.

Review freeze `freeze.json` sha256 **`10bb3cbd425143aad70f129c96c2ec72f2dfa7f6c1b83dd89e8920b04b1a31cf`**:
`harness.py` 20539 B `1b84f0f5…`, `review_checks.py` 96211 B `41ac5306…`, `VERIFICATION.json` 12195 B `2fd9e408…`.

## Result: bounded checks pass for V6; no concrete defect reproduced

Independent reruns in fresh dirs (not the author's counts): **V6 own 32/32, exact-reader composition 13/13, file-admission 26/26** (`v6-*`); the same three on V5 also
pass as controls (32/13/26). Final run `review-03` on exactly the frozen review sources: **54 tests, 0 failures/errors/skips**
(48 unchanged real-class regression tests incl. F1–F7, plus A1, C1–C5; counts are not additive with the candidate's checks).

| ID | Delta checked | Result on V6 |
|---|---|---|
| C1 | Equal coarse ticks with distinct UTC: `sample_after` returns the actual **next** returned snapshot (`is` identical object), 4 reads for 3 ties, earlier snapshots and `previous` deep-equal their copies, nothing normalized or incremented; advancing immediately costs exactly one read | pass |
| C2 | Stall (512-sample cap exactly; and the 1 s perf_counter bound ≤4 reads), identity change (pid / birth / image / observer_id), regression, non-int monotonic (bool/None/str/float), bad `previous`, missing probe → `ValueError`, refused at the first bad read. `close_observer(after=…)` on stall/identity/regression still calls `close()` exactly once, records `unavailable`/`not_exit_proof`, is idempotent, and the frozen reader rejects that wrapper. End to end on a never-advancing clock the real pair refuses, no survival bundle is produced, every observer handle and client is released | pass |
| C3 | Real `Active`/`Driver`/`Observer` pair on a 15.625 ms coarse clock (hundreds of equal-tick reads occurred): both survival verdicts `independent_control_survival_confirmed`; every adjacent strict transition in both saved bundles is strictly increasing, whole-millisecond stamps | pass |
| C5 | Call-structure proof: cb→ca, tb→te, cp→cf, te→target close-final, cf→control close-final (both bundles) and ca→cp (the trial-229 pair) are each produced by `sample_after`/`close_observer(after=…)` with exactly the previous actual sample | pass |
| C4 | Trial-229 retained verdict re-derived by the unchanged frozen reader: cancel **refused** (`control_after->control_pre_cleanup: monotonic stamp reused by a different snapshot`), timeout **confirmed**, both equal to the saved verdicts; run root listing digest `e0e3520a…` | pass |
| A1 | Synthetic active dispatcher bound to one real fixture grant: matching grant passes `check()` and `recheck_start()`; another admitted grant, same bytes at a copied path, hash/path/output root each wrong, each field missing or of wrong type (None/1/True/list), **legacy owner+sequence only**, idle owner and wrong sequence are all refused with the intended reason (recorded), at check AND at every recheck; the real canonical dispatcher (idle/230) refuses | pass |

Controls (same suite, `control-v5-b`, `control-v3-b`): **V5** passes A1/C1/C2/C3 but **fails C5** (it lacks the three added `sample_after` transitions, so V6 is required);
**V3** fails A1/C1/C2/C3/C5, and its coarse pair is refused by the frozen reader (`Observer close final snapshot: monotonic stamp reused by a different snapshot`), the same failure class as trial 229.
Preserved: `review-01` (4 failures, all bugs in my new tests), `review-02`, first controls `control-v5/v3` (invalid: the synthetic review hard-coded the V6 freeze; fixed and rerun as `-b`).

## Remaining limits (none a new defect)

- Not constructed: a rapid-timeline **end-to-end** tie for cb→ca, tb→te, cp→cf. The metadata copies embed a ~46 ms request-to-close window (longer than one 15.625 ms tick); V6 is evidenced there by the call-structure proof (C5), strict ordering on a coarse clock (C3), helper behavior (C1/C2) and the V5 control.
- Worst-case added wait: nine `sample_after` calls per pair, each ≤ 1 s (typically ≤ ~16 ms), far inside the 90 s control timeout; stall is refused, never papered over.
- Offline only: no real `GetTickCount64`/handles, no live canonical slot (the real slot is idle/230), no real DIMR record; admission still pins 5 of 134 kernel binaries (unchanged).
- Native authority: none; G must still bind the exact admission, a current lease (now exact grant+hash+output) and the runtime.

## Reproduce

```
.venv/Scripts/python.exe -I -B research/proposals/short-close-native-clock-auth-review/review_checks.py --out research/experiments/SHORT-CLOSE-NATIVE-CLOCK-AUTH-V-<stamp>/<fresh-child>
```
Local (git-ignored) evidence: `research/experiments/SHORT-CLOSE-NATIVE-CLOCK-AUTH-V-20261105-01/` (`run-checks-01`/`composition-01`/`admission-01` = V5 reruns, `v6-*` = V6 reruns, `review-01…03`, `control-*`, `freeze-01`). Portable receipt: `VERIFICATION.json`.
