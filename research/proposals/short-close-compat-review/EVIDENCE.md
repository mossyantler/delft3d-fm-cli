# SHORT-CLOSE-COMPAT-RUNTIME-V and SHORT-CLOSE-COMPAT-PACK-V evidence

Date 2026-11-05. Verifier: Claude Sonnet 5.5 (`claude-sonnet-5-5`). The effort level "high" comes from the coordinator-supplied process argv. I cannot read it from inside the session, so it is reported, not self-verified. Python 3.12.10, repository HEAD `1fce44d` at the PACK-V runs.

All tests are synthetic. Process, Job and FFI boundaries were blocked in every run: `subprocess.Popen`, `ctypes.CDLL`/`WinDLL`, and the `api` of `windows_job` and `windows_job_trace_api`. Blocked attempts were 0 in all runs, and no native engine or Job was launched. I wrote nothing under the product, checkpoint, runtime venvs or test corpora. Output went to fresh `research/experiments/…V-*` directories and to this proposal directory. The tracked-file changes `short-close-compat/d1-tests.log` and `d1-verification.json` were not made by me.

## Independent harnesses (this directory)
| file | sha256 |
|---|---|
| `run_runtime_v.py` (RUNTIME-V: baseline, in-memory candidate overlay, guard-removed mutant) | `c539b14eea6e1b185f35695435ef5a8db83ece1b9330fa49510c07f2a9390c76` |
| `run_pack_v.py` (PACK-V: real installed runtime, no overlay) | `b50b64371c80271095bd011c3cc6fe792ddeb23d5e907e61f184975e17539c9e` |

Both remove root `src` from `sys.path` (the venv's editable `.pth` adds it), so root code cannot be imported by accident. They assert every `dfm_cli` module's origin is the frozen runtime. They also assert the `runs.py` and `run_pump_lifecycle.py` hashes. PACK-V additionally asserts that `runs.fail.__code__.co_filename` is the installed file, so no overlay exists.

## RUNTIME-V (candidate overlay on frozen rev04 runtime; not a wheel)
Candidate `runs.py` sha256 `a9e36eab5f0120f7db53f5f8aaa89726a712ae0616fec64349fc9e8e73ce7513`. Base sha256 `4e1d3c75a5fa5ddbcba2236388ef5248e6b4884c2e023f3b2cc66858456eb82c`.

1. **Author replay reproduced.** The command `.venv/Scripts/python.exe -I -B research/proposals/short-close-compat/verify.py research/experiments/SHORT-CLOSE-COMPAT-RUNTIME-V-20261105-01` gave **15 tests, 0 failures, 0 errors, 0 skips**.
   - The regenerated `candidate.patch` has sha256 `e5a2e6d5…15be0d`, identical to the proposal's.
   - The regenerated `runs.py` is `a9e36eab…`.
2. **Protected corpora**, one process per cell, from `…/PACK-I-rev04…/{checks,tests/legacy49,tests/focused}`. These are read-only inputs and are hash-identical to `checks` and `author116`.

| group | baseline | candidate overlay | guard-removed mutant |
|---|---|---|---|
| author116 (9 modules incl. short gate, native cleanup, canonical gate) | 116 pass (V-04) | 116 pass (V-04) | 114 pass, **2 fail** (V-04) |
| legacy49 (pump close-attribution, pump lifecycle, terminal publication, weir profile) | 49 pass (V-03) | 49 pass (V-03) | 47 pass, **2 fail** (V-03) |
| focused (pump profile, serial exit) | 18 pass (V-03) | 18 pass (V-03) | 18 pass (V-03) |

3. **Mutation meaning.** Deleting the `profile_name == "short"` term is caught independently of the D1 test by two protected tests:
   - `test_pump_close_attribution…test_runner_retains_cleanup_failed_and_original_timeout_reason` (expects `pump_cleanup_failed`).
   - `test_weir_run_profile…test_weir_failed_proof_close_and_member_namespace_including_nested_causes` (subtest `missing_child`).

   This confirms the short-only restriction is load-bearing for pump and weir, and matches my review-02 reasoning.

   One residual weakness: `verify.py`'s own mutation test uses `assertRaises(AssertionError)` and does not check the message. Any assertion would satisfy it. This is minor, because the protected tests above give a specific detection.
4. **Retained initial failures (V-03).**
   - The first harness ran author116 from `tests/author116`. Test modules derive `ROOT` from their file depth, which resolves to `…/research`.
   - That gave 3 identical failures in baseline and candidate: `test_actual_217_…`, `test_actual_219_…` and `test_actual227_component_…`, each a missing `research/research/experiments/...` path. The mutant run also had these 3 plus the 2 real detections.
   - These are harness location errors, not product defects.
   - Rerun in V-04 from the byte-identical `checks/` copies (not edited) gave the clean results in the table.
   - V-02 holds three earlier aborted attempts (a `sys.path` assertion and a CRLF issue in the harness).

## PACK-V (actual installed runtime, no overlay)
Runtime: `…/SHORT-CLOSE-COMPAT-PACK-I-20261105-02/build-01/runtime-venv`.
- **Wheel:** `dist/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl`, sha256 `e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6`. This matches the coordinator's value.
- **Payload comparison:** all 190 `dfm_cli/*.py` wheel members were compared byte-for-byte to the installed files, with 0 mismatches.
- **Installed `runs.py`:** `a9e36eab…`. `run_pump_lifecycle.py` is `49c4a6ed…` (unchanged).
- **Diff against the previous rev04 runtime:** I compared the 190 top-level `dfm_cli/*.py` hashes. Exactly one differs, `runs.py` (`4e1d3c75…` to `a9e36eab…`). I did not diff subpackages or non-`.py` files recursively.

| group | new installed runtime | previous rev04 runtime (control) |
|---|---|---|
| author116 (116) | **116 pass** | 116 pass |
| legacy49 (49) | **49 pass** | 49 pass |
| focused (18) | **18 pass** | 18 pass |
| cli4: the four literal migrated `test_cli` bodies | **4 pass** | 3 pass, **1 fail** |

The rev04 failure is `test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop`: `'short_cleanup_failed' != 'termination_unconfirmed'`. It is exactly the compatibility defect, and the new runtime fixes it without overlay.

Every run recorded `all_dfm_cli_modules_from_runtime: true` (148, 148, 38 and 137 modules loaded for author116, legacy49, focused and cli4) and `in_memory_overlay: false`.

Receipts: `research/experiments/SHORT-CLOSE-COMPAT-PACK-V-20261105-01/<group>-<runtime>/{verification.json,tests.log}`. RUNTIME-V receipts are in V-01, V-03 and V-04. Counts are not additive across corpora, since the groups overlap.

## Actionable defects
**None in the product bytes.** Non-blocking items:
- **N1.** The lifetime-unproven issue string in `fail()` is a literal copy of `run_pump_lifecycle.py:663`. A reword would silently regress short back to `short_cleanup_failed`. It is currently caught by the cli4 test and the author's literal test.
- **N2.** `verify.py`'s mutation test is non-specific (see 3). It is covered by the two protected detections.

## Not performed (limits)
- No native engine, Job or HANDLE-level evidence. All receipts are synthetic fakes.
- No installed CLI end-to-end or schema command rerun. The packager's own installed checks were not rerun.
- No full-root-suite acceptance. The root `tests/` fixtures predate the rev04 receipts and were deliberately not used.
- No recursive non-`.py` diff of the two venvs, and no re-audit of the wheel RECORD.
- Independence limit: the test corpora and fixtures are the author's. My independence is in the harnesses, the origin checks, the mutation runs and the control runtime.
