# SHORT-CLOSE compatibility candidate

The user resumed in Herdr on 2026-11-05. Codex prepared this private candidate;
Claude Code Sonnet 5.5 high independently reviewed the contract. This directory
is research material, not accepted product code or native execution approval.

The rev04 candidate replaces the established `termination_unconfirmed` public
error with `short_cleanup_failed` even when the actual original Job and collector
close succeeded. The proposed patch preserves the original code only for the
`short` profile, with failed lifetime evidence, successful typed close/binding
checks, no close exception and exactly the one lifetime issue. The manifest state
remains `cleanup_failed`; unproven lifetime never becomes successful completion.
Pump and weir retain their family-specific errors.

`verify.py` compiles this change in memory against the existing frozen rev04
installation. It does not modify that installation, the checkpoint, or product
sources. It requires the local package runtime and the checkpoint's migrated
fixtures. From the repository root, choose a fresh output directory:

```powershell
.venv/Scripts/python.exe -I -B research/proposals/short-close-compat/verify.py research/experiments/SHORT-CLOSE-COMPAT-review-NEW
```

The final author run passed 14 tests with no failures, errors or skips. Four are
the unchanged migrated CLI test bodies. Ten additional tests check close failure
precedence, malformed summary flags, binding contradictions, storage exceptions,
and the existing pump/weir codes. Some negative tests inject derived close
assessments after the synthetic close; they are not raw Windows API evidence.
Process creation and Job/FFI boundaries are blocked during the tests. Reading
the current Python process identity before that guard is inspection only.

`candidate.patch`, `verification.json` and `tests.log` pin the final run.
Earlier local runs 01–02 failed because of test harness mistakes (an import and
an assertion capture); 03–05 were intermediate passes, and 06 binds these final
candidate bytes. Keep those local records. Results are not additive.

Independent static review and independent runtime verification are distinct.
At the first replay, independent candidate execution, a new package freeze and
the runner/reader composition gate were all still pending.

`SHORT-CLOSE-COMPAT-D1-I` strengthens the profile comparison identified in the
independent static review: the same complete passing close receipt now checks
short, pump and weir. Removing the short-only predicate must fail that comparison;
an explicit mutation test verifies this. All 15 synthetic tests passed in fresh
`SHORT-CLOSE-COMPAT-D1-I-20261105-01`; `d1-verification.json` and `d1-tests.log`
retain the result. The candidate product bytes are unchanged (`a9e36eab…`).
The original 14-test evidence above remains historical.

Independent [runtime and installed-wheel checks](../short-close-compat-review/EVIDENCE.md)
now reproduce the 15-test replay and pass the protected 116-, 49- and 18-test
corpora. The actual installed compatibility wheel passes the four unchanged CLI
tests; the previous rev04 runtime still fails the one expected error-code test.
The corpora overlap and their counts must not be added. Removing the profile
guard independently fails the pump/weir tests. Commits `1a1e5b6` (RUNTIME-V) and
`1f0acbd` (PACK-V) retain separate node evidence. No actionable product defect
was found; the literal issue string and non-specific author mutation assertion
remain documented non-blocking limitations. Runner/reader composition and native
regressions precede product integration.
