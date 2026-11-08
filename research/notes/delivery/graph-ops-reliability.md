# Graph dispatch protocol 2 (GRAPH-OPS-RELIABILITY-I)

## Scope and audit basis

Baseline: `b8c93ff35a7ac4f6e0845cfd3ae7faac4b693da7`, main, inspected
2026-11-08. `git log 39128f3..HEAD -- research/workflows/graph` and the scoped
diff showed no committed graph changes since the audit. Main had unrelated
uncommitted dashboard/test changes and CLAUDE.md; implementation uses the
isolated `fix/graph-ops-reliability` worktree and preserves those files.
Only graph tools, their tests, and operating documents change. No product code,
Native run, product queue dispatch, existing approval edit, migration, merge or
push is part of this change.

This contract supersedes P3 C2/C4/C5 and P4 P2–P6/P8 **only for new execution,
collection and gate decisions**. Historical G records describe their historical
criteria, not protocol-2 verification. In particular P4 P8.4 explicitly allowed
substring failure detection, P8.7 allowed stored null verdicts, and P6 specified
gate exit 0 for false. Those are deliberate contract changes here.

| Audit issue | Baseline finding (static analysis, b8c93ff dispatch.py) | Disposition |
| --- | --- | --- |
| Retry uses old PASS/metrics | `cmd_start`, lines 615–637, replaces dispatch only | Fixed: archive complete attempt, clear current results before intent |
| Minimal V-Run receipt passes | `check_receipt`, lines 873–893, optional fields | Fixed: role schema and immutable target binding |
| Closed alone opens gate | `predecessor_checks`, lines 239–264 | Design strengthened; legacy closure is not new evidence |
| Foreign session loses worktree | `cmd_stop`, lines 943–972 | Fixed: identity/cwd/absence checks precede deletion/release |
| Nested exception hides original | `cmd_start`, lines 638–655 | Fixed: separate error variables and retained cleanup state |
| Lowercase pass/narrative failure | `receipt_failure`, lines 222–236 | Contract changed: exact outcome enum; explicit legacy interpretation |
| Dirty dry-run differs | `prepare_start`, lines 533–576, vs `prepare_worktree`, lines 390–404 | Fixed: shared read-only worktree preflight |
| Fresh open blocker ignored | `check_start_resources`, lines 527–530 | Fixed: all fresh failures block |
| Reconcile drops same-name/different-pane | `cmd_reconcile`, lines 1089–1093 | Fixed: compare complete name/pane/session tuple |
| No-op reconcile writes | `cmd_reconcile`, lines 1108–1113 | Already handled for old facts; retained and extended to new facts |
| Start-before-record interruption | `cmd_start`, lines 585–637 | Fixed: intent, worktree/pane/agent/prompt stages |
| Premium reference is regex only | `check_start_policy`, lines 501–509 | Fixed: actual record, scope, model/effort and limits |
| Owned-path declaration only | `check_start_policy`, lines 501–503; `cmd_collect`, lines 896–926 | Fixed: explicit read-only mode; computed Git changes at collect/gate |
| Clean unreferenced commit protection | `remove_worktree`, lines 407–419 | Already handled; retained, also protects ignored evidence |
| Missing usage represented as zero | `usage_for`, lines 855–870 | Already null with reason; preserved in interval/cost records |
| Native reservation vs permission | P4 P7 and COORDINATOR | Already separate; no engine lease granted by dispatch |
| Ready tasks without plans | Operational read-only ready result: 4 tasks, all no plan, 0 in-progress | Changed since audit's 5; diagnose, do not invent operational plans |

Observed regressions are executable in `research/workflows/graph/test_dispatch.py`.
The artifact/index at the implementation commit records commands and actual
results. Tests establish graph logic and Git behavior; they do not certify
Herdr/Beads integration, model availability, Native termination or scientific
validity.

## Ownership, state and execution attempts

Beads remains the only lifecycle store. The coordinator is its only writer.
`metadata.dispatch` is the current attempt; `dispatch_history` holds complete
earlier records with their receipts and metrics. `collection_history` retains
superseded receipts/samples within an attempt. No new status database exists.
Every attempt has a UUID `dispatch_id`, positive attempt, task ID/code, frozen
packet SHA-256 and bytes, resolved base/Contract commit, role and task kind.
V-Run/G additionally freeze candidate; V-Run/code G freeze the verification
plan digest. I produces its candidate; V-Plan produces its frozen plan. V's
candidate may equal its base. V-Plan must not receive an I candidate argument.

