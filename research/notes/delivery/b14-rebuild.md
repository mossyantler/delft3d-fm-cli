# Contract: B14 astronomic constituent assignment, rebuild on current main

Beads: `B14-PUBLIC-I` (`dfm-jtm.6`), `B14-REBIND-V-Plan` (new), `B14-PUBLIC-V-Run` (`dfm-jtm.7`), `B14-G`
(`dfm-jtm.8`). Status: proposal by the coordinator, 2026-11-09. Product verification rules apply in full.

## Background

- B14 adds `boundary constituents-inspect` (read-only) and `boundary constituents-set` (preview, then apply bound to
  the preview hash): exact-uppercase astronomic constituents on existing waterlevel BC supports of one boundary, from
  a version-1 assignment JSON. The behaviour is the private candidate revision02
  (`research/experiments/B14-I-20261105-rev02/HANDOFF.md`, "Proposed contract for V"; `schema-proposal.json`). It
  passed independent installed checks twice (32 tests / 74 calls on the 190- and 194-file wheels;
  `B14-G-combined-inputs-01`: input editing only) and was never merged. Its direct engine runs were held for the
  SHORT-CLOSE lifecycle, which is now accepted.
- The research BMI runner branch (`dfm-jtm.3`, `.4`, `.5`) is **deferred by user decision (2026-11-09)**. B14
  acceptance rests on the two commands and the six direct runs below; no runner result is required or claimed.
- Frozen product files (`B14-I-20261105-rev02/src/dfm_cli/`, byte-identical in
  `B14-I-COMBINED-PACK-20261105-01/snapshot/src/dfm_cli/`):

  | file | sha256 |
  | --- | --- |
  | `boundary_constituents.py` | `42a98ffeb6eeba4b4189fb1c35374572590b58d9b90698556f3b1bda3e41b490` |
  | `boundary_constituents_graph.py` | `739d12fab01132a0c370985d1c4c6748fdc6318cb09a123ee80e707fb7000733` |
  | `boundary_constituents_parse.py` | `d4c0b9f38e6ca595a669cead048a4aa9aae923dafe22518f00f7d65cacdf7e23` |
  | `tests/test_boundary_constituents.py` (25 tests) | `33265b078fb2330039aad060500bffe6c146dc59c9b6ea551050b9490046d5b3` |

- Every module the candidate imports (`common`, `boundary`, `boundary_import`, `boundary_import_graph`,
  `boundary_series`, `boundary_series_parse`, `fm_model_identity`, `model`, `observation_inputs`,
  `pump_edit_contract`, `pump_edit_security`, `pump_edit_write`) is unchanged on main since `df447d8` (static check,
  2026-11-09). The four `cli.py` anchors below each occur once on main.
- Independent V material: the direct gate in `B14-V-RUN-CONTRACT-20261105-01/runner-contract.json` (`direct_gate`,
  sha256 `299246ec…`) and its predeclaration
  `B14-V-installed-rev02-20261105-01/epoch-phase-gate-01/predeclared.json` (`d22cd306…`), with the six prepared
  cases, `assignments.json` and `public-calls.json` in the same folder.

## R1. Product change

- Base: main after `G15-G` merges (expected 209 product files, 105 commands). If G15-G does not merge first, the
  coordinator re-bases this Contract before dispatch.
- Copy the three modules byte for byte; check each sha256 before and after committing. No other product module
  changes.
- `cli.py`: exactly the four insertions of `B14-I-COMBINED-PACK-20261105-01/cli-semantic-replacements.json`, applied
  by hand at these anchors (do not copy any old `cli.py`): `, boundary_constituents` appended to
  `from . import boundary_coefficients, results_stations`; `boundary_constituents.register(boundaries)` after
  `boundary_vertical.register(boundaries)`; `"boundary_constituents": boundary_constituents.contract(),` after
  `"boundary_vertical": boundary_vertical.contract(),`; the `constituents-inspect`/`constituents-set` dispatch branch
  before the `vertical-inspect` branch. New lines use the line ending of the line above; no other byte changes.
- Result: 212 product files, 107 public commands, schema `boundary_constituents` equal to the frozen `contract()`,
  every existing schema entry and command parameter unchanged.

## R2. Tests and README

- `tests/test_boundary_constituents.py` with all 25 tests and the same assertions. Allowed adjustments, each listed
  in the receipt: fixtures under `tempfile`; the CLI through `python -m dfm_cli` or in-process `cli.main`; base facts
  (file and command counts, schema key set). A change to an assertion about `boundary constituents` behaviour,
  bounds, errors or bytes is a defect.
- `README.md`: one paragraph next to the other boundary paragraphs: the two commands, the ten-name catalogue, that
  only A0/M2 have engine evidence, and that harmonic frequencies and corrections refuse. No new example folder.
- Full `unittest discover -s tests`: no new failures against the base.

## R3. Replay of the public edits

- I replays the four calls in `public-calls.json` (preview and apply for epoch2001 and epoch2026) with the rebuilt
  CLI on fresh copies of the retained base inputs, a fresh preview hash for each apply, and compares every resulting
  file byte for byte with the retained `cases/epoch*-public-a0-m2/` inputs. Those inputs must also equal the
  `manual` inputs, as `runner-contract.json` `input_integrity` requires.

## R4. Independent verification

- **V-Plan (rebind):** re-bind the frozen `direct_gate` and predeclaration to the current product without changing
  any prediction, tolerance or acceptance rule: the current `dfm run start --profile short --route direct` command
  and manifest fields (`ownership.job_close`, `ownership.short_lifecycle`); whether the `short` profile writes the
  restart files at 0 and 120 s the gate requires (source lines and earlier run evidence); the timeout `T` with its
  basis; the runner environment (G18 R6.4: `.venv` python with `PYTHONPATH` set to the clean venv's site-packages,
  so `netCDF4` is available); reader/oracle files pinned by sha256. If a gate assumption cannot hold under the
  current lifecycle, say so; do not adapt the acceptance.
- **V-Run portable:** wheel from the frozen candidate in a clean venv (`--no-index --no-deps`); 212 files equal to
  the candidate; schema check against current main; the earlier installed V checks (32 tests / 74 calls) with only
  base facts rebound; regression on candidate and base listing every differing test.
- **V-Run native (after explicit user approval recorded as a HUMAN node, coordinator review and an exclusive
  lease):** the six direct cases, one attempt each, serially, in new folders, judged by the frozen `direct_gate`:
  natural completion with 121 frames, restart files as planned, exact equality of public and manual outputs per
  epoch, A0 controls retained. The prescribed signal is a receiving state, not proof of a constituent phase.

## R5. Out of scope

- The BMI runner branch and its four diagnostics (deferred);
- native evidence for the other eight catalogue names;
- harmonic frequencies, correction pairs, unit conversion, GUI parity;
- POSIX behaviour.

## Done when

- **I:** R1-R3; the three modules unchanged; `compileall` clean; `schema inspect` shows 107 commands and
  `boundary_constituents`; the 25 tests pass; full regression as R2; replay result saved.
- **V-Plan:** R4 rebind documents and wiring checks, with ambiguities listed.
- **V-Run:** R4 portable, then native after approval; PASS or REJECT with reproducing commands.
- **G:** merge; wheel identity with 212 files; full regression; a new verification note
  `research/notes/verification/boundary-constituents.md`; DELIVERY and ROADMAP rows.
