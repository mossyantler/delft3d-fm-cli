# NATIVE-ADAPTER-FINAL-V handoff

Reviewer model: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort.** AGENTS.md read first.
Reviewed ONLY: `research/proposals/short-close-native-adapter-v3`, commit `a546eb6`, freeze
**`daffc237b80eb5c35b49dcb445e11cda03ae91f86ba080b9a2177253d3aa8c16`** (re-hashed: all 14 files match).
Reader unchanged: `980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62`.
No Git, native, GUI, Job, FFI or process query/launch; no edit to the product, reader, adapter (V1/V2/V3), checkpoint,
shared docs, dispatch or the V1 review (its freeze still re-hashes clean). `native_authorized: false`.

Review freeze: `freeze.json` sha256 **`33848a44cd56fdf2ecb039a3cbdcf58a6ad70770e84227623ba478a42e3a8778`**

| File | bytes | sha256 |
|---|---|---|
| harness.py | 20046 | `8a28c661d3d14d2ec86ba6f4071d668b298a72de97a9cc8277d3265dcdb8aed9` |
| review_checks.py | 74504 | `1f0f7924b95fc4efddfb86c964fdaea45fdadcc40640932c022ce5b8ca20ece9` |
| VERIFICATION.json | 7521 | `d4f7281a4ffdbc5007c656f367aac89f10049816a80626135ede031f19b85f81` |

## Result: bounded checks pass; all seven V1 findings are corrected as specified

No new concrete defect was reproduced. This is an offline result only; it grants nothing.

Independent reruns in fresh `SHORT-CLOSE-NATIVE-ADAPTER-FINAL-V-20261105-01/` dirs (not the author's counts):
**own checks 29/29, composition 13/13 (my frozen reader), admission 22/22**; dispatch still `idle/228` (`2b4c7ad1…`), no `native-rev04` folder.
Final run `review-01` on exactly the frozen review sources: **48 tests, 0 failures/errors/skips** (the 41 unchanged real-class regression tests —
full 12-case two-route run, pair/singles with the real reader, 31 asserted admission refusals, warm-client, deadlines, static boundary audit — plus the
seven requirement tests below, plus 0 mutation families added).
Discrimination control (`…-FINAL-V-20261105-02/v1-control`): the same suite against frozen **V1** fails all seven requirement tests, so they are not vacuous.

| ID | Required corrected behavior | Result on V3 |
|---|---|---|
| F1 | Complete raw bundle `<target>-survival-final.json` (10 keys) saved before the actual reader runs; verdict `observations_sha256` equals the digest of the saved bundle; the saved bundle re-runs to the same verdict offline, for success AND refused; also present when the reader raises | pass |
| F2 | Known-unstarted client (no go pipe attempt): aborted in ≤10 s virtual (was ≥110 s), no `run cancel`, no native manifest/folder/audit invented, primary error kept (`stopped_no_retry…`, not cleanup-failed), receipt `…-unstarted-client.json` with `native_owner_started:false`, budget released, attempt still spent | pass |
| F3 | Cancel recovery ONLY before any pipe attempt: receipt failure → disposal sends exactly one `go` (`started-2.json`); after a pipe attempt (flush failure, or dead pipe) disposal never repeats (`lines` ≤ 1) | pass |
| F4 | Snapshot failure: observer still closed, `final_snapshot.state=unavailable`, `not_exit_proof`, idempotent, receipt saved | pass |
| F5 | WinError 32/33 → `None` + diagnostic (`not_exit_proof`, in `manifest_polling_errors` of the report) and the full 12-case run still passes; WinError 5 / unclassified still raise; absent file → plain `None` | pass |
| F6 | Uncertain go (dead pipe, or line written then flush failed) keeps `command_started: null`, `command_delivery: unknown`, `go_attempted: true`, never repeats; pre-pipe receipt failure stays `not_attempted` and is retryable once; an unknown-delivery client is disposed through the owner path (cancel + manifest), never as unstarted | pass |
| F7 | Exact canonical observer/comparator paths: swapped roles and a byte-identical copy elsewhere are refused (`…canonical pinned source paths`); canonical accepted | pass |

Fake-process honesty (harness only): EOF on an un-started client ends it with code 2 as the real `warm_client` does; `dead` = client already died (write raises, nothing delivered, exit 1); `flush_fail` = line delivered but flush raises.

## Unresolved blockers / limitations (none are new regressions)

- **No remaining reproduced defect**, but not exercised by a test: `Active.cancel()` can be re-entered after `cancel_client.ready()` raised and would call `go()` on a client whose readiness check never passed. Unreachable in the scheduled flows (only dispose creates that client, once) — a latent robustness note for the author, not a blocker.
- `Active.finish()` now polls up to its deadline (≤110 s) when a *started* owner returned without a manifest; bounded, intended for F5.
- F3 conservative limit: after an uncertain cancel the owner is left to its own native timeout (control 90 s) rather than cancelled again.
- Unchanged from V1: admission pins 5 of 134 kernel `.dll/.exe`; a pre-go failure still spends the single attempt; cleanup-cancel clients are created without an admission recheck; the lease is owner+sequence only; natural run ~0.3 s makes a missed observer capture a spent attempt.
- Not validated: real kernel32/observer snapshots (the pinned `RetainedProcess` class ran on a fake kernel), the real installed CLI, a real DIMR record (metadata copies of direct records), any native, GUI, Job or process behavior.
- Native authority: none. G must still bind exact admission, current canonical lease, and runtime/plan/output; this review is an offline input only.

## Reproduce

```
.venv/Scripts/python.exe -I -B research/proposals/short-close-native-adapter-final-review/review_checks.py --out research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-FINAL-V-<stamp>/<fresh-child>
```
Local (git-ignored) evidence: `research/experiments/SHORT-CLOSE-NATIVE-ADAPTER-FINAL-V-20261105-0{1,2}` (`run-checks-01`, `composition-01`, `admission-01`, `review-01`, `v1-control`, `freeze-01`). Portable receipt: `VERIFICATION.json`.