Start admission requires explicit role, task kind, Contract and write scope
(`--owns` or `--read-only`), plus model runtime proof and task-class pool. Unknown
fields/types in plans refuse. Paths use `/`, reject absolute/drive-relative,
dot, empty or parent parts, and follow the host's case convention. Overlap is
by complete path segments. Collection computes the base-to-candidate Git diff,
including both rename sides, and checks staged/unstaged/untracked worktree
changes. Gate recomputes retained I changes even after worktree removal.
Ignored evidence is preserved on stop; write isolation is an operating policy,
not a security boundary against arbitrary shell access.

Intent is written before resource creation. Each requested/confirmed resource
stage is persisted. External calls can succeed without returning a response;
uncertainty preserves the reservation. A failed start retains its primary error,
separate cleanup errors, resource identities and unknown/measured usage. Cleanup
never removes a reused or uncertain worktree. A prompt is sent once with frozen
packet bytes inline; the source path is diagnostic only. Transcript mismatch
requires review, and an uncertain submission never sends Enter or the prompt
again. Reconcile never restarts work.

Reservations include closed tasks until `ended_at`, not just in-progress tasks.
Stop needs the exact name/pane/session and observed cwd. Query errors are
`unreachable`, incomplete identity is `unknown`, a changed tuple is
`identity_mismatch`, and only authoritative absence of both agent and pane is
`confirmed_absent`. Only a settled owned agent may have its pane closed; the
absence is checked again afterwards. Registered worktree ownership and clean
Git state are checked before removal. Dirty/ignored files, unsaved commits,
deregistered leftovers or removal failures retain reservation with `needs_review`.
Legacy ownership is never inferred. A Herdr pane observation does not release
an independently managed Native engine lease or establish Native process exit.

## Receipt contract

`protocol.validate` is the single executable schema, version 2. Complete,
schema-tested examples are [receipt-examples.json](../../workflows/graph/receipt-examples.json).
Their synthetic commits/IDs are intentionally not collectable against a real
task: substitute the printed execution context and observed files/hashes.

Every receipt requires all dispatch bindings, `schema_version`, `contract_sha`,
`outcome`, `explanation`, and nonempty typed `evidence`. Outcomes are exactly
`completed`, `failed`, `blocked`, `cancelled`. Verdicts are exactly `PASS` or
`REJECT`; success needs completed and, where required, PASS. Unknown top-level
fields refuse; use an `extensions` object for noncritical annotations.

| Role | Additional requirements |
| --- | --- |
| I | Candidate commit, exact changed_paths, nonempty checks with command/result, implementation and checks artifacts. Completed code/docs I needs a nonempty commit |
| V-Plan | Plan SHA-256 identifying its frozen verification_plan artifact; Contract only, no I analysis |
| V-Run | Exact candidate, Contract and plan; explicit verdict; checks and structured verification/checks artifacts |
| G | Candidate, Contract, approval_scope, review artifact and exact validation_refs (task ID, dispatch ID, original receipt hash). Code G also requires plan and current I/V-Plan/V-Run, with identified distinct I/V-Run sessions. Tool/documentation review may use the lighter I + coordinator/independent review evidence route. Verified I changes under src/, tests/ or pyproject.toml require code G regardless of task labels |
| Contract | Explicit Contract commit and contract artifact; no fake candidate/test/native fields |

`checks.result` is pass/fail/skip. A successful I/V-Run needs at least one pass
and no failed required check. Skips remain visible; native and scientific
approval cannot be inferred from Python results. G still reviews applicability
and scientific evidence. No receipt, gate or `closed` value merges product code.

Each evidence entry needs `artifact_id`, bundle-relative `path`, `sha256`,
`kind`, `source`. Paths must resolve under the receipt bundle and be files.
Checks/verification must parse as structured JSON. Sources identify this dispatch
(`dispatch:<UUID>`) or `git:<candidate-or-Contract>:<repo-relative-path>`; Git
sources are compared with the actual blob bytes. These are traceable provenance
claims, not cryptographic author authentication.

