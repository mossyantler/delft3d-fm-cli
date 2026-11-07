# S07 · Wind-speed-dependent drag coefficient (`wind drag-inspect`, `wind drag-set`)

The GUI task is in [gui-workflows S07](../collection/gui-workflows.md#wind-drag). This note records what the public commands
change and what the installed engine did with the result.

## Scope

- **What it edits:** an existing `[wind] ICdtyp=2` (Smith & Banke) with exactly two `Cdbreakpoints` and two
  `Windspeedbreakpoints` literals. Only the selected numeric tokens change, in place or into a new folder, using
  preview, then apply bound to the preview hash.
- **Bounds:** coefficients 0–1 (dimensionless), speeds 0–1e6 m/s, and the two speeds at least 0.1 apart. Nothing is
  clamped.
- **Refused:** other drag laws, legacy EXT, initial fields, spatial coefficients, stress inputs and gridded meteo
  providers. The full contract is in `dfm schema inspect` under `wind_drag`.
- **Example:** [examples/wind_drag](../../../examples/wind_drag/README.md). Its commands run as written in Windows
  PowerShell 5.1.

## #233 · Installed engine (2026-11-08)

[Contract](../delivery/s07-rebuild.md) R4. Seven serial `short` direct runs, each 120 s, on a 48-cell model with a
uniform 10 m/s wind from 225°, anchors at 5 and 15 m/s, ρ_air 1.2, and no relative wind. The two `public` cases were
edited with the merged CLI. Each run had 121 frames.

| Case | Cd | τx, τy (Pa) observed | Predicted |
| --- | --- | --- | --- |
| wind_base | 0.002 | 0.169706, 0.169706 | 0.169706 each |
| wind_manual / wind_public | 0.0025 | 0.212132, 0.212132 | 0.212132 each |
| calm_base / calm_manual / calm_public | 0.001 / 0.002 / 0.002 | 0, 0 | 0 |
| direction_control (135°) | 0.002 | −0.169706, 0.169706 | −0.169706, 0.169706 |

- **Tolerances:** all values lie within 5e-8 Pa absolute or 2e-6 relative (1e-12 for zero), predeclared before any
  launch.
- **Closure:** every run reached `completed`, with the original Job close recorded in the manifest
  (`ownership.job_close`).
- **Approvals:** the user approved the runs as `HUMAN-20261108-01`/`-02`, under leases `native-233`/`-234`.
- **Evidence:** [native review](../../experiments/S07-V-Run-20261108-01/REVIEW-native2.md),
  [result](../../experiments/S07-V-Run-20261108-01/verification-native2.json), and
  [portable review](../../experiments/S07-V-Run-20261108-01/REVIEW.md).

The first attempt stopped at `wind_base`. The installed engine (1.2.184) rejects `operand = override` in the EXT
`[Meteo]` block with `Unsupported operand 'o' for quantity 'windxy'`, while GUI exports write `operand=O`. The
fixtures were corrected in that one line only (Contract R6.4). `wind drag-set` does not read or write `operand`.

## Not established

- GUI table-edit parity;
- other drag laws or more breakpoints;
- winds between or outside the anchors beyond these cases;
- spatial wind;
- scientific calibration;
- the installed engine's source commit.
