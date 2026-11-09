# G15 · Structure file transfer (`structure inspect`, `structure export`, `structure import`)

The GUI task is ROADMAP row 20 (G15). This note records what the public commands do and how they were verified. No
engine or GUI run belongs to this result.

## Scope

- **Commands:** `structure inspect` is read-only. `structure export` writes a geometry or hydraulic bundle into a new
  folder. `structure import` replaces one existing, explicitly named `StructureFile` target. Export and import use
  preview, then apply bound to the preview hash.
- **Writes:** W2D (planar weir, scalar or TIM crest) and P2D (scalar pump). The other 14 rows of the approved scope
  (gates, staged pumps, pillars, Shapefile, 1D, 3D, multi-file writes and others) are reported as deferred or
  unsupported, never written. The full contract is in `dfm schema inspect` under `structure_transfer`.
- **Closure:** the graph includes the MDU, every supported declared input and output, and unselected data. An
  unknown or ambiguous edge blocks a complete or writable result. This includes an MDU key outside the engine field
  registry whose value names a `Structure.id` or an existing file or directory (Contract R6). In that case inspect
  reports the graph as not closed, previews refuse with exit 3, and an apply that supplies a hash refuses with
  exit 4 (`stale_preview`).
- **Source of the behaviour:** the approved proposal rev02
  (`research/experiments/G15-PROPOSAL-I-20261105-rev02/`, G approval `G15-PROPOSAL-G-final-01`) and the
  [Contract](../delivery/g15-finish.md).

## Verification (2026-11-08/09)

| Check | Result |
| --- | --- |
| Author tests (I) | 23 ported tests plus 4 R6 tests; full discover 1,833 OK, 47 skips |
| Independent installed tests (V, Lovelace's frozen material) | public 30/30, publication faults 11/11 on the clean wheel install |
| Wheel | 209 product files equal to the candidate; payload equal between G's and V's wheels |
| Schema | 102 → 105 commands; only `structure inspect/export/import` and `structure_transfer` added, every existing parameter unchanged |
| ACL cases | protection toggled and restored to the exact SDDL inside V's folder (user approval `HUMAN-20261108-05`) |
| Regression | candidate 1,833 / base 1,806, no new failures |

- **Round 1** stopped on V fixtures: some `.ini` prologue lines began with `*`, which the accepted INI grammar
  (`model.parse`) rejects. Contract R5 changed those first bytes to `#` in a frozen copy and clarified that the
  repository's Python-payload Job unit tests are allowed.
- **Round 2** found a real defect (`G15-R2-D01`): uncatalogued MDU keys such as `[future] ControlTarget = 7` or
  `Alias = nested.tbl` escaped closure, and a probe changed the hidden file after preview without stopping apply.
  Contract R6 defined the fix; `G15-CLOSURE-I` implemented it in `structure_transfer_graph.py`.
- **Round 3** passed on candidate `bdd90b0`. V listed one ambiguity, R6-APPLY-EXIT: an apply with a supplied hash on
  a graph-rejected model exits 4, not 3. G accepts this. No valid preview can exist for such a model, and the
  existing mapping `structure_transfer.py:61-63` reports a hash that matches no current preview as stale.
- **Evidence:** [round 3 review](../../experiments/G15-TRANSFER-V-Run-20261108-01/REVIEW-r3.md),
  [result](../../experiments/G15-TRANSFER-V-Run-20261108-01/verification-r3.json),
  [round 2 review](../../experiments/G15-TRANSFER-V-Run-20261108-01/REVIEW-r2.md),
  [G acceptance](../../experiments/G15-G-20261109-01/acceptance.json).

## #238 · Installed engine (2026-11-09)

[Contract](../delivery/g15-engine.md) with R5 (engine only; GUI parity deferred by user decision). Six serial direct
runs, each 120 s with a 120 s limit, on copies of the public examples: a weir with a TIM crest under
`--profile weir-series` and a scalar pump under `--profile pump-scalar`. For each kind the target ran untouched
(control), after `structure export` from a source model and `structure import` into it (public), and after the same
change by hand (manual). Public and manual inputs were byte-equal before launch.

| Kind | public vs manual | control vs transferred |
| --- | --- | --- |
| weir, TIM crest | history, map and both restarts equal at rtol = atol = 0 | `weirgen_crest_level` −0.5 m vs +0.5 m at all 55 times 66–120 s |
| pump, scalar capacity | equal at rtol = atol = 0 | `pump_structure_discharge` 4 vs 0 at all 120 times 1–120 s |

- 362 variable comparisons over 8 file pairs; only per-file creation provenance (16 attributes per kind) differs.
- Every run completed with the original Job closure, 121 history and map frames, and restarts at 0 and 120 s.
- **Approvals:** the user approved the runs as `HUMAN-20261109-02` under lease `native-238`.
- **Not run:** a scalar-crest weir. No public run profile admits it (`weir-series` needs a TIM, `short` refuses
  structures), so its engine result is not established (`G15-SCALAR-WEIR-PROFILE`).
- **Evidence:** [native review](../../experiments/G15-ENGINE-V-Run-20261109-01/REVIEW.md),
  [result](../../experiments/G15-ENGINE-V-Run-20261109-01/verification.json),
  [plan](../../experiments/G15-ENGINE-V-Plan-20261109-01/PLAN.md).

The control comparison only shows that the transfer reaches the engine; no discharge magnitude was predicted.

## Not established

- engine behaviour of a transferred scalar-crest weir (no admitted public profile);
- GUI export/import parity (`G15-GUI-PARITY`, deferred by user decision);
- scientific validity beyond the equality above;
- the 14 deferred or unsupported scope rows;
- coordinate conversion and POSIX behaviour.
