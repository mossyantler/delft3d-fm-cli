# Coordinator guide

Agent summary of [INTENT.md](INTENT.md). If they conflict, INTENT wins. Edit both
together. Read the root [AGENTS.md](AGENTS.md) first. This file is for the
coordinator. Workers read their Task Packet, not this file.

**Coordinator session model:** GPT-6.1 Sol `high` or Claude Opus 5.5 `high`
(user decision 2026-11-06, INTENT §5.1 and `coordinator_session`). Opus is
approved only for this session. Workers you assign still follow the model
policy below.

**Beads** records what must be done. **Herdr** runs the agents. **Git worktrees**
isolate their changes. The **validation gate** checks completion criteria.
**G** decides acceptance. GitHub and artifact storage hold the reproducible
evidence. These responsibilities never overlap.

## Transition status (update when a phase closes)

| Phase | Status, 2026-11-07 |
| --- | --- |
| 0 Inventory | Done. [Phase 0/1 report](research/notes/delivery/graph-ops-phase0-1.md) |
| 1 Beads trial | Done. `bd` 1.3.1 at `research/tools/beads/1.3.1/bd.exe`; 15/15 checks in `research/experiments/GRAPH-OPS-P1-20261106-01/verification.json` |
| 2 Migrate graph | Done 2026-11-06 (user-approved). [Phase 2 record](research/notes/delivery/graph-ops-phase2.md): bdw I/V/G, workspace init, 46-issue seed (7 epics, 39 tasks), DELIVERY cross-check |
| 3 Herdr integration | Done 2026-11-06. [Record](research/notes/delivery/graph-ops-p3-dispatch.md#phase-3-close-coordinator-2026-11-06): dispatch tool, CODEFIX, recovery trial, LIVEFIX (C5), B06 reader pilot |
| 4 Isolation and parallel work | Done 2026-11-07. [G record](research/notes/delivery/graph-ops-p4-parallel.md#g-record-coordinator-2026-11-07): `fill`, `status`, `reconcile`, `gate`, ownership and model policy; live Tests A-E |
| 5 | Blocked on 4. |

Beads is the single source of truth for active state and dependencies. Read and
write it only through **bdw**:
`python -m research.workflows.graph.bdw <bd command>`. bdw works from any
checkout or worktree and derives the shared workspace
`<main checkout>-beads/.beads` by itself. Writes require `DFM_BD_ROLE=coordinator`
in your own environment; every other caller is read-only. Do not call `bd.exe`
directly. [DELIVERY.md](DELIVERY.md) keeps approval records and a snapshot from
`python -m research.workflows.graph.seed report`. Nobody edits a status by hand.

**Dashboard (read-only):** `python -m research.workflows.graph.dashboard pages`, then `... preview`
(http://127.0.0.1:9000, Ctrl+C stops) or `... tui`. bv 0.25.2 reads only a copy in
`<main checkout>-beads/dashboard/source/`: a fresh export for the coordinator, the export committed at HEAD
for anyone else. bv runs without bd on PATH, without Beads variables and without hooks, so its edits go nowhere.

Not authorized by INTENT or by this file: product code changes, native runs,
unapproved merges, remote sync. Each needs its own explicit approval.

## Coordinator loop

1. `bdw ready --json --exclude-type epic`, then `bdw show <id>` for the candidate
   only. Never load the whole graph or long histories. Here `bdw` stands for
   `python -m research.workflows.graph.bdw`.
2. Confirm the Contract and prerequisite G approvals. Confirm the evidence exists
   at the cited commit or path.
3. Check for conflicts in owned paths, shared files, Git operations and native or
   fixture resources.
4. Select the model (see below) and write a Task Packet.
5. Start or reuse a worker. Record the execution log.
6. Watch the session. Collect the result receipt.
7. Run the deterministic gate (Python/CLI), never an LLM, for checks code can
   decide.
8. On failure, route it by type (see Failure and recovery).
9. After G approval:
   - close the Beads task with its evidence in `--reason`;
   - add a line to DELIVERY.md「최근 승인」 and regenerate the snapshot;
   - run `bdw backup-sync` and commit the refreshed
     `research/notes/delivery/beads-state.jsonl` with the node
     ([backup and restore](research/notes/delivery/graph-ops-backup.md));
   - push the approved commits.
10. Return to step 1.

Close a task only on evidence you have checked yourself. When you cannot
confirm a result, leave the task open and record why.

## Graph model

- One **Epic** per feature (for example, B06 Source/Sink). Its tasks are
  `<CODE>-Contract`, `-I`, `-V-Plan`, `-V-Run`, `-G`; split I or V further when
  large. Beads generates the issue ID. The project code goes in the title or
  metadata.
- Dependencies are explicit `blocks` edges. Contract blocks I and V-Plan, which
  run in parallel. I and V-Plan block V-Run. V-Run and the required automatic
  gates block G. A downstream Epic is blocked by the upstream **G**, never by I.
  Never infer order from Epic membership.
- Statuses: Open, In Progress, Blocked, Deferred, Closed. Acceptance is expressed
  as a closed G task with its evidence. I or V being closed is not Epic
  acceptance.
- Useful commands (all through bdw): `ready --json --exclude-type epic` (otherwise
  epics with no dependencies appear as ready), `ready --explain`, `blocked`,
  `show`, `dep tree`, `dep cycles`, `graph check`. New task:
  `create "<CODE>: <title>" --parent <epic> --metadata '{"task_code":"<CODE>"}' -l role:<role>[,needs-lease]`,
  then `dep add <blocked> <blocker>`. `doctor` does not support embedded mode.
  Epics stay open after their children close, so acceptance is the closed G task.
- **Human nodes** record every decision that belongs to the user: phase
  transitions, premium calls, native runs, merges, pushes, remote sync, tool
  installs, and any other question the coordinator cannot settle.
  - Before the step, create
    `HUMAN-<yyyymmdd>-<nn>: <question>` under the epic with labels `human,role:human`
    and metadata `{"task_code","kind":"user_decision"}`, then
    `dep add <step> <human-node>`. The step cannot become Ready until the user
    decides.
  - Ask the user in chat. Record the verbatim decision in metadata `answer` and in
    the close `--reason`, then close the node (user decision 2026-11-06,
    `HUMAN-20261106-11`).
  - If a worker asks the user directly, record that answer the same way.
  - Pending decisions: `bdw list --label human` (open only).
- Record which worker holds a task with a label or note, and **never as the
  `--assignee`**. bd treats an assignee as a claim, and then refuses to let anyone
  else, the coordinator included, update or close the task. If a claim was left
  behind by a session that has ended, release it with
  `bd --sandbox unclaim <id> --if-assignee <name>` and record why.
- What bdw enforces (Phase 1 and BDW-V evidence): pinned bd 1.3.1 SHA-256, the
  out-of-tree workspace, `--sandbox`, metrics/hooks/remote adoption off, and
  `--readonly` plus a read allowlist for workers. Init, sync, dolt, vc, config,
  delete, integrations and caller-supplied `--sandbox/--readonly/--actor` are
  refused for every role. It is a tool policy, not a security boundary. Running
  `bd init` inside the working tree would commit `.beads/`, `.gitignore` and
  **whatever is already staged**. `beads.role` is set to `maintainer` in local
  `.git/config` by user decision on 2026-11-06. It only affects bd's issue
  routing, which this project does not use, and it is unrelated to
  coordinator/worker permissions. On a new machine, run
  `git config --local beads.role maintainer` once.
- Storage: Dolt embedded mode with you as single writer. All worktrees of the
  repository share one Beads workspace. No per-worktree database, no extra
  SQLite. Consider Dolt server mode only when concurrent writers become
  necessary, and Dolt remote only for several clones or machines. Dolt sync and
  Git merges are separate operations.
- History: failure evidence of rejected candidates, raw native records,
  checkpoints, accepted base commits and reproduction data all stay. Review a
  retention policy before any Beads compaction or cleanup.

## Task Packet

A worker receives only this, plus `AGENTS.md` and the directory guide for its
paths:

```text
Node: <CODE>-<role>  (Beads <id>)        Role: I | V-Plan | V-Run | G
Goal: <one sentence>
Contract: <path>@<sha>                    Base commit: <sha>
Approved inputs: <G receipts / artifact refs of prerequisites>
Owned paths: <write scope>                Read-only: <shared files it may read>
Resources: <none | lease id and scope>
Evidence to use: <paths, commit SHAs, artifact IDs; no pasted logs>
Done when: <checkable, exhaustive criteria>
Submit: changed files, diff/commit, commands run with results, receipt JSON
```

Pass references (paths, SHAs, artifact IDs, receipt JSON, a minimal diff, a short
failure summary) and keep pasted logs out of the packet. A V packet carries the
Contract and the frozen candidate commit or fingerprint, and leaves out the
author's self-assessment. A worker's private state (scratch analysis, debug
trail) stays private. What crosses to others is shared state: status, artifact
refs, Contract changes, results, blockers, approvals.

Reuse a session only for short repair loops on the same task. Use a fresh
session to start verification, to switch tasks, when prior context could bias a
judgment, or when context is large. Keep stable instructions separate from
per-task data so prompt caching can work.

## Model selection

The policy YAML in [INTENT §6.8](INTENT.md) is the single source for candidates,
pools, effort defaults and limits. Never copy its values elsewhere. The goal is
the lowest **total cost per accepted task**: implementation + verification +
integration + rework + tools.

1. If code can do it, call no LLM.
2. If the scope is narrow and the result checkable, use a lightweight model
   evaluated for that task type (Luna, Haiku).
3. For visual, GUI or document extraction, use Terra or a suitable Claude
   model. Judging what the extracted values mean belongs to code or a separate
   verifier.
4. For design, multi-file implementation or independent judgment, use Sol or
   Sonnet. They are equal candidates; choose by measured results per task type,
   with no fixed role per vendor.
5. Escalate to premium (Opus or Astra) only when a general model has demonstrably
   failed, or the question is exceptional from the start.

- Until the evaluation in INTENT §6.7 exists (Phases 3–4), use only three pools:
  rule-based, general (Sol/Sonnet `medium`, `high` when complex) and approved
  premium.
- Never sweep models cheapest-first. Repairs after the first attempt are capped
  at 2 per cause. Fix environment, file, permission or command errors without
  switching models. When switching, hand over only the Contract, the candidate
  commit, a reproducible failure, a short summary of the failed approach and one
  concrete question.
- **Premium** needs user approval with a written question, the limits of the
  prior approach, the input scope, the expected call count, a usage budget and a
  verification method. Prefer Opus when both fit. Never chain Opus into Astra,
  never auto-escalate, never auto-substitute. Return to general models for the
  remaining work. Astra's effort is capped at `high` with no exception. Fable is
  disabled unless separately approved.
- Effort: use only levels the runtime supports. Automatic assignment goes up to
  `high`. High-cost modes are never enabled automatically.
- Verification independence: give V a separate session and, where possible, the
  other vendor. For high-risk work, agreement between models is not evidence.
  Require independent criteria, a frozen candidate, a raw-data check, the
  regressions, the required native verification and the G procedure.
- Verification weight (user decision, 2026-11-07): the full procedure above is for product
  CLI work (`src/dfm_cli`, native runs). Tool nodes (`research/workflows`, dispatch, bdw) and
  doc nodes get a light check: author tests plus a short independent check of the core cases or
  a coordinator check, with no large verifier suite, regression re-runs or repeated live rounds.
- Before assigning a model, verify that it is available with its exact model ID,
  supported effort, tools and billing mode on the installed runtime. Previously
  seen IDs or prices are not verified settings.

## Starting agents

Use **dispatch** for assignments (coordinator only). New executions use
[protocol 2](research/notes/delivery/graph-ops-reliability.md), which supersedes
Phase 3/4 intake, retry, resource-release and gate clauses for new work. Historical
approvals keep their original meaning. Read the protocol before using a new plan.

```powershell
python -m research.workflows.graph.dispatch start <id> --packet <file> `
    --kind codex --model <verified-id> --effort medium --role I --task-kind code `
    --contract-sha <commit> --owns <path> --runtime-proof <probe.json> `
    --task-class general_implementation
python -m research.workflows.graph.dispatch fill --dry-run
python -m research.workflows.graph.dispatch status
python -m research.workflows.graph.dispatch reconcile
python -m research.workflows.graph.dispatch gate <id>
python -m research.workflows.graph.dispatch collect <id> --receipt <file>
python -m research.workflows.graph.dispatch stop <id>
```

`start` records intent and frozen packet bytes before creating resources. It
tracks worktree, pane, session and prompt stages. It never retries an uncertain
submission. Before retrying, inspect the prior attempt and explicitly release
its resources. A closed task is not a terminated execution. I, V and G continue
to use separate owned worktrees; V-Plan gets the Contract without the author's
analysis, and V-Run gets the frozen candidate and plan.

`fill` is one scheduling pass, not an autonomous coordinator: no plan produces
`no_plan`; an invalid or legacy plan produces `bad_plan`; policy/approval,
resources, predecessors and worktree refusals carry distinct codes. The
coordinator prepares missing packets/plans and resolves the reported blocker.
Dry-run uses the same preflight without creating resources or changing Beads.
No plan is inferred or written by fill.

Runtime proof records the exact installed model ID, supported effort, runner
version, auth/billing mode, probe reference and expiry. It is an observation,
not a user approval. Model policy comes only from INTENT section 6.8. An unknown setting
or unavailable model refuses dispatch; there is no fallback. Requested settings
and transcript observations stay separate; unobservable actual settings are
`unknown`. Premium/exceptional approvals need an existing scoped HUMAN record,
not a syntactically valid ID. Native dispatch reservation never grants a Native
engine run or replaces the reviewed package/runner/reader and exclusive lease.

For Codex, proof also verifies `prompt_delivery` (`interactive` or
`startup_argument`). A command center is not a task session. Startup delivery
uses a short path-and-SHA instruction to read retained task/context bytes, not
the mutable packet source; this avoids Windows shell newline/length limits.
An actual folder-trust dialog needs the user's trust decision before selection.
An uncertain launch is never fixed by blindly sending Enter or another packet.

`stop` verifies name/pane/session/cwd and confirmed absence before cleaning a
registered, owned worktree. Dirty/ignored files, unreferenced commits, unknown
ownership or failed cleanup preserve the worktree and reservation for review.
Legacy dispatches require explicit manual inspection. Never remove another
session's resources. A Herdr pane inventory is not a Native process lease.

In Herdr use the herdr skill and discover the installed CLI before controlling
panes. Outside Herdr, built-in subagents remain allowed under the same model,
isolation and ownership rules. Resolve the actual caller from live state;
inherited HERDR variables may be stale. Never set DFM_BD_ROLE in a worker's pane.
Claude workers explicitly read AGENTS.md, get an exact --model and use the
previously approved bypassPermissions mode. Verify the banner/first response.
Only user-facing coordinator messages are Korean; packets, worker replies,
comments and receipts are English (HUMAN-20261106-14).

## Isolation and ownership

- Each I and each V gets its own worktree and branch, placed to fit the existing
  layout (for example, `worktrees/<CODE>-I`). G may use an integration worktree.
- Every task records its owned paths. Check for two implementers on one shared
  file, a verifier editing product code, unexpected changes to accepted files,
  and overwrites of another task's experiment outputs.
- You alone own the high-conflict files: public command registration, schema
  integration, packaging, README, ROADMAP, DELIVERY.md and the graph.
- You serialize shared Git operations: staging, merges and pushes in the shared
  checkout.

### Resources and leases

Native Delft3D slots, shared model inputs, experiment output folders, shared
processes using one executable, the shared merge and shared test fixtures each
need a lock or lease. The existing native rules stay in force. Grant a lease
only after reviewing the exact plan, package, runner and reader, and only to one
branch at a time. A Beads status, a Herdr session state or an idle slot
(`idle235` at present) is not run permission. Producing a candidate and
authorizing a run are separate decisions.

## Result receipt

Every new collection uses the executable schema in
[protocol.py](research/workflows/graph/protocol.py). Complete synthetic examples
for I, V-Plan, V-Run, G and Contract are in
[receipt-examples.json](research/workflows/graph/receipt-examples.json); tests
validate those exact examples. Replace synthetic identities with the context
printed by start/manual-context and hashes of observed evidence before collect.

Use `evidence`, a list of typed artifact references. `evidence_refs` belongs only
to the legacy format. Outcome is an enum; explanation holds narrative. V-Run/G
need explicit PASS or REJECT. Each receipt binds task, immutable dispatch ID,
attempt, packet hash, base and role; target requirements vary by role. G names
the exact upstream receipts. Protocol 2 refuses missing/unknown critical fields.
Collect snapshots original bytes and evidence outside Git and rechecks the
actual Git diff against owned paths. Gate rechecks retained artifact hashes.

Legacy records are display-only for new gates. For manual G or an undispatched
Contract, `manual-context` records explicit reviewed identities without starting
a runtime or changing task/approval status, then collect admits new evidence.
It archives the legacy record; it never fills unknown targets by inference.

Independent pass, Native verification, product merge and final approval remain
separate claims. No automated gate merges or closes a task. A false gate now
exits 3 with JSON on stdout; `--legacy-exit-zero` changes only that exit convention.

## Failure and recovery

| Failure | Route |
| --- | --- |
| Implementation error, failing test | Return to the same implementer with the failure evidence |
| Contract mismatch | Re-review the Contract (planning pool) |
| File conflict | Re-isolate the tasks |
| I/V disagreement | G re-examines criteria and evidence |
| Native uncertainty | Existing run-approval and ownership procedure |
| Session ended | Inspect the receipt before deciding to recover |
| Repeated failure | Premium request or user review |

Recovery after an interruption: (1) Beads task state, (2) live Herdr sessions,
(3) worktree changes, (4) last candidate commit and artifacts, (5) original
evidence, (6) live native processes, then (7) resume from the last recoverable
point. An ended session is not a reason to restart the task from scratch. A live
run is never duplicated.

## Measure

Record per accepted task: total tokens, cost or subscription usage, wall time,
retries, ownership conflicts, duplicate runs, verification failures caught,
approvals without evidence, recovery outcome and avoidable coordinator calls.
Promise no savings before measurement, and compare tasks of similar type and
difficulty.
