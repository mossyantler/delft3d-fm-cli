# Contract: S07 wind drag editor on the current product

Beads: `S07-I` (`dfm-lo0.3`), `S07-V-Plan` (new), `S07-V-Run` (`dfm-lo0.4`, lease), `S07-G` (`dfm-lo0.5`).
Status: proposal by the coordinator, 2026-11-07. Product verification rules apply in full.

## Background

- S07 adds `wind drag-inspect` and `wind drag-set`, which edit an existing `[wind] ICdtyp=2` with exactly two
  `Cdbreakpoints` and two `Windspeedbreakpoints` literals (Smith-Banke, two breakpoints). The installed editor was
  approved as S07-EDITOR-G (`dfm-lo0.1`): 8 public calls, all 8 inputs preserved in place and in copy.
- The candidate was packaged on the old 191-file base (`S07-COMBINED-PACK-I-20261105-01`, wheel `87d02495…`), before
  SHORT-CLOSE (`df447d8`) and B06-RUN-PROFILE (`d22876a`). It is not approved product code.
- Frozen source (local, Git-ignored), byte-pinned in `research/checkpoints/20261105-quota-pause/pending/S07-I/`:
  `snapshot/src/dfm_cli/wind_drag.py`, `wind_drag_graph.py`, `wind_drag_text.py`, and `registration.patch` for
  `cli.py`. Proposed tests and example: `research/experiments/S07-I-20261105-01/proposed/tests/test_wind_drag.py`
  (18 tests) and `proposed/examples/wind_drag/`. The behaviour spec is `wind_drag.contract()` in that snapshot
  (`smith-banke-two-breakpoints-v1`) and `research/experiments/S07-I-20261105-01/contract-final.json`.

## R1. Product change

- Add the three modules **byte-identical** to the frozen snapshot. Every module they import exists unchanged on main;
  if one does not, stop and ask.
- `cli.py`: the three registration sites of `registration.patch` only (import, `COMMAND_MODULES["wind"]`, the
  `"wind_drag"` schema entry), applied by hand next to the B06 `source_sink_run_profile` line. Nothing else changes.
- No change to `runs.py`, `run_pump_lifecycle.py` or any other product file. S07 runs through the existing `short`
  profile.
- Result: 196 product files, 100 public commands, schema `wind_drag` equal to the frozen `contract()`, and every
  existing schema entry (including `source_sink_run_profile`) unchanged.

## R2. Tests and example

- `tests/test_wind_drag.py` from the proposed tests, adjusted only where the current base needs it (say which).
- `examples/wind_drag/` from the proposed example, if its commands run unchanged against the rebuilt CLI.
- Full `unittest discover -s tests`: no new failures against the current base (1,756 tests, 33 geo skips on main).

## R3. Public-edit replay

`wind_public` and `calm_public` were edited with an old wheel (`S07-V-20261105-01/public-authored-01/`). Replaying the
same public `wind drag-set` calls on fresh copies of their base inputs with the rebuilt CLI must give byte-identical
files.

## R4. Native acceptance (V-Run; needs a lease and user approval)

Seven sequential `dfm run start <case>/model.mdu --profile short --route direct --install <suite> --timeout 60
--out <fresh>` runs on the predeclared cases (`research/experiments/S07-V-20261105-01/prepared-01/`), with
`public` cases from the R3 replay:
- `wind_base`, `wind_manual`, `wind_public`;
- `calm_base`, `calm_manual`, `calm_public`;
- `direction_control`.

Acceptance:
- **Stress values:** the predeclared values in `prepared-01/predeclared.json`, on `mesh2d_windstressx/y` and
  `mesh2d_windx/y`. For example, τx = τy = 0.169706 Pa at Cd 0.002 and 0.212132 at Cd 0.0025, zero for the calm cases,
  and the sign flip for `direction_control`.
- **Tolerances:** stress 5e-8 Pa absolute, 2e-6 relative, 1e-12 for zero.
- **Time axis:** 121 frames over 0..120 s.
- **Terminal state:** `completed` through the current SHORT-CLOSE lifecycle. The close receipt is the one the current
  manifest records (`job_close`, `close_receipt_source`), not the separate `job-close.json` of the rejected old patch.
- **Stop rule:** stop at the first failure.

## R5. Out of scope

- GUI table-edit parity;
- other drag types or more breakpoints;
- spatial or stress overrides;
- scientific calibration;
- the installed engine's source commit.

## R6. Clarifications (coordinator, after V-Plan; binding for I and V)

1. **A1, test adjustments.** A change to the proposed `test_wind_drag.py` is allowed only where a test asserts a base
   fact that has changed since the old base: product file count, public command count, the set of schema entries
   (for example `source_sink_run_profile`), or a module or fixture path. Each change is listed in the I receipt with
   its reason, and V-Run checks the diff against this list. Any change to an assertion about `wind drag-inspect` or
   `wind drag-set` behaviour, bounds, errors or bytes is a defect.
2. **Example quoting.** Windows PowerShell 5.1 strips the inner double quotes of a native argument, so the
   proposed `--changes '{"..."}'` line fails there. Commit `examples/wind_drag/` with the quoting changed so each
   command runs as written in Windows PowerShell 5.1, and run it once that way. Only the quoting may change.
3. **Registration position (V-Run finding S07-R1-REGISTRATION-POSITION).** "Applied by hand next to the B06
   `source_sink_run_profile` line" in R1 means the patch is applied by hand because B06's line now sits in its
   context. The position is the one `registration.patch` gives: the `"wind_drag"` schema entry directly after
   `"weir_series"`. It does not require the entry to be adjacent to the B06 line. This was the coordinator's
   wording, not a candidate defect.

## Done when

- **I:**
  - R1 and R2, with byte identity of the three modules checked by sha256;
  - `compileall` clean;
  - `python -m dfm_cli schema inspect` shows 100 commands and `wind_drag`;
  - R3 replay identical.
- **V-Plan:** re-binds the predeclared S07 plan to the current product and manifest fields (R4), and fixes the
  reader/oracle pin naming. No native launch.
- **V-Run:** portable checks on the frozen candidate, then R4 after user approval.
- **G:**
  - wheel identity with 196 files;
  - full regression;
  - merge, and a record in the S07 verification note.
