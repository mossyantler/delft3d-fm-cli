# SHORT-CLOSE Native V checkpoint

User requested pause after backup on 2026-11-05 (Asia/Seoul). No new implementation, review, tests or native work authorized. Coordinator owns Git/checkpoint persistence and push; this worker made no Git/root/dispatch edits.

## Safe terminal boundary

Last atomic operation completed: `test_raw_audit.py` exited 0; 7 unit methods / 107 persisted composition cases, 0 failures, 0 errors, 0 skips. No operation is still running. No native/GUI launches, PID queries, live sessions, retained process handles or background commands owned by this worker. No native lease is held. Global slot 228 is idle per user.

## Owned files and hashes

Current folder: `C:/Users/minyeop/project/delft3d-fm-cli/research/experiments/SHORT-CLOSE-NATIVE-V-rev04-20261105-01`. Candidate is NOT FROZEN and NOT G/native-approved.

- `api-contract-v1-SUPERSEDED.json` — `fbd74feaadceae90f43ccff32c4d2f15390b7d7bf7b3b8279ef0585998c8b986`
- `api-contract.json` — `11fe9b6cd3a8c77c3696735f693ee798ab33daf253afb946fdf696e401aa1bd2`
- `fixtures.py` — `e58a11f6ecd510a3b541acc61f139e346b77d142dca08db9df7472e69e0b0bd0`
- `raw_audit.py` — `ccabff06809a4629fbff50f2c67281dee516509735db8166133bd646a50c0b57`
- `test_raw_audit.py` — `aed7a7ab2d5da5cd77cf45a1b5a222522e00c35994b445ddd481874efc2bcd1d`
- `tests-01/verification.json` — `dc3612ac971f9c027d4e776125d2b634152ee33539e4238ffbd94db8f6070a7b`

`tests-01/` retains all 107 JSON input/result pairs and tests.log. Original #227 five manifests remained byte-identical; their hashes are in the test receipt. Historical states stay completed/failed/cleanup_failed exactly; no original receipt was rewritten.

## Implemented scope

- raw_audit.py: stdlib-only audit_record, assert_public_state, audit_control_survival; no product/common predicate imports. All original lifetime captures/births/images/HANDLE exits, original Job accounting/empty membership/real CloseHandle/collector closure checked separately from public state, physics and causal kill attribution.
- Original #227 forced records pass independent lifetime closure while keeping cleanup_failed public state. Missing early capture is rejected, even when old active-only classify would pass. Old classify is explicitly active-scope, not claimed buggy.
- Independent observer handles are NOT native Popen handles. Three live samples + final exit must match same retained observer object/birth/image and original-owner control root; any-Job query is only auxiliary. Final control original Job proof is independent. Close wrapper {final_snapshot,close} accepted; both pre-call and post-call observed_at conventions tested, without synthesizing raw wait values.
- Consistent cleanup_members are auxiliary only, not coverage; conflicting image/birth/exit/wait chronology refuses. Active Job snapshots and later per-HANDLE observations are non-atomic; no equality assumption between active snapshot and later live subset.

## Important unfinished work / do not infer acceptance

- api-contract.json is still PROSPECTIVE v2 and has stale close-schema wording relative to the implemented {final_snapshot,close} wrapper and timestamp handling. V1 was preserved explicitly as superseded. Finish a clear prospective contract update only after user resumes; do NOT seal current docs as a final API.
- No final source/API freeze yet. Archimedes producer requires actual pinned-reader composition and fake-driver tests before its freeze; standalone V 107 tests are not that combined acceptance.
- Pending additional checks considered but NOT started: strict manifest schema/version admission; redundant observer final monotonic chronology; broader auxiliary chronology and contradictory primitive probes. Do not claim these are implemented/tested.
- Need producer composition against current raw_audit.py, finalize exact state/control PASS keys and API docs, preserve original G interface probes, then independent G review. No native until explicit future exclusive lease and package/runtime V/G admission.
- Natural/badmesh/emptyBC original raw closure is separate from 600-second/final-restart/191-variable numerical gates; raw audit has physics_assessed=False. No all-members-killed or forced==completed claim.

## Exact resume references (DO NOT RUN WHILE PAUSED)

Inspect this checkpoint and tests-01/verification.json first. Do not rerun test_raw_audit.py directly: tests-01 is intentionally existing.

For authorized read-only integration only, import the exact pinned source with a standalone pure Python process:
```powershell
.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, r'C:/Users/minyeop/project/delft3d-fm-cli/research/experiments/SHORT-CLOSE-NATIVE-V-rev04-20261105-01'); import raw_audit; print(raw_audit.SCHEMA)"
```

Then coordinate with Archimedes thread 01a1a63e-c258-77c2-bc07-403709d8a207; author planning/adapter folder SHORT-CLOSE-NATIVE-I-rev04-20261105-01. Public pure API expected keys route/argv/working_directory/run_directory/executable_sha256/profile_name, optional run_id. State expectation family/route/allow_natural_race, optional control_terminal_states. Raw audit pass: audit_state qualified_full_lifetime_close plus lifetime_passed/actual_job_close_passed/collector_close_passed True. Survival pass: independent_control_survival_confirmed plus passed/control_lifetime_passed/observer_same_handle_confirmed True. Natural-race state returns passed True but case_success False.

## Other frozen work / handoff

- B06 adapter execution was handed solely to Faraday in B06-PROVENANCE-V-FAR-20261105-01. EIN requirements/sourceaudit/70 negatives + 6 positive controls remain frozen under B06-PROVENANCE-V-EIN-20261105-01; no duplicate adapter execution by this worker.
- B14 source/interface ACKs rev01–rev05 are retained. Latest completed rev05 ACK: B14-V-INTERFACE-ACK-rev05-20261105-01/verification.json SHA3a98deb7552badca181dcc005fc31c9799e3a3fc62c6a2cfc9be5d099652f626. Source-only, never full-runner/native approval. Rev06 request arrived but was NOT audited here due critical native-audit priority; parent says no rush until Plato.
- B14 science/consumer freeze remains 0b7c26e8a5d04343e7ef305f8568bd3e836f1bb0e054a77ff819260b64096ee1; scientific inputs/tolerances unchanged. Public direct routes/common composition remain separate held dependencies.

Paused now. No further worker edits after this checkpoint.