Collect copies original receipt bytes and artifact bytes into
`<main>-beads/dispatch-artifacts/<sha256>/<name>` (override with
`DFM_DISPATCH_ARTIFACT_ROOT`). Metadata stores portable IDs, relative paths,
hashes, kind/source and the normalized document. Identical collection is
idempotent; a changed receipt preserves the prior sample. Gate checks copies
and binding, compares candidate/Contract/plan among predecessors and target,
checks Git identity/ownership and G's exact upstream receipts. Source changes
after collection do not change the decision; missing/corrupt retained copies
block it. Back up the artifact tree **separately** from Beads/Dolt/JSONL. Git
holds small examples and this index, not transcripts or large experiment data.

Gate false returns JSON `ok:false` on stdout with exit **3**. Success is exit 0;
refusal/external failure is exit 2 with one JSON object on stderr containing
`refused`/`error` (plus reason/cleanup where present). The explicit deprecated
`--legacy-exit-zero` preserves P4's exit convention only, never weaker checks.

## Legacy compatibility and rollout

No operational migration is required or automatically applied. Existing
approvals, failures, unknown metadata and receipt hashes stay unchanged. The
read-only `compat --snapshot <copied-export.jsonl>` produces a deterministic
dry-run inventory with original record/line hash, source hash, interpretation,
unknown identities and review needs. Repeated runs do not write the source.
Lowercase pass/reject are recognized for display; only explicitly enumerated
old outcomes are mapped. The B06 narrative containing expected_base_failure is
displayed as planning complete with its original explanation. Arbitrary prose
containing fail/reject is not guessed to be failure or success for admission.
`evidence_refs` is a legacy field; it is not silently promoted to typed evidence.

Legacy display is never new gate eligibility. New work needing an old approval
requires a deliberate coordinator review of its real scope and evidence, not
bulk conversion. `manual-context <id> --context <file>` records explicit task,
role/kind, base, Contract, candidate/plan where applicable, actor, read_only and
owned_paths. It preserves prior records, prints a fresh UUID/context for a new
receipt, starts no process and changes no task/approval status. A manual G can
then collect reviewed evidence and exact validation references. Unknown targets
must be supplied from evidence, never guessed. An active/unreleased old dispatch
cannot be replaced this way. Handle its resources manually through retained
owned handles; this version refuses automatic legacy cleanup.

Before rollout, preserve the existing Dolt backup, export hash and original
artifact directories. Review `fill --dry-run` and legacy inventory. Populate
plans/proofs only for authorized tasks. Keep the old branch available for CLI
rollback; existing records are not rewritten. Reverting code does not justify
reusing a protocol-2 receipt as legacy approval. Any future importer must retain
original bytes, produce a dry-run, and prove idempotency on a copied export
before separately authorized application. None is needed for this additive
format.

## Model policy and measured cost

INTENT §6.8 is the sole model policy. Its YAML is represented in JSON-compatible
syntax so stdlib json can read it (the former missing space after
independent_verification also made it invalid YAML). Values are preserved.
Runtime proof is local coordinator evidence: model_key, exact model_id/kind,
availability_verified, supported_efforts, runner/version, auth/billing mode,
probe_ref, expires_at and task_classes_evaluated. The transitional general pool
exception must be explicit if evaluation is unavailable. Never make up a proof.
Premium/exceptional HUMAN records must be uniquely found and approved/closed,
and model_approval must cover task IDs, exact model, effort, task classes,
question/input scope, prior limits, verification method, max_calls and
usage_budget.max_total_tokens. Fable additionally needs a separate exceptional
approval. Historical prose decisions are not automatically interpreted as new
grants. No approval node is created or closed by dispatch. Call and previously
measured usage limits are admission controls; this wrapper is not an in-flight
billing/token hard cap. Unknown prior approved usage requires coordinator review.

Codex proof also requires `prompt_delivery`: `interactive` for a verified chat
input at launch, or `startup_argument` for CLIs that open a command center without
an initial prompt. The latter passes the already archived frozen prompt as the
documented [PROMPT] argument and never sends a second prompt. Its pre-task usage
baseline is unknown because execution can precede observation. Failure records
retain `failure_stage` before changing stage to needs_review. A command-center
launch is not proof of a task session or prompt acceptance.

