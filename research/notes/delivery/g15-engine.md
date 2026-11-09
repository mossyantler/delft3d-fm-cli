# Contract: G15 structure transfer on the installed engine (engine only)

Beads: `G15-ENGINE-Contract` (`dfm-h9c.6`, this Contract), `G15-ENGINE-V-Plan`, `G15-ENGINE-V-Run`, `G15-ENGINE-G`
(new); `G15-GUI-PARITY` (new, deferred). Status: proposal by the coordinator, 2026-11-09. User decision (2026-11-09):
engine only; GUI export/import parity is deferred and stays "not established". No product change belongs to this
Contract: it verifies the merged product (`structure inspect/export/import`, `G15-G` `d8665fc`, current main
`910441f`) on the installed engine.

## Question

When `structure export` and `structure import` move a supported structure (W2D planar weir with scalar crest, W2D
planar weir with TIM crest, P2D scalar pump) into an existing target model, does the engine compute exactly what it
computes for the same target edited by hand to the same intended bytes? And does the transfer change the result
compared with the untouched target (so the comparison is not vacuous)?

## R1. Cases

- Base models: copies of repository examples that already ran on this engine through a public run profile:
  `examples/weir_series` (`dfm run start --profile weir-series`, evidence #217) for both weir cases and
  `examples/pump` (`dfm run start --profile pump-scalar`, evidence #187) for the pump case. If a profile's admission
  refuses a case (for example `weir-series` with a scalar crest), V-Plan reports it and proposes the nearest admitted
  profile or model with its source lines; it does not widen a profile. Another approved runnable model needs a stated
  reason.
- For each of the three structure kinds: a **source** model whose structure differs from the target's in the
  transferred properties (geometry, crest or capacity, as the row allows), a **target-control** run of the untouched
  target, a **public** run where the target is changed only by `structure export` (from the source) and `structure
  import` (preview, then apply with its hash), and a **manual** run where the same target is edited by hand to the
  bytes the public import is meant to produce. At most 9 runs in total; V-Plan fixes the exact count.
- Inputs are built and frozen by V-Plan before any run; the public case's files must equal the manual case's files
  byte for byte, which is checked before launch (input equivalence), as in G18 and B14.

## R2. Acceptance (V-Plan predeclares before any run)

- Every run completes naturally under the chosen public profile with the manifest's original Job closure, all
  expected output frames and restart files of that profile, and no fatal or error diagnostics.
- Public and manual outputs are exactly equal (rtol = atol = 0) in every variable, mask, dimension, dtype and
  variable attribute of history, map and restart files; only per-file creation provenance may differ, each
  difference listed.
- The control differs from the public/manual pair in at least one predeclared structure observable (for example the
  structure discharge or crest level time series in history), so the transfer demonstrably reaches the engine.
- No numerical prediction of discharge magnitudes is required; if V-Plan predeclares one, it is reported as an
  observation unless the plan states its tolerance before any run.

## R3. Process

- **V-Plan (Codex):** cases, frozen inputs, manual edits, predeclared observables, runner (the public `dfm run start`
  profile, environment as in G18 R6.4), reader with pins, timeout basis, and the admission file. No launch.
- **Native runs:** only after explicit user approval recorded as a HUMAN node, coordinator review of package,
  runner and reader, and an exclusive lease (next free slot `native-238`). One attempt per case, serial, no retries.
- **V-Run (Codex, a fresh session):** checks the plan's input equivalence on the installed merged product, runs the
  approved cases and judges them by the frozen plan.
- **G:** records the result in `research/notes/verification/structure-transfer.md` and DELIVERY; no merge.

## R5. Clarification (coordinator, after V-Plan; binding for V-Run)

1. **Scalar-crest weir (V-Plan A1).** No public run profile admits a scalar-crest weir model: `weir-series` requires an
   authored TIM (`weir_run_inputs.py:147-150`, refusal `weir_series_constant_conversion`) and `short` refuses
   `geometry/structurefile`. R1 forbids widening a profile, and the proposed substitute (the TIM row again) would not
   establish the scalar claim. The engine gate is therefore the **six admitted runs**: `weir_tim` and `pump_scalar`,
   each control, public and manual. The three `weir_scalar` folders stay frozen, unexecuted, and the scalar-weir
   engine result stays "not established" (file transfer is verified by `G15-G`). A public profile that admits scalar
   weirs is a separate product question (`G15-SCALAR-WEIR-PROFILE`).

## R4. Out of scope

- GUI export/import parity (`G15-GUI-PARITY`, deferred by user decision); the 14 deferred or unsupported scope rows;
  scientific calibration; other structure kinds; DIMR route unless V-Plan shows the profile supports it.

## Done when

- **V-Plan:** R1-R3 deliverables frozen, ambiguities listed.
- **V-Run:** PASS or REJECT by the frozen plan, after approval.
- **G:** verification note and DELIVERY updated.
