# B14 · Astronomic constituent assignment (`boundary constituents-inspect`, `boundary constituents-set`)

The GUI task is ROADMAP row 27 (B14). This note records what the public commands change and what the installed engine
did with the result.

## Scope

- **What it edits:** amplitude and phase of named astronomic constituents on existing water-level BC supports of one
  boundary, chosen by exact support ID or `--all-active`, from a version-1 assignment JSON (units m and degrees).
  `--create-missing` appends missing rows to existing active signals. Preview writes nothing; apply needs the preview
  hash and uses the shared `pump_edit_write`/`pump_edit_security` publisher.
- **Catalogue:** ten exact uppercase names (A0, Q1, P1, O1, K1, N2, M2, S2, K2, M4). A0 is signed with phase 0;
  other amplitudes are non-negative; phases lie in [-360, 360] degrees. Lowercase or other source symbols, harmonic
  frequencies, correction pairs and unit conversion are refused, not repaired. The full contract is in
  `dfm schema inspect` under `boundary_constituents`.
- **Engine evidence:** A0 and M2 only. The other eight names are file edits without engine evidence.
- **Source of the behaviour:** private candidate revision02 (`research/experiments/B14-I-20261105-rev02/HANDOFF.md`)
  and the [Contract](../delivery/b14-rebuild.md).

## Verification (2026-11-09)

| Check | Result |
| --- | --- |
| Author tests | 25 frozen tests, unchanged; full discover 1,858 OK |
| Installed checks (V) | 32 tests / 74 calls on a clean wheel install; 212 files equal to the candidate |
| Schema | 105 → 107 commands; only the two commands and `boundary_constituents` added |
| Replay | the four public calls reproduce the retained public inputs, which equal the manual inputs, for both epochs |
| Engine | six direct `short` runs, all PASS (below) |

### Installed engine

[Contract](../delivery/b14-rebuild.md) R4 and R6. Six serial `dfm run start --profile short --route direct` runs, each
120 s with a 60 s limit, on a small 2D model with a west water-level boundary (A0 0.125 m; M2 0.060 m in the edited
cases) and an east zero boundary, at two epochs (2001-01-01 and 2026-11-05).

| Case | Result |
| --- | --- |
| epoch2001 and epoch2026 × a0-control / manual-a0-m2 / public-a0-m2 | rc 0, `completed`, original Job closure recorded, 121 frames over [0, 120] s, restarts at exactly 0 and 120 s, no fatal or error diagnostics |
| public vs manual, each epoch | all 169 variables (history 66, map 35, both restarts 34) equal in raw and decoded arrays, masks, dimensions, dtypes and attributes, rtol = atol = 0; only per-file creation provenance (history, dates, uuid) differs |
| A0 controls across epochs | recorded observations (Contract R6): arrays equal; CF time units and creation metadata differ |

- **Approvals:** the user approved the runs as `HUMAN-20261109-01` under lease `native-237`. The research BMI runner
  branch was deferred by the user and is not part of this result.
- **Evidence:** [native review](../../experiments/B14-PUBLIC-V-Run-20261109-01/REVIEW-native.md),
  [native result](../../experiments/B14-PUBLIC-V-Run-20261109-01/verification-native.json),
  [portable review](../../experiments/B14-PUBLIC-V-Run-20261109-01/REVIEW.md),
  [G acceptance](../../experiments/B14-G-20261109-01/acceptance.json).

The prescribed boundary signal is a receiving state. Equal outputs show that the CLI edit is equivalent to the manual
edit for the engine. They do not prove a constituent phase or a tidal prediction.

## Not established

- engine evidence for the other eight catalogue names;
- GUI table-edit parity;
- harmonic frequencies, correction pairs, spatial fallback between supports;
- the BMI diagnostics (deferred research branch);
- the installed engine's source commit.
