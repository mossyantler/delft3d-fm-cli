# Paused checkpoint — 2026-11-05, Asia/Seoul

Explicit user STOP after checkpoint/backup. **No native, GUI, worker, live exec
session or retained process HANDLE remains from my work.** Every invoked Python
command returned; no subprocess/FFI was used by preparation/tests. Native slot
228 remains idle, NOT a grant. No Git/root/dispatch/shared-doc edits or push.
Coordinator owns backup/push. Do not resume without explicit authorization.

## Current private node: NOT frozen, NOT accepted

`SHORT-CLOSE-NATIVE-I-rev04-20261105-01` contains prospective twelve-case public
run adapter and prepared inputs only. No freeze.json, runtime admission or lease.
Old scripts/#227 and all earlier common/package evidence remain unchanged.

| File | SHA256 |
|---|---|
| prepare.py | fd0d6662eab5bf5c0832f0a489bcb45fa44c2992c82b18bc3da358ca6afcfdc0 |
| admission.py | dad725e859c00f18e5d51a0bb4cd83127fea9a0cef1b2df97fd7fc229d3f089a |
| warm_client.py | 508adf798d2c75d79d4b8499a1fbf8c62e6df7866600b1552868367499896e7b |
| public_driver.py | 9bd09cab97c805058a3f7a1641c1c31c469345d7e8d5f7117552ab1377dffa21 |
| replay_adapter.py | d57e1fdc8bc1572c69ace2e875aa0e190609f023fd3a719ac5aaa80e0e4cddb0 |
| test_portable.py | 035aed468e10b4280188d929d99aed70ae2c310b99731cb1e8ea8b48145af2b3 |
| test_flow.py | f638317d12ec152c752e6077df55dc4dc5b2c21975d4df4b07dfdca898a29a0f |
| expected-product.json | 221e391b4e07e149535c36b234317d7c4a2bb6c9346c6f77028623560997dacb |
| prepared-01/predeclared.json | b78599205de505604fb3821c91caf3fddbc7ca44ae9c009c8c423e977064f30d |
| portable-tests.json | 9917164f7dbf0acf5bbc9151c7c299babf0b8e4ec80b5f7cfa2c9565d487d8fe |
| composition-probe-01/verification.json | 13ed869bf42a7eb0b52638784377028030e7b28ab332ffcd0a8d14ebc1575976 |
| composition-probe-01/raw_audit_snapshot.py | a7b8429b7eb49f85d5e73ac1863d6828640813b5bfb2418dad00ace9c692f88b |

The predeclaration records SHA/size for all **40 copied inputs** (four ten-file
graphs), verified byte-identical to #227 inputs: valid, slow(DtMax0.0001), corrupt
mesh only, BC truncated before first [Forcing] only. No native outputs copied.
`expected-product.json` is the expected common191 contract, NOT runtime admission.
Plan: direct then DIMR, each natural/bad-mesh/empty-bc/control/timeout2s/cancel,
max12, max2 concurrent, one attempt/no retry. Installed CLI is sole native owner.
All terminal cases need independent lifetime + original Job/member/collector
close; control survival and natural600s/restart/raw191 comparator are separate.

## Checks actually completed (not additive)

- `portable-tests.json/log`: 12 PASS, zero failures/errors/skips; earlier mutable
  adapter revision. No final-source whole-adapter rerun claimed.
- `flow-tests-01.json/log`: 3 PASS; `flow-tests-02/03/04.json/log`: 6 PASS each.
  Latest checks exercise control-readiness failure, target mid-start error,
  natural race before ready (completed record retained, no target cancellation),
  single owner already naturally failed before error, receipt-storage failure
  still disposing both owners, and unstarted warm-client abort. Fake driver only.
- `composition-probe-01`: exact **unfrozen** V reader snapshot SHA a7b842…;
  five original #227 records read-only. Natural/bad-mesh/empty-bc lifetime+close
  and public-state checks pass. Timeout/control lifetime+close pass while public
  state correctly refuses original cleanup_failed. No historical reclassification.
  This is an interface probe, NOT final pinned-reader composition/acceptance.
- No new tests were started after the user STOP. No native/FFI/root writes.