Requested model/effort are separate from transcript model observations; actual
effort stays unknown if unavailable. An observed model mismatch blocks the
receipt's new gate. Unavailable models never auto-substitute. Retries require a
classified cause; at most two repairs per cause are admitted. Environment/CLI/
path/permission/approval errors cannot justify switching models. Model changes
need a retained failure/rationale and cannot chain premium families.

Metrics bind each dispatch/attempt/session, requested settings, observed models,
role/outcome, session cumulative usage, measured baseline-to-collection interval,
raw counter endpoints, attempt wall time, transcript ID/hash, and unknown
costs/reasons. Missing baselines are unknown, never zero. Failed
starts and rework remain attributable. Codex input includes cache reads; Claude
input excludes them. Do not add cached input twice or add reasoning into output.
An interval needs matching monotonic counters and a measured baseline; session
cumulative data is diagnostic, never summed across V-Plan/V-Run. Overlapping
counter intervals or shared sessions without comparable endpoints are excluded
from task attribution and explicitly reported as unknown. Work switches
need a new context; short repairs may reuse one only with measured boundaries.

`dispatch metrics <ids...> --accepted-task <G-id> --cohort <before-or-after>
--benchmark-case <case>` exports only the selected nodes and their attempts.
The accepted_task grouping is supplied by the coordinator, not a new approval.
`accounting <export.json>` accepts that output or a metrics array, deduplicates
dispatch samples, includes failed attempts and verification work, groups by
accepted_task/cohort/benchmark_case, and reports role and provider breakdowns
with unknown usage/cost. Billed amounts require explicit dispatch_interval scope
and currency; missing amounts or mixed currencies never become a numeric total.
Compare the same representative cases (short
review, receipt repair, interrupted start) before/after. Portable regressions
measure reliability without model calls; actual token/cost comparisons require
authorized measured tasks. No baseline or savings percentage is invented.

## Verification and remaining integration scope

Run `python -m unittest research.workflows.graph.test_dispatch -v` and
`python -m compileall -q research/workflows/graph`. Portable tests use stdlib,
temporary real Git repositories/worktrees and fake external protocol adapters.
Validation, gates, transitions, diff computation, artifacts and accounting are
not mocked. Transcript parsing regressions are retained. The old binary-bound
P3/P4 tests at b8c93ff exercise explicitly superseded contracts and are replaced
by these portable cases; they are not silently counted as passing here.
Related bdw/dashboard suites retain their own external-binary integration skips.

Operational changes in this task are limited to the new improvement node.
Product Ready work was only read. Real Herdr/Beads integration, runtime proofs,
process ownership after a real crash, Native engine termination and any
scientific verification remain untested by this suite. Use a separately
authorized disposable integration graph for rollout; no product queue replay
or repeated live rounds are required for the tool's lightweight review.

### Frozen-candidate observations (2026-11-08)

Candidate `933a3ad4909c416d4760e2aeee7af8c43f4c3120`, branch
`fix/graph-ops-reliability`, Beads `dfm-fmc.52`. The experiment
`GRAPH-OPS-RELIABILITY-I-20261108-01` retains original outputs and hashes;
[reliability-evidence.json](../../workflows/graph/reliability-evidence.json) is
the portable index with the sixteen requested regression groups mapped to cases.

- Observed: 59 relevant tests, 57 passed, 2 skipped; all 39 portable dispatch
  tests passed with no skips. The two unchanged bdw/dashboard integration cases
  lacked their pinned bd/bv binaries in the isolated worktree. No production DB
  or installed runtime was substituted for a test fixture.
- Observed: compileall for research/workflows and research/scripts, and
  git diff --check, exit 0. Test elapsed time was about 38 seconds; that is a
  regression-run observation, not a model-cost savings comparison.
- Observed: a copied snapshot's 20 legacy receipts were inventoried twice with
  identical results and byte-identical input. Operational records were not
  migrated. Existing approval states and artifact sources were not changed.
- Static analysis/coordinator light check: policy values match the baseline
  after correcting the original YAML typo; no duplicated top-level definitions,
  product-code changes or out-of-scope shared edits. The review is not represented
  as an independent model verdict or a live integration approval.

Raw artifacts remain ignored and local; the index does not imply they are
available on another machine. Copy the artifact tree separately and verify its
hashes before relying on it there. This candidate is not merged into accepted
product code and has not been pushed. Rollout needs reviewed real plans/runtime
observations and a separately authorized disposable integration check, not an
operational migration or an automatic replay of the product queue.
