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