## Important implementation state / remaining work

1. Einstein's independent reader/API is still prospective at
   `SHORT-CLOSE-NATIVE-V-rev04-20261105-01`. APIv2 last communicated SHA
   11fe9b6cd3a8c77c3696735f693ee798ab33daf253afb946fdf696e401aa1bd2;
   code continued changing before STOP. Do not treat snapshot a7b842 as final.
2. G requires actual composition tests against the **exact frozen V reader**:
   natural, bad mesh, empty BC, mixed live/early retained members, control survival,
   missing-original-early-capture negatives, and full fake-driver error disposal.
   Those final composition tests/fixture builder are not yet written/completed.
3. APIv2: state expectation uses family/route/allow_natural_race; require passed
   AND case_success. Natural race is observed/unexercised, never forced pass.
   Control declared terminal states now only ['cancelled']; no failed-state pass.
4. Survival bundles use schema SHORT-CLOSE-NATIVE-V-control-observations-2.
   Observer HANDLE is independently opened/captured live, NOT native Popen;
   IsProcessInJob(None) is ANY-Job only. Original exact Job/lifetime comes solely
   from independent raw-owner audit. No synthetic wait258/exit/flags.
5. G's interface probe found pre-call close observed_at timestamp. Current driver
   stamps started before real call, finished after return, observed AFTER finished.
   This fix and the narrowed control-state expectation still need exact final
   reader composition tests. Snapshot fields are preserved; close wrapper is
   {final_snapshot,close}, fixed observer_id, actual typed API return.
6. Admission gate is mutable/untested as a complete admitted composition. It
   requires exact canonical dispatch owner SHORT-CLOSE-NATIVE-G and fresh seq>228,
   source2254/common191, exact Raman package, full installed191/launcher/Python
   and critical-origin rehashes, selected binaries/libraries, exact V module,
   fresh direct experiments/SHORT-CLOSE-G-native-rev04-* output; rechecks pre-go.
   G admission JSON/template/HANDOFF/final freeze are not yet produced.
7. Review remaining bounds/documentation: code has 600s scheduling deadline plus
   separately bounded original-owner disposal waits (110s/owner); prepared plan's
   native_batch_wall_seconds=600 wording must be reconciled honestly before freeze.
   Never abandon an owner or invent a kill to meet a wall bound.
8. Finish-only cleanup is idempotent; storage errors cannot prevent other owner
   disposal. Original terminal records are not rewritten by adapter/auditor.
   No root production predicate/old classify is an independent acceptance oracle.

## Earlier immutable references (do not modify)

- Common rev04 freeze2254e8835cd8a70beabea1af2860db751b28dbea2fb60f06ccd773d4b6d198e1;
  lifecycle49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207;
  runs4e1d3c75a5fa5ddbcba2236388ef5248e6b4884c2e023f3b2cc66858456eb82c.
- Independent common V final ec0aa1305451ea07f6dd686e128fcef69c1d173d6975ff6e5aafacb05bbc4c6b.
- Raman common191 package freeze001c82139a632d34c05957f10bab3396e32df5289bad4c62efb374bb055462d6;
  wheel f7eb645f48bf51cb6176970a749f09bc040472be5969b469892ac8b848a9586b.
  Its native contract is UNADMITTED; package V/G acceptance is coordinator's node.
- Prior e4a7 rejected V121=120/121 remains frozen; rev04 fixes optional auxiliary
  top-level image contradiction without granting any auxiliary coverage.

## Exact safe resume command (read only; requires authorization to do more)

```powershell
Get-Content -LiteralPath 'C:\Users\minyeop\project\delft3d-fm-cli\research\experiments\SHORT-CLOSE-NATIVE-I-rev04-20261105-01\CHECKPOINT.md'
```

After explicit resume authorization, first obtain Einstein's final frozen packet
and coordinator state; then finish the outstanding offline composition work.
Do not execute the prospective replay command or infer a grant from idle228.
Coordination: Einstein thread01a1a56e-574a-7ae1-aa51-101c4d765368;
Raman01a1a632-c8e1-7700-b59d-8f610117aab9. Parent/coordinator owns Git backup.
