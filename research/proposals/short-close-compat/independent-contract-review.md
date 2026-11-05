**Finding.** A minimal correction is safe, but it must be limited to `profile_name == "short"`. I only read files here (no execution, no writes), so everything below comes from static review.

**Cause (confirmed by reading `runs.py:371-414` and `run_pump_lifecycle.py:610-681`)**
- `fail()` sets `termination_unconfirmed` at `runs.py:387-390` when `exit_evidence(run)["passed"]` is false.
- It then calls `close()` at `runs.py:402`.
- `close()` appends "Required all-member lifetime/forced-attribution evidence unproven" at `run_pump_lifecycle.py:662-663` whenever exit evidence is unproven. That sets `lifecycle["state"]="failed"` even when `close_assessment.passed` is true.
- `runs.py:403-409` then overwrites the public error with `short_cleanup_failed`.
- This matches the author's analysis. It is a real compatibility difference: the old wheel `eedd` did not guard `short`, so it never called `close()` there.

**Why the pump/weir path must not change.** `tests/test_pump_close_attribution.py:78-87` runs the same scenario (close passes, lifetime unproven). It requires `pump_cleanup_failed` and `cleanup_failed`, and it asserts that `close_assessment.passed` is true. A change applied to every guarded profile would break that test. Weir has a similar assertion at `tests/test_weir_run_profile.py:271`. So the gate must be short-only.

**Recommended predicate** (insert in `fail()` after the `close()` call at `runs.py:402`, and change the `if` at line 403):
```python
LIFETIME_ONLY = ["Required all-member lifetime/forced-attribution evidence unproven"]
ca = lifecycle.get("close_assessment") or {}
preserve = (record.get("profile_name") == "short"
            and error.code == "termination_unconfirmed"
            and lifecycle["state"] == "failed"
            and lifecycle["exit_evidence"]["passed"] is False
            and ca.get("passed") is True
            and ca.get("job_handle_close_confirmed") is True
            and ca.get("collector_close_confirmed") is True
            and ca.get("job_binding_confirmed") is True
            and "close_error" not in lifecycle
            and lifecycle["issues"] == LIFETIME_ONLY)
if lifecycle["state"] not in {"passed", "not_created"} and not preserve:
    ...  # existing replacement block unchanged
```
- Better still, export the issue string as a constant from `run_pump_lifecycle.py` and use it at both line 663 and in `fail()`. A literal copy in `runs.py` would break silently if the text changed.
- When `preserve` is true, keep these as they are:
  - `state="cleanup_failed"`
  - `record["error"]` as `termination_unconfirmed`
  - `validation.simulation="failed"`
  - `ownership.short_lifecycle` with state `"failed"`, so the raw unproven-exit fact stays recorded
- The `issues == LIFETIME_ONLY` equality does the real work. It excludes every other failure, including `close_error` ("Original close raised"), because that adds its own issue.

**Counterexamples that must still give `short_cleanup_failed`** (each should become a test)
1. `succeeded=False` or `return_value=0` on the Job `CloseHandle` receipt. This adds a second issue and sets `job_handle_close_confirmed` false.
2. A collector close error, `collector_close.errors` non-empty, or a wrong `state` or `return_type`.
3. `job.close()` raises while a passing receipt is still on `job.close_result`. That adds the "Original close raised" issue plus `close_error`.
4. The close receipt has a different token or a failed `_binding`, or `job_close` is `None` (not JSON-serializable).
5. `run.job is None` after a creation attempt. This gives `unconfirmed`, and `run.process` is also `None`, so the error is never `termination_unconfirmed`.
6. An error code other than `termination_unconfirmed`, for example `run_timeout` with exit evidence proven but close failed.
7. Pump and weir profiles with the exact short scenario. They must remain `pump_cleanup_failed` and `weir_cleanup_failed`.

**Paths the change does not touch** (neither is "close/storage failure becoming short_cleanup_failed"; both are separate public failures)
- A manifest write failure inside `close()` raises `short_lifecycle_persistence` (exit 6) before the predicate runs.
- A terminal publish failure raises `terminal_write_unconfirmed` from `publish_terminal`.

**Other points**
- `short_lifecycle_gate.assess` requires `completed` plus lifecycle state `passed`. The failed lifecycle is retained, so no success path opens.
- The normal-completion branch is unaffected: `start()` raises `short_job_close_failed` from `runs.py:428`. If `fail()` then re-enters, the error is not `termination_unconfirmed`.

**Author versus independent evidence**
- The author's evidence is `HANDOFF.json`, `error-code-analysis.json`, `effect-audit.json` and the installed replay. It is self-declared "author_not_independent_V", synthetic, and shows only that `close_assessment.passed` is true with `exit_evidence` unproven. It exercises only one positive case.
- My independent evidence is static code reading plus the protected pump and weir tests. I ran nothing, so the `tests/test_cli.py:308` test is not shown to turn green. I did not read the unreviewed `finalize.py` replay beyond lines 30-90, and I did not confirm the exact `issues` list from the installed manifest.
- Before acceptance, the negative cases above need a fresh run, not only the positive case.
