# Contract: GRAPH-OPS-P3-DISPATCH

Phase 3 of [INTENT.md](../../../INTENT.md#phase-3--herdr-coordinator-통합): assign one Beads task to a
Herdr agent, link the session to the task, and collect the receipt and usage, with no orchestration server.
Nodes: `-I` (Beads `dfm-fmc.30`), `-V` (`dfm-fmc.31`), `-G` (`dfm-fmc.32`). User decisions:
HUMAN-20261106-11, -13, -14, -15, -16.

## C1. bdw allowlist for `human` and `gate`

Edit `research/workflows/graph/bdw.py` only as needed.

- A worker may run `human list` and `human stats`.
- The coordinator may also run `human respond`, `human dismiss`, and `gate create|list|show|check|resolve`.
- `gate add-waiter`, `gate discover`, bare `human`, bare `gate` and any other subcommand are refused for both roles.
- Every refusal and guarantee bdw already has stays as it is: the frozen
  `research/workflows/verification/verify_bdw.py` and `verify_backup.py` still pass, and so do the existing
  `test_bdw` cases.

## C2. `python -m research.workflows.graph.dispatch`

A new coordinator tool in `research/workflows/graph/dispatch.py`. Every subcommand except `show` refuses
(exit 2, JSON on stderr) unless `DFM_BD_ROLE=coordinator`. All Beads access goes through bdw. Herdr
is called through the executable in `DFM_HERDR_EXE` (default `herdr` on PATH), so tests can use a fake.
Output is one JSON object on stdout.

- **`start <beads-id> --packet <file> --kind claude|codex --model <id> --effort <level> [--name <agent>] [--base <sha>]`**
  - Refuses an epic, a closed node, a node with open blockers, a node whose recorded dispatch still has a
    live agent, a packet outside the main checkout's `research/experiments/`, and a `--kind` other than the two.
  - Creates a detached worktree `<main>-wt/<TASK_CODE>` at `--base` (default: main checkout HEAD). An existing
    clean worktree at the same commit is reused. Anything else at that path is refused.
  - Splits a new pane next to the caller's pane without focus, with cwd set to the worktree, and starts the agent
    with an explicit model and effort. Claude also gets `--permission-mode bypassPermissions` (HUMAN-20261106-16).
    Nothing is started when any earlier step fails, and a failed start leaves no new pane open.
  - Sends one English prompt: read `AGENTS.md`, then read and execute the packet file.
  - Sets the node `in_progress` with no assignee and writes `metadata.dispatch`: agent name, pane id, kind,
    requested model and effort, agent session id from Herdr, worktree, base sha, packet path and SHA-256,
    `started_at`, and `attempt` (1, 2, ...). Earlier attempts stay in `metadata.dispatch_history`.
    Other metadata keys are preserved.
- **`show <beads-id>`**: the recorded dispatch, plus the live Herdr agent state when the pane still exists.
  Read-only, any role.
- **`collect <beads-id> --receipt <file>`**
  - The receipt is JSON with `task_code` equal to the node's code; anything else is refused.
  - Usage comes from the agent's own transcript, found by session id:
    Codex `~/.codex/sessions/**/rollout-*-<session>.jsonl` (the last `token_count` event) and Claude
    `~/.claude/projects/*/<session>.jsonl` (sum of `message.usage` over assistant messages, counting each
    message id once).
    Record input, cached input, cache-write, output and reasoning tokens where present, the actual model
    id(s) seen in the transcript, and wall time from the first to the last transcript timestamp.
    A missing transcript records `usage: null` with the reason; it never fails the collect.
  - Writes `metadata.receipt` (path, SHA-256, verdict/outcome) and `metadata.metrics`, adds one comment, and does not
    change the status. Closing remains the coordinator's judgment.
- **`stop <beads-id>`**: closes the recorded pane only if it still hosts the recorded agent, which is idle or done.
  It removes the worktree only if it is clean. It records `ended_at`. It never kills processes by name.

## C3. Safety

- Tests and verification use throwaway repositories, throwaway Beads workspaces and a fake Herdr only.
  Nothing touches the real `delft3d-fm-cli-beads`, the real Herdr session or the real transcripts directories
  (point them elsewhere through `DFM_CODEX_HOME` / `DFM_CLAUDE_HOME`, default `~/.codex` / `~/.claude`).
- No commits, pushes or edits in the main checkout. `git status` of the main checkout is unchanged by any subcommand.
- All text dispatch writes for agents (prompts, comments) is English.

## Done when

The author tests under `research/workflows/graph/test_dispatch.py`, the extended `test_bdw.py` and the frozen
verifiers pass, `python -m compileall -q research/workflows` is clean, and each C1–C3 clause has a test.

## C4. Clarifications (coordinator, after V-Plan; binding for I and V)

1. **Herdr protocol** is the installed Herdr 0.9.5 CLI. Calls:
   `pane split <pane> --direction right|down --cwd <dir> --no-focus` → `result.pane.pane_id`;
   `agent start <name> --kind <kind> --pane <pane> [--timeout MS] -- <agent args>` → `result.agent`;
   `agent prompt <name> <text>`; `agent get <name>` → `result.agent.agent_status` and
   `result.agent.agent_session.value`; `pane close <pane>`. Errors are JSON on stderr with exit 1. The caller
   pane is `HERDR_PANE_ID`. **The session id can be `null` right after `agent start`.** `start` reads it again
   with `agent get` after the prompt and records `null` with a reason only if it is still missing.
   Codex model and effort go after `--` as `--model <id> -c model_reasoning_effort=<level>`. Claude gets
   `--model <id> --effort <level> --permission-mode bypassPermissions`.
2. **Metadata keys** are the author's choice as long as every value named in C2 is present and documented in
   the module docstring. V checks the values, not the spelling.
3. **Exit codes:** success is exit 0 with exactly one JSON object on stdout. Every refusal or failure is exit 2
   with one JSON object on stderr that has a `refused` or `error` key.
4. **Recovery:** binding only as written in C2. Anything further is diagnostic.
5. **Transcripts:** malformed lines are skipped and counted. Timestamps are ISO 8601 UTC. `wall_seconds` is a
   number. Cached input is reported separately and not added into input.
6. **Paths:** the packet is resolved (symlinks and junctions followed) and must lie inside the main checkout's
   `research/experiments/`. The task code must match `^[A-Za-z0-9][A-Za-z0-9-]*$`, or `start` refuses
   (amended 2026-11-06, GRAPH-OPS-P3-CODEFIX: the graph's own codes such as `B06-READER-V-Run` mix case;
   the original upper-case-only rule refused 10 open nodes). An agent is
   live when `agent get` succeeds and its pane id equals the recorded one.

## G record

G approves `641c887` (merged in `09de210`). Beads `dfm-fmc.30`–`.32`, smoke `dfm-fmc.33`.

- **I:** Claude Sonnet 5.5 high in pane `dispatch-i`, worktree branch `wt/GRAPH-OPS-P3-DISPATCH-I`. Rounds: `be88d93`, then `641c887`.
  The worker's open questions were answered by the coordinator: frozen-verifier pins, transcript shapes, `pane_id` location.
- **V:** Codex gpt-6.1-sol high in pane `dispatch-v`, run in parallel with I for V-Plan. V-Plan listed six
  ambiguities, which C4 answered.
  - V-Run on `be88d93`: REJECT 281/282. DISPATCH-V-001: Codex `cache_write_input_tokens` was dropped. The cause
    was that the coordinator gave the real transcript keys to V only, not to I.
  - V-Run rev2 on `641c887` with the verifier unchanged: PASS 282/282. The author suite exceeded the
    verifier's own 180 s limit and passed 25/25 in 250 s.
- **G checks:**
  - The merged files are byte-identical to `641c887`. The author tests pass on main.
  - Live run against the real Herdr session: `start` (14 s), `show` (worker role), `collect` (real Claude
    transcript), `stop` (pane closed, worktree removed).
  - `collect` and `stop` also worked on the two hand-recorded sessions (I and V).
- **Measured usage** (from `collect`; Codex `input` includes cached input, Claude `input` excludes it):

| Node | Model | Wall (transcript span) | Input (uncached) | Cached read | Cache write | Output |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| DISPATCH-I (2 rounds) | claude-sonnet-5-5 | 6,934 s | 159 | 11,115,542 | 174,370 | 82,600 |
| DISPATCH-V (Plan + 2 runs) | gpt-6.1-sol | 7,109 s | 120,276 | 11,247,872 | 0 | 99,445 (46,109 reasoning) |
| P3-SMOKE (trivial) | claude-sonnet-5-5 | 18 s | 8 | 234,266 | 31,800 | 581 |

  The smoke row shows the fixed cost of one Claude worker turn cycle: about 32 K tokens of context
  written to cache, then read back on each turn. Wall spans include idle time between rounds.
  Codex weekly usage stood at 91 % after V. No savings claim yet: Phase 5 compares similar tasks.
- **Follow-ups:**
  - `test_dispatch` takes about 250 s.
  - `bdw create --silent` output once failed to yield the id inside a shell pipeline.
  - Settled-state detection needs the receipt file plus a screen check, because idle agents can still have
    background work.
