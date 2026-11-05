# NATIVE-READER-I handoff

Worker model: **Claude Sonnet 5.5 (`claude-sonnet-5-5`), high effort**, as assigned.
Status: **frozen candidate**, pending coordinator review and independent G review.
`native_authorized: false`. Not product code. No Git operation, no shared-doc edit,
no native/GUI/process/Job/FFI call, no package install. Nothing under
`research/proposals/short-close-native-adapter` or the checkpoint was opened for
writing; the checkpoint `native-V` files are byte-unchanged.

## Freeze

`freeze.json` sha256 `980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62`
(`artifact_files`: filename -> `{sha256, bytes}`; re-hashed independently, no mismatch,
no unlisted file). Listed files:

| File | sha256 |
|---|---|
| raw_audit.py | `ddf31bae3ec558a5d0ec27b739990e4201ccc16908013069f7b6b7df8b76e215` |
| api-contract.json | `90e867263e5b555ebc5b98e45810e02bec5b2980f5e8c316d697af8b1dfc355d` |
| fixtures.py | `486d0cbc8805b2b98139aa37c3bbbac7208a9c41e6573adf17a835dc46bd7373` |
| test_raw_audit.py | `b1c5c444884440fba248b7bad682297d77d3a0c1f1d6eb77f7f2f017997ce1f8` |
| api-contract-v1-SUPERSEDED.json | `fbd74feaadceae90f43ccff32c4d2f15390b7d7bf7b3b8279ef0585998c8b986` (byte-identical to checkpoint) |
| PROVENANCE.json, VALIDATION.json | see `freeze.json` |

Checkpoint candidate (immutable): raw_audit `ccabff06…`, contract `11fe9b6c…`.

## API — **not breaking**, API id stays `SHORT-CLOSE-NATIVE-V-raw-api-2`

Signatures, pass keys, the `control-observations-2` input schema and every result
schema string are unchanged. Acceptance is **stricter** and two result fields were
added (`manifest_admission`, `members[].exit_code_equals_requested_code`). The
semantic identity of the reader is therefore the `raw_audit.py` hash, not the schema
string — pin the hash.

```
audit_record(record, expected) -> dict
assert_public_state(record, expectation) -> dict
audit_control_survival(target_record, control_record, observations, expected_control) -> dict
```

Pass keys:
- record: `audit_state == "qualified_full_lifetime_close"` and `lifetime_passed`, `actual_job_close_passed`, `collector_close_passed` all `True`.
- state: `passed is True` and `case_success is True` (natural race: `passed` True, `case_success` False, `natural_race_observed` True).
- survival: `audit_state == "independent_control_survival_confirmed"` and `passed`, `control_lifetime_passed`, `observer_same_handle_confirmed` all `True`. `audit_state == "not_observed"` means a required live/exited window was missed (never a pass).

Close wrapper is exactly `{final_snapshot, close}`; `final_snapshot` is a **later,
distinct** exited snapshot (the adapter's `close_observer()` shape) or the exit sample
itself. Observer `in_a_job` is the any-Job result and is only required `True` on live
samples. Real label keys `handle_role`/`image_observation`/`membership_scope` are
accepted when exact; any contradicting label refuses.

## What changed from the checkpoint candidate

1. Manifest admission: `schema_version == 3`, terminal public state, original launch-HANDLE identity source, `created <= started <= finished`, `created <= Job association`, `initial_job_pids` contains the root and only lifetime PIDs, forced `stop_reason` equals the actual request reason. **JSON protocol is not checked**: the manifest has no such field (protocol 2 is the stdout envelope); reported as `json_protocol_checked: false`.
2. Observer chronology: every adjacent same-observer pair (including `final_snapshot` after the exit sample) needs UTC non-decreasing, monotonic strictly increasing (equal only for the identical snapshot) and UTC/monotonic deltas within 1 s. Only UTC is compared across observers.
3. Auxiliary/primitive contradictions: stop-time observations earlier than the same HANDLE's capture; `unavailable`↔`error` mismatches; post-exit image query claims; one shared exit-primitive check for member, root_handle and auxiliary exits (`GetExitCodeProcess` return, `confirmed`, timeout, exit code equality, not before request return). Exit-code equality with the requested code is reported as an observation only.
4. `test_raw_audit.py` now requires a **fresh output folder argument** and optional `--baseline`; it refuses an existing folder or one inside the source folder.

## Validation (synthetic/offline only; counts are not additive with the checkpoint run)

Final run `research/experiments/SHORT-CLOSE-NATIVE-READER-I-20261105-01/tests-03`,
run on exactly the frozen sources: **10 unit methods, 215 cases (107 original + 108
adversarial), 0 failures, 0 errors, 0 skips**. The 107 original cases have
**byte-identical inputs and identical verdicts** to the checkpoint's `tests-01`; the five
#227 manifests are byte-unchanged and historical states stay completed/failed/cleanup_failed.
Every new negative asserts the *intended* reason. Mutation check: disabling each of 13
new checks in a scratch copy makes the tests fail (13/13 caught). Static AST audit: `raw_audit.py` imports only
`datetime, hashlib, json, pathlib, re`; no open/exec/eval/subprocess/ctypes/os.
Preserved: `tests-01` (failed: two harness defects — case-group tag depended on class
order, one duplicate case name — no reader defect) and `tests-02`.

## Remaining limits (do not over-read)

- All observer bundles are **synthetic**; no real adapter snapshot has been read. The 1 s skew bound, `in_a_job == True` on live samples and the `observed_at` conventions are untested against real records. A real-record refusal means fix the producer or raise to G, not loosen silently.
- Equal timestamps cannot order a live/signalled pair across handles and are accepted.
- `exit_image_query` "captured" shape never occurs in the originals; its check is a conservative reading. Public chronology bounds rest on the five originals plus launch order.
- Closure is not causal kill, clean finalization, 600 s/restart/191-variable physics, or a numerical verdict (`physics_assessed` is always false). Natural/bad-mesh/empty-bc original closure and the numerical gates stay separate.
- No composition with the adapter, no independent G review, no package/runtime admission, no native lease. The adapter is expected to pin this freeze hash and treat any `passed`/`case_success` logic as above.
- `research/experiments/` is git-ignored here: `VALIDATION.json` is the portable receipt; raw evidence (`tests-01..03`, `mutation-01`, `freeze-01/make_freeze.py`) stays local. The coordinator serializes any commit of the new proposal folder.
