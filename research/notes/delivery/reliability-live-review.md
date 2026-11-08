# GRAPH-REL-V independent core review

Verdict: **PASS within the assigned scope**. Candidate and Contract:
`ab064b1baae6bdd692cf780baf32d853c15c785b`. Plan SHA256:
`2d72dab958de038f84f7726cb0d84efe7c914aa8a9bcfac67701c87640a3b884`.
Dispatch `053a5f27-b6ef-47e7-80b2-96d14527de78`, attempt 5, task `dfm-b79`.

Observed behavior: the three prescribed portable regressions passed (3 tests,
exit 0). They exercise retry archival and rejection of reintroduced old PASS,
preservation under foreign session/missing cwd/unreachable runtime/working
agent, and refusal of lightweight G for a documentation-labelled implementation
that changes `src/dfm_cli/example.py`. These cases use real temporary Git and
fake Beads/Herdr boundaries; they do not establish live recovery behavior.

Static analysis at the candidate: `dispatch.py:159` revalidates current receipt
bindings and retained artifact bytes; `dispatch.py:684` archives prior receipts
and metrics; `dispatch.py:1050` checks actual Git ownership; `dispatch.py:1112`
checks current upstream identities and product scope; `dispatch.py:1254` and
`:1291` preserve uncertain resources. `protocol.py:68`, `:170` and `:198`
enforce schema/bindings, keep legacy interpretation separate from new gate
eligibility, and check retained artifact hashes. References are under
`research/workflows/graph/`. No concrete defect was found in this focused review.

Observed live transport: read-only Beads lookup in the disposable
`gr-live/r-beads/.beads` matched every printed execution binding and the frozen
task-file hash. Herdr `agent get w2:p2G` matched agent `graph-rel-v`, session
`01a1bb41-116d-7992-8e5d-ce7bb0d89c16` and this checkout's cwd. The first Beads
lookup lacked its local pinned executable; a subsequent read used the existing
hash-verified binary through `DFM_BD_EXE`, preserving the disposable tracker.

Retained evidence: `research/experiments/reliability-review/checks.json`,
`verification.json`, `transport.json`, raw command logs and schema-2
`receipt.json` (ignored). The receipt hashes its checks and verification
artifacts. No full-suite, live retry/cleanup, engine initialization, completed
simulation or scientific validity was verified. This review grants no G
approval or integration.
