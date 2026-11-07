# Agent guide

`dfm` is an AI-friendly CLI for Delft3D Flexible Mesh: create, inspect and edit
model inputs, validate models, run simulations and verify outputs. The long-term
goal is broad suite coverage, delivered one reproducible, verified workflow at a
time. The Python application is in `src/dfm_cli/`. Evidence and research tools
are in `research/`.

## Read next: only what your task touches

| Your task | Read first |
| --- | --- |
| Starting or resuming a session | [RESUME.md](RESUME.md) |
| Coordinating: choosing, assigning, closing nodes; starting agents | [COORDINATOR.md](COORDINATOR.md), a summary of [INTENT.md](INTENT.md) (INTENT wins on conflict) |
| Node status, prerequisites, approvals | [DELIVERY.md](DELIVERY.md) |
| Editing `src/dfm_cli/` or `tests/` | [src/AGENTS.md](src/AGENTS.md) |
| Experiments, native runs, GUI/console, evidence, `research/` code | [research/AGENTS.md](research/AGENTS.md) |
| Dispatch attempts, receipts, recovery and portable graph checks | [graph protocol 2](research/notes/delivery/graph-ops-reliability.md) |
| Product scope and milestones | [ROADMAP.md](ROADMAP.md), [README.md](README.md) |

Search the relevant files instead of loading whole manuals, inventories, history
or source trees. Use `rg --no-ignore` for artifacts that Git ignores.

## Work graph and roles

Every unit of work is a **node** in a DAG:
Contract → I ∥ V-Plan → V-Run → G. What unblocks the next stage is the required
**G approval**. A finished implementation does not.

- **I (implement):** works only in its owned paths, runs the local tests and
  submits changed files, the diff and test results. It freezes the candidate,
  then hands off: verification and merging belong to V and G.
- **V (verify):** runs in a separate session from the author. V-Plan derives
  cases from the Contract alone. V-Run checks the frozen candidate against those
  cases. V writes only in its verification folder.
- **G (integrate):** reconciles the I and V evidence and reviews Contract changes
  and shared-module conflicts. It approves or returns a structured rejection.
  Only G merges.
- **Coordinator:** the single writer of graph state and the only agent that
  starts or messages other agents. When a worker finds new work, it asks the
  coordinator to create a node.

**Graph state:** since 2026-11-06, Beads holds active node state and
dependencies. Read it with
`python -m research.workflows.graph.bdw show <id>` (or `ready --json --exclude-type epic`)
from any checkout or worktree. Only the coordinator writes. Each status lives in
exactly one place.

## Guardrails

- Accepted product code is `src/dfm_cli/` at the approved commit. Anything under
  `research/checkpoints/` or `research/proposals/` is a candidate. Treat
  checkpoints as immutable and build new candidates in separate folders.
- A native Delft3D run needs two things: the coordinator's review of package,
  runner and reader, and an exclusive lease. A graph status, a session state or
  an idle slot is not permission. Confirm that no live run exists before
  starting one.
- A failed process lookup never proves that a process exited. Stop only the
  process tree a run owns, through its retained handles.
- Edits are preview-then-apply. Each edit changes only the requested fields and
  preserves unknown keys, comments, ordering, precision and repeated blocks.
- Report each validation layer on its own: syntax, references, semantics,
  engine initialization, completed simulation, scientific validity. Passing
  Python tests and passing native numerical verification are separate results.
- Support every claim with a source commit and file/line, a manual section and
  PDF page, or an experiment ID with retained artifacts. Label each claim as
  observed behavior, documentation, static analysis or proposal.
- Test on fresh projects or copied official examples. Existing user projects
  and unsaved GUI sessions are off limits.
- Keep downloads, tools, manuals, raw evidence, venvs and experiment outputs out
  of Git, as `.gitignore` already does. Commit small portable findings indexes
  that point to them.

## Git checkpoints

A node is complete only when it has at least one non-empty commit. Use the subject
`<type>(<NODE-ID>): <concrete change>`, for example
`fix(SHORT-CLOSE-I): verify closure before completion`. Give each node its own
commits; never fold several nodes into one bulk commit.

1. Run `git status --short` and `git diff -- <owned-paths>`. Confirm that every staged
   change belongs to this node and that other workers' changes are preserved.
2. Run the node's checks and read the actual results.
3. Run `git add -- <owned-paths>`, review `git diff --cached`, then commit.
4. Report the node ID, the commit hash and the validation scope.
5. After G approval, the coordinator pushes: fetch, check the branch and its
   upstream, run `git push origin <branch>`, then confirm the remote SHA.
   Fast-forward only; never rewrite published history.

In the shared checkout only the coordinator stages, commits and pushes. A worker
submits its node ID, owned paths, patch and validation results. A worker in an
assigned isolated worktree may commit on its own branch. A committed candidate
is still not accepted product code.

## Environment and commands

Windows/PowerShell, Python 3.12+, setuptools packaging, standard-library
argparse. From the root:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[run]'
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/dfm.exe schema inspect
python -m compileall -q src tests research/workflows research/scripts
```

The wheel check, research venv, audit and native replay commands are in
[research/AGENTS.md](research/AGENTS.md#commands). The current version is CLI
0.4.0.dev1 with JSON protocol 2 and manifest 3. The implemented commands are
exactly those that `dfm schema inspect` lists; other names in the capability map
are proposals. Discover each machine's installations and capabilities instead of
assuming this one's.

Update this guide and the relevant directory guide when implementation or
development commands change. Finish every task by reporting the changes,
evidence, checks and remaining uncertainties.
