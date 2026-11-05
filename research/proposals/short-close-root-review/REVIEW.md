# SHORT-CLOSE-ROOT-V review

Reviewer: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort**; AGENTS.md read first. Final integration review of the root diff
(two product modules + test migration + short regressions), including the coordinator's added `tests/test_short_close_errors.py`.
No Git write, no staging, no native/process/PID/DLL/FFI call; only files read, hashed and focused synthetic tests run in-process;
nothing outside this folder and the fresh `research/experiments/SHORT-CLOSE-ROOT-V-20261105-01/` output was written. Checkpoints and run-229/231
raw bytes untouched. Product bytes unchanged between my first comparison and the end of the review.

Review freeze `freeze.json` sha256 **`9eea3faccb757569616c1af20586060ba53a9b1185d1b186e899f712097a75ec`**
(`root_review.py` `446e7c3b…` 15847 B; `VERIFICATION.json` `d9e5a021…` 6507 B). Final run `review-02`: **27/27 checks** (`review-01` preserved: 2 over-broad checks of mine).

## Verdict: **APPROVE** the root integration

Pending only what the coordinator owns: the full root unittest result (not duplicated here) and the non-empty Git commit. No blocking defect found.
This node is not complete until the coordinator commits.

## Exact hashes (the commit manifest; all re-checked unchanged at the end)

| Path | sha256 (prefix) | bytes |
|---|---|---|
| src/dfm_cli/runs.py | `a9e36eab5f0120f7…` (= wheel / admission pin) | 26748 |
| src/dfm_cli/run_pump_lifecycle.py | `49c4a6ed29b64b08…` (= wheel / admission pin) | 49032 |
| tests/test_cli.py | `05d9f7703612da75…` | 20005 |
| tests/cli_job_fixtures.py | `ba19d58800f5d30d…` | 12649 |
| tests/pump_lifecycle_fixtures.py | `b84850361bd42940…` | 10566 |
| tests/test_pump_close_attribution.py | `f649196d8a812cfd…` | 8397 |
| tests/short_fixtures.py | `8e4dd000fbcb1ad8…` | 11041 |
| tests/test_short_close_contract.py | `b20f4603a865df21…` | 8605 |
| tests/test_short_close_errors.py | `7718df1dd8ff7e5a…` | 4048 |

Full hashes are in `VERIFICATION.json`.

## What I verified

- **Root191 == accepted wheel `e32bf84f…`**: all 191 `src/dfm_cli` files byte-identical to the wheel payload and to the admission `expected-product` pin; none extra or missing; both modules differ from HEAD.
- **Scope**: exactly 2 modules + 3 touched tests + 4 new test files in `src/`+`tests/`, nothing staged. (An unrelated untracked `research/proposals/short-close-native-gates/verify_root.py` exists; outside scope, not reviewed.)
- **Assertion invariants**: `test_cli.py` 63 → 63 assert statements over 27 functions and `test_pump_close_attribution.py` 33 → 33 over 10 — every function's assertion AST is byte-identical to HEAD; no removed diff line contains an assertion; the pump fixtures file has no assertions and the same function set. The four migrated CLI tests change only setup (receipt-carrying `CliJobFixture`, absolute stub image paths, `side_effect=owned.stop/poll`).
- **Provenance**: `cli_job_fixtures.py`, `test_cli.py` = checkpoint migrated = fixture-I migrated; `pump_lifecycle_fixtures.py`, `test_pump_close_attribution.py` = checkpoint legacy49; `short_fixtures.py`/`test_short_close_contract.py` = accepted author116 except 2 and 1 docstring/comment lines (code identical).
- **No hidden repair or skipped assertions**: no skip/expectedFailure added (the 8 test_cli Windows guards pre-exist); helper receipts are constructed before launch/stop/close and asserted unchanged; `short_fixtures` forbids real `Popen` and both Windows API entry points; `cli_job_fixtures` patches only `OwnedJob` and the native normal-exit capture boundary, never a production assessment or persistence function.
- **Focused portable runs** (all OK, 0 skips): error tests 3, short contract 18, pump close attribution 8, migrated CLI classes 10.

## Your cross-profile question: yes, it is retained — no missing regression

`tests/test_short_close_errors.py` is the persistent equivalent of the compat package's cross-profile check: one identical failed-lifetime/passed-close receipt yields `termination_unconfirmed` (short), `pump_cleanup_failed` and `weir_cleanup_failed`. I ran the compat package's own profile-guard mutation (guard removed from `runs.fail`): the persistent test **fails** (2 failures), so it retains the guard regression. Close-failure priority and storage-error propagation are tested for `short`; for pump/weir the close-failure codes are asserted by their own persistent tests (`test_pump_close_attribution.py:82`, `test_weir_run_profile.py:271`), and a probe confirms no leakage (`short_cleanup_failed`, `pump_cleanup_failed`, `weir_cleanup_failed` for the same close faults).

## Findings (all INFO, none blocking)

- **R1**: the short contract file has **18** test methods (same as the accepted author116 file), not 19; with the 3 error tests that is 21 short-related. Use 18 + 3 in commit/DELIVERY text.
- **R2** (optional): to make the close-failure parametrization symmetric, loop it over `("pump-scalar","pump_cleanup_failed")` and `("weir-series","weir_cleanup_failed")` in `test_short_close_errors.py`; the probe shows the expected values.
- **R3**: `short_fixtures.py` ends with stacked redefinitions of `normal_receipt`/`close_receipt` adding schema fields at construction — correct and identical to the accepted file; fold into the constructors in a later cleanup. Its forced receipt is a minimal orchestration stub, so these tests prove ordering/orchestration, not native evidence strictness (the independent reader's job).
- **R4**: the four migrated CLI tests are Windows-only at HEAD too and skip silently elsewhere.

Not done by design: full-suite run, any native action, staging/commit.
