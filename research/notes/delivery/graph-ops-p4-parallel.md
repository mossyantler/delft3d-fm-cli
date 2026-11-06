# Contract: GRAPH-OPS-P4-PARALLEL

Phase 4 of [INTENT.md](../../../INTENT.md#phase-4--작업-격리와-독립-검증): several agents work on different
Beads tasks at the same time, without file, Git or native-resource conflicts, and only verified results
unblock later work. Builds on `research/workflows/graph/dispatch.py` (Contracts C1–C5 in
[graph-ops-p3-dispatch.md](graph-ops-p3-dispatch.md)). User request: 2026-11-06, "GRAPH-OPS: 실제 다중 에이전트
병렬 오케스트레이션 구현 및 검증".

## Diagnosis (coordinator, observed 2026-11-06)

- **Herdr is not the limit.** Two dispatched agents already ran at the same time in the real session:
  `livefix-v` (Codex, `dfm-fmc.42`) and `b06-reader-v` (Claude, `dfm-985.3`); earlier, `dispatch-i` and
  `dispatch-v` ran I and V-Plan in parallel. Each had its own pane, session and worktree.
- **`dispatch start` does not block.** It returns once the prompt has started a turn, so the coordinator can
  start a second agent while the first one works.
- **What is missing is tooling, not capability:**
  1. No concurrency limit. Any number of `start` calls succeed.
  2. No file-ownership record, so two implementers that edit the same file are not stopped.
  3. No serialization of native runs between dispatches.
  4. No view of all active dispatches, and no reconcile step after a coordinator restart. Recovery was
     done by hand in GRAPH-OPS-P3-RECOVERY.
  5. `collect` checks only `task_code`. A wrong `candidate_sha` or missing evidence is accepted.
  6. Nothing checks that a node's finished predecessors have collected receipts, or that a verifier's
     verdict was PASS, before the next stage starts. Beads blockers only check that the nodes are closed.
  7. Choosing ready tasks is manual. No command starts every dispatchable ready task.
- **Beads dependencies are correct where they exist.** I and V-Plan block V-Run, and V-Run blocks G.

## P1. Ownership and resources on `start`

`start` gains these options:
- `--owns <path>`, which may be repeated. It names a repository-relative file or directory prefix that the
  worker may edit. Each path is normalized to forward slashes, with no `..`, nothing absolute, no empty
  part, and no trailing slash.
- `--native`, which marks a dispatch that needs the exclusive native lease.
- `--approved <HUMAN-id>`.

`metadata.dispatch` records `owned_paths` (a sorted list, `[]` when none is given), `native` (true or false)
and `approved` (null when not given).

## P2. Preflight on `start`

These checks run before any side effect. Any failure is exit 2 with `refused`, and nothing is created or written.

An **active dispatch** is a node whose status is `in_progress` and whose `metadata.dispatch` has no `ended_at`.

1. **Limit.** Refuse when the number of active dispatches on other nodes is at least the limit. The limit is
   `--max-parallel N`, else `DFM_DISPATCH_MAX_PARALLEL`, else 2. It must be a whole number of at least 1.
2. **Ownership.** Refuse `ownership_conflict` when an owned path is equal to, or is a directory prefix of,
   an owned path of another active dispatch, in either direction. The refusal names the other node and both
   paths. `research/workflows/graph` and `research/workflows/graph/dispatch.py` conflict;
   `research/a` and `research/ab` do not.
3. **Native.** Refuse `native_busy` when `--native` is given and another active dispatch is native.
4. **Model policy.** Refuse when the effort is not one of `low`, `medium` or `high`. Refuse when the model id
   contains `astra` or `opus` (case-insensitive) and `--approved` does not match `^HUMAN-[0-9]{8}-[0-9]+$`.
5. **Predecessor evidence.** For each blocking dependency, refuse `missing_receipt` when the dependency has a
   `metadata.dispatch` but no `metadata.receipt`. Refuse `failed_predecessor` when its receipt `verdict` is
   anything other than `PASS`, or its `outcome` contains `fail` or `reject` (case-insensitive). Dependencies
   that were never dispatched are judged by Beads status alone, as today.
6. Every existing refusal from C2–C5 still applies.

## P3. `fill` (coordinator)

`fill [--max-parallel N] [--dry-run]` reads `bdw ready --json --exclude-type epic` and keeps the tasks that
have `metadata.plan`. `metadata.plan` is written by the coordinator and has `packet`, `kind`, `model` and
`effort`. It may also have `owns`, `native`, `approved`, `base` and `name`.

- Tasks are taken in Beads priority order, then by id. Each one runs through the same preflight and start
  as `start`, with the arguments taken from `metadata.plan`, until the limit is reached.
- A task that is refused or fails is reported with its reason, and `fill` continues with the next one.
  One failed worker never undoes another worker's start.
- Ready tasks without `metadata.plan` are reported as `no_plan` and are not started.
- `fill` never starts a node that already has a dispatch without `ended_at`, whatever its status is.
  An uncertain earlier attempt is left for the coordinator to review.
- With `--dry-run`, `fill` reports what it would start and writes nothing.
- The output is one JSON object with `started`, `skipped` (id and reason), `limit` and `active_before`.

## P4. `status` (any role) and `reconcile` (coordinator)

- **`status`** lists every active dispatch with:
  - the node id, task code, agent, kind, pane, session id, worktree and model;
  - `started_at`, attempt, `owned_paths` and `native`;
  - `receipt_collected` (true or false);
  - `live`: true, false or null. It is null when Herdr cannot be reached. It is read-only.
- **`reconcile`** compares every active dispatch with live Herdr and the worktree.
  - **Live** (`agent get` succeeds and the pane matches): no write.
  - **Not live:** writes `metadata.dispatch.review` with `state` (`finished` when a receipt has been
    collected, otherwise `needs_review`), `reason`, `detected_at`, `worktree_exists` and `worktree_dirty`.
    It also adds one English comment. It does not change the status, does not set `ended_at`, does not start
    anything and does not remove anything.
  - **Herdr unreachable** (exit 2 with `error`): nothing is written for any node.
  - The output also lists:
    - `in_progress` nodes that have no active dispatch (`untracked_in_progress`);
    - live Herdr agents that no active dispatch records (`unrecorded_agents`), report only.
- Running `reconcile` twice gives the same result and adds no second comment for an unchanged state.

## P5. Fan-in checks in `collect`

Refuse with exit 2, and write nothing, when any of these holds:
- **Commit.** The receipt has a non-null `candidate_sha` that does not resolve to a commit in the main
  repository, or that is not a descendant of, or equal to, the dispatch `base_sha`.
- **Evidence.** The receipt has an `evidence` list and an entry does not exist. Relative entries are taken
  from the receipt's folder.
- **Verdict.** The receipt has a `verdict` that is not `PASS` or `REJECT`.

A `REJECT` receipt is collected and recorded. It then blocks dependents through P2.5.

## P6. `gate <id>` (any role, read-only)

`gate` reports `ok: true` only when:
- every blocking dependency is `closed`;
- every dispatched dependency has a collected receipt;
- no receipt is a failure in the P2.5 sense.

Otherwise it gives `ok: false` with one reason per dependency. The exit code is 0 in both cases, and the
answer is in `ok`. The coordinator runs `gate` before starting or closing a G node.

## P7. Unchanged policy

- Merges and pushes stay with the single coordinator, one branch at a time (COORDINATOR rule).
  Dispatch never merges, commits or pushes.
- Every worker has its own worktree `<main>-wt/<TASK_CODE>`. The C2 path rules stay.
- Native runs still need the coordinator's review and the lease. P2.3 only stops two native dispatches.
- I and V stay separate sessions, and V uses a different vendor where possible.

## Safety

Contract C3 still applies. Tests and verification use throwaway repositories, throwaway Beads workspaces, a
fake Herdr and fixture transcripts only. All text that dispatch writes for agents is English.

## Done when

- `research/workflows/graph/test_dispatch.py` covers every P1–P6 clause with the fake Herdr. The existing
  `test_bdw`, `test_dispatch` and `test_dashboard` pass, and `python -m compileall -q research/workflows` is clean.
- The committed verifiers `verify_dispatch.py`, `verify_codefix.py` and `verify_livefix.py` still pass as
  regressions. If a regression case contradicts P2 or P5, for example a fixture receipt with a made-up
  `candidate_sha`, V lists it with the reason and does not count it as a defect.
- **G's live trial in the real Herdr session.** The fake-Herdr tests do not prove live behaviour.
  - Test A: a Claude agent and a Codex agent on two independent mock tasks, started by one `fill`, with
    overlapping run times.
  - Test B: a mock Contract → I ∥ V-Plan → V-Run → G graph.
  - Test C: an ownership conflict refused.
  - Test D: `reconcile` after a coordinator restart while an agent is live.
  - Test E: bad receipts refused and `gate` closed until the receipts are valid.
