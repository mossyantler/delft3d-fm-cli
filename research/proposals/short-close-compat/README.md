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
Next steps are independent candidate execution, a new package freeze and the
runner/reader composition gate before any native lease or product integration.
